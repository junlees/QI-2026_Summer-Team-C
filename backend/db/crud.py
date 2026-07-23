"""Read/write helpers for diagnosis history and follow-up reminders."""
import datetime
import json

from . import models


def save_diagnosis(crop_id, class_id, confidence, status, result, follow_up_target_date=None):
    conn = models.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO diagnoses (crop_id, class_id, confidence, status, result_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (crop_id, class_id, confidence, status, json.dumps(result, ensure_ascii=False)),
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


def get_history():
    conn = models.get_connection()
    try:
        rows = conn.execute("SELECT * FROM diagnoses ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_due_follow_ups(today=None):
    """Reminders whose target_date has arrived and haven't been sent yet.

    No background scheduler yet — call this on-demand (e.g. on app load)
    per CLAUDE.md's "async reminder" step; a real push/cron job comes later.
    """
    today = today or datetime.date.today().isoformat()
    conn = models.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM follow_up_reminders WHERE sent = 0 AND target_date <= ?",
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
