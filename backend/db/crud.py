"""Read/write helpers for users, crops, diagnosis history and follow-ups.

All queries use explicit column lists (never SELECT *) so adding a column can
never silently leak into an API response.
"""
import datetime
import json

from . import models

# Fixed KST offset: Korea has not observed DST since 1988, so a constant
# offset avoids the tzdata dependency in the slim production image.
KST = datetime.timezone(datetime.timedelta(hours=9))


def kst_today_start_utc():
    """UTC timestamp string for today's KST midnight, in the same
    "YYYY-MM-DD HH:MM:SS" format SQLite's datetime('now') writes — so a
    lexical `created_at >= ?` compare is correct and index-friendly."""
    now_kst = datetime.datetime.now(KST)
    midnight_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_kst.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --- users -------------------------------------------------------------

_USER_COLS = "id, created_at, email, password_hash, role, certification, purpose, daily_limit"


def create_user(email, password_hash, certification, purpose):
    """Insert a user and return its id. Raises sqlite3.IntegrityError on a
    duplicate email (callers map it to 409) — race-safe, no SELECT-then-INSERT."""
    conn = models.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, certification, purpose) "
            "VALUES (?, ?, ?, ?)",
            (email, password_hash, certification, purpose),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_email(email):
    conn = models.get_connection()
    try:
        row = conn.execute(
            f"SELECT {_USER_COLS} FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = models.get_connection()
    try:
        row = conn.execute(
            f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_user_profile(user_id, certification, purpose):
    conn = models.get_connection()
    try:
        conn.execute(
            "UPDATE users SET certification = ?, purpose = ? WHERE id = ?",
            (certification, purpose, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_admin(email, password_hash):
    """Seed (or refresh) the admin account from the environment at boot.
    Updating the hash every boot means an ADMIN_PASSWORD rotation in .env takes
    effect on restart; on Cloud Run's in-memory filesystem this same call also
    recreates the admin after every cold start. daily_limit NULL = unlimited."""
    conn = models.get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET password_hash = ?, role = 'admin', daily_limit = NULL "
                "WHERE id = ?",
                (password_hash, row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO users (email, password_hash, role, daily_limit) "
                "VALUES (?, ?, 'admin', NULL)",
                (email, password_hash),
            )
        conn.commit()
    finally:
        conn.close()


def set_daily_limit(user_id, daily_limit):
    """daily_limit: int >= 0, or None for unlimited. Returns False for an
    unknown user id."""
    conn = models.get_connection()
    try:
        cur = conn.execute(
            "UPDATE users SET daily_limit = ? WHERE id = ?", (daily_limit, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def admin_list_users(today_start_utc):
    conn = models.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.created_at, u.email, u.role, u.certification, u.purpose,
                   u.daily_limit,
                   (SELECT COUNT(*) FROM diagnoses d
                     WHERE d.user_id = u.id AND d.created_at >= ?) AS used_today,
                   (SELECT COUNT(*) FROM diagnoses d
                     WHERE d.user_id = u.id) AS total_count,
                   (SELECT MAX(d.created_at) FROM diagnoses d
                     WHERE d.user_id = u.id) AS last_diagnosis_at
            FROM users u
            ORDER BY u.id ASC
            """,
            (today_start_utc,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- crops -------------------------------------------------------------

_CROP_COLS = "id, user_id, created_at, name, emoji, color, growing_environment, purpose_override, harvest_date"


def create_crop(user_id, name, emoji, color, growing_environment, purpose_override, harvest_date):
    conn = models.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO crops (user_id, name, emoji, color, growing_environment, "
            "purpose_override, harvest_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, emoji, color, growing_environment, purpose_override, harvest_date),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {_CROP_COLS} FROM crops WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_crops(user_id):
    # ORDER BY id ASC: the dashboard treats the LAST element as the most
    # recently registered crop (its main CTA links to it).
    conn = models.get_connection()
    try:
        rows = conn.execute(
            f"SELECT {_CROP_COLS} FROM crops WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_crop(user_id, crop_id):
    conn = models.get_connection()
    try:
        row = conn.execute(
            f"SELECT {_CROP_COLS} FROM crops WHERE id = ? AND user_id = ?",
            (crop_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_crop(user_id, crop_id, growing_environment=None, purpose_override=...,
                harvest_date=None):
    """Partial update; purpose_override uses ... as the "not provided" sentinel
    because None is a meaningful value (= use the account default).
    Returns False when the crop doesn't exist or isn't owned by user_id."""
    fields, params = [], []
    if growing_environment is not None:
        fields.append("growing_environment = ?")
        params.append(growing_environment)
    if purpose_override is not ...:
        fields.append("purpose_override = ?")
        params.append(purpose_override)
    if harvest_date is not None:
        fields.append("harvest_date = ?")
        params.append(harvest_date)
    if not fields:
        return get_crop(user_id, crop_id) is not None

    conn = models.get_connection()
    try:
        cur = conn.execute(
            f"UPDATE crops SET {', '.join(fields)} WHERE id = ? AND user_id = ?",
            (*params, crop_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_crop(user_id, crop_id):
    conn = models.get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM crops WHERE id = ? AND user_id = ?", (crop_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# --- diagnoses ---------------------------------------------------------

def save_diagnosis(crop_id, class_id, confidence, status, result,
                   follow_up_target_date=None, user_id=None, follow_up_status=None):
    conn = models.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO diagnoses (user_id, crop_id, class_id, confidence, status, "
            "result_json, follow_up_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, crop_id, class_id, confidence, status,
             json.dumps(result, ensure_ascii=False), follow_up_status),
        )
        diagnosis_id = cur.lastrowid

        if follow_up_target_date:
            conn.execute(
                "INSERT INTO follow_up_reminders (diagnosis_id, target_date) VALUES (?, ?)",
                (diagnosis_id, follow_up_target_date),
            )
        conn.commit()
        return diagnosis_id
    finally:
        conn.close()


def get_history(user_id):
    """The user's diagnoses, newest first, with the crop's display fields
    joined in (LEFT JOIN — the crop may have been deleted since)."""
    conn = models.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.created_at, d.status, d.confidence, d.result_json,
                   d.follow_up_status,
                   c.name AS crop_name, c.emoji AS crop_emoji, c.color AS crop_color
            FROM diagnoses d
            LEFT JOIN crops c ON c.id = d.crop_id AND c.user_id = d.user_id
            WHERE d.user_id = ?
            ORDER BY d.created_at DESC, d.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_diagnosis(user_id, diagnosis_id):
    conn = models.get_connection()
    try:
        row = conn.execute(
            "SELECT id, created_at, user_id, crop_id, class_id, confidence, status, "
            "result_json, follow_up_status FROM diagnoses WHERE id = ? AND user_id = ?",
            (diagnosis_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_follow_up_status(user_id, diagnosis_id, status):
    conn = models.get_connection()
    try:
        cur = conn.execute(
            "UPDATE diagnoses SET follow_up_status = ? WHERE id = ? AND user_id = ?",
            (status, diagnosis_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def count_diagnoses_since(user_id, since_utc):
    conn = models.get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM diagnoses WHERE user_id = ? AND created_at >= ?",
            (user_id, since_utc),
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


# --- follow-up reminders (still unwired — no callers yet) --------------

def get_due_follow_ups(today=None):
    """Reminders whose target_date has arrived and haven't been sent yet.

    No background scheduler yet — call this on-demand (e.g. on app load)
    per CLAUDE.md's "async reminder" step; a real push/cron job comes later.
    """
    today = today or datetime.date.today().isoformat()
    conn = models.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, diagnosis_id, target_date, sent FROM follow_up_reminders "
            "WHERE sent = 0 AND target_date <= ?",
            (today,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_follow_up_sent(reminder_id):
    conn = models.get_connection()
    try:
        conn.execute("UPDATE follow_up_reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        conn.commit()
    finally:
        conn.close()
