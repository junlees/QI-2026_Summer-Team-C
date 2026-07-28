import datetime
import json
import logging
import os
import re
import sqlite3
import uuid

# Load .env BEFORE anything reads the environment (JWT_SECRET, ADMIN_*,
# OPENAI_*). Previously this only happened as a side effect of importing
# ai.llm.client — too fragile an ordering to hang auth secrets on.
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

import auth
from ai import pipeline
from ai.llm import chat
from db import crud, models

# Serve the static frontend that lives in ../frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
CERTIFICATIONS = {"conventional", "organic"}
PURPOSES = {"self_consumption", "sale"}
GROWING_ENVIRONMENTS = {"open_field", "greenhouse"}
EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")
DEFAULT_DAILY_LIMIT = 3

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB
models.init_db()


def _seed_admin():
    """Create/refresh the admin account from ADMIN_ID/ADMIN_PASSWORD. Runs at
    every boot so the account survives Cloud Run's in-memory DB resets and
    picks up password rotations. Never log the values."""
    admin_id = (os.environ.get("ADMIN_ID") or "").strip()
    admin_password = os.environ.get("ADMIN_PASSWORD") or ""
    if admin_id and admin_password:
        crud.upsert_admin(admin_id, auth.hash_password(admin_password))
    else:
        logging.getLogger(__name__).warning(
            "ADMIN_ID/ADMIN_PASSWORD not set; admin account not seeded."
        )


_seed_admin()


@app.errorhandler(413)
def payload_too_large(e):
    return jsonify({"status": "error", "message": "Image too large (max 10 MB)."}), 413


def _validate_image(image):
    filename = secure_filename(image.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "image must be a .jpg, .jpeg, or .png file"
    return filename, None


def _parse_harvest_date(raw_value):
    if not raw_value:
        return None, None
    try:
        datetime.date.fromisoformat(raw_value)
    except ValueError:
        return None, "harvest_date must be in YYYY-MM-DD format"
    return raw_value, None


def _profile_response(user):
    return {
        "email": user["email"],
        "role": user["role"],
        "certification": user["certification"],
        "purpose": user["purpose"],
        "daily_limit": user["daily_limit"],
        "used_today": crud.count_diagnoses_since(user["id"], crud.kst_today_start_utc()),
    }


def _current_user_or_401():
    """Fresh users row for the token's uid. None means the row is gone (e.g.
    Cloud Run reset the in-memory DB after this token was issued) — callers
    return the 401 to force a clean re-login."""
    return crud.get_user_by_id(g.user["uid"])


_STALE_SESSION = (
    {"status": "error", "message": "Session is no longer valid. Please log in again."},
    401,
)


@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "landing.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# --- auth --------------------------------------------------------------
@app.route("/api/signup", methods=["POST"])
def signup():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    certification = body.get("certification") or "conventional"
    purpose = body.get("purpose") or "self_consumption"

    if not EMAIL_RE.match(email):
        return jsonify({"status": "error", "message": "Please enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters."}), 400
    if certification not in CERTIFICATIONS or purpose not in PURPOSES:
        return jsonify({"status": "error", "message": "Invalid certification or purpose value."}), 400

    try:
        user_id = crud.create_user(email, auth.hash_password(password), certification, purpose)
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "An account with this email already exists."}), 409

    user = crud.get_user_by_id(user_id)
    return jsonify({"token": auth.issue_token(user), "profile": _profile_response(user)}), 201


@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    user = crud.get_user_by_email(email)
    # Same message for unknown email and wrong password — no user enumeration.
    if user is None or not auth.verify_password(user["password_hash"], password):
        return jsonify({"status": "error", "message": "Invalid email or password."}), 401

    return jsonify({"token": auth.issue_token(user), "profile": _profile_response(user)})


@app.route("/api/profile", methods=["GET"])
@auth.require_auth
def get_profile():
    user = _current_user_or_401()
    if user is None:
        return jsonify(_STALE_SESSION[0]), _STALE_SESSION[1]
    return jsonify(_profile_response(user))


@app.route("/api/profile", methods=["PUT"])
@auth.require_auth
def update_profile():
    user = _current_user_or_401()
    if user is None:
        return jsonify(_STALE_SESSION[0]), _STALE_SESSION[1]

    body = request.get_json(silent=True) or {}
    certification = body.get("certification", user["certification"])
    purpose = body.get("purpose", user["purpose"])
    if certification not in CERTIFICATIONS or purpose not in PURPOSES:
        return jsonify({"status": "error", "message": "Invalid certification or purpose value."}), 400

    crud.update_user_profile(user["id"], certification, purpose)
    return jsonify(_profile_response(crud.get_user_by_id(user["id"])))


# --- crops -------------------------------------------------------------
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _validate_crop_fields(body, partial=False):
    """Shared validation for create/update. Returns (fields, error)."""
    fields = {}

    if "name" in body or not partial:
        name = (body.get("name") or "").strip()
        if not name or len(name) > 40:
            return None, "name is required (max 40 characters)"
        fields["name"] = name
    if "emoji" in body or not partial:
        emoji = (body.get("emoji") or "").strip()
        if len(emoji) > 8:
            return None, "emoji is too long"
        fields["emoji"] = emoji or None
    if "color" in body or not partial:
        color = (body.get("color") or "").strip()
        # Stored value lands in style="background:..." templates — allow hex only.
        if color and not _COLOR_RE.match(color):
            return None, "color must be a hex value like #3f7d20"
        fields["color"] = color or None
    if "growing_environment" in body or not partial:
        env = body.get("growing_environment") or "open_field"
        if env not in GROWING_ENVIRONMENTS:
            return None, "growing_environment must be open_field or greenhouse"
        fields["growing_environment"] = env
    if "purpose_override" in body or not partial:
        override = body.get("purpose_override")
        if override is not None and override not in PURPOSES:
            return None, "purpose_override must be self_consumption, sale, or null"
        fields["purpose_override"] = override
    if "harvest_date" in body or not partial:
        harvest_date, error = _parse_harvest_date(body.get("harvest_date"))
        if error:
            return None, error
        fields["harvest_date"] = harvest_date

    return fields, None


@app.route("/api/crops", methods=["GET"])
@auth.require_auth
def list_crops():
    return jsonify(crud.get_crops(g.user["uid"]))


@app.route("/api/crops", methods=["POST"])
@auth.require_auth
def add_crop():
    fields, error = _validate_crop_fields(request.get_json(silent=True) or {})
    if error:
        return jsonify({"status": "error", "message": error}), 400
    crop = crud.create_crop(
        g.user["uid"], fields["name"], fields["emoji"], fields["color"],
        fields["growing_environment"], fields["purpose_override"], fields["harvest_date"],
    )
    return jsonify(crop), 201


@app.route("/api/crops/<int:crop_id>", methods=["PUT"])
@auth.require_auth
def edit_crop(crop_id):
    body = request.get_json(silent=True) or {}
    fields, error = _validate_crop_fields(body, partial=True)
    if error:
        return jsonify({"status": "error", "message": error}), 400

    updated = crud.update_crop(
        g.user["uid"], crop_id,
        growing_environment=fields.get("growing_environment"),
        purpose_override=fields["purpose_override"] if "purpose_override" in fields else ...,
        harvest_date=fields.get("harvest_date"),
    )
    if not updated:
        return jsonify({"status": "error", "message": "Crop not found."}), 404
    return jsonify(crud.get_crop(g.user["uid"], crop_id))


@app.route("/api/crops/<int:crop_id>", methods=["DELETE"])
@auth.require_auth
def remove_crop(crop_id):
    if not crud.delete_crop(g.user["uid"], crop_id):
        return jsonify({"status": "error", "message": "Crop not found."}), 404
    return jsonify({"status": "ok"})


# --- diagnosis ---------------------------------------------------------
@app.route("/api/diagnose", methods=["POST"])
@auth.require_auth
def diagnose():
    image = request.files.get("image")
    if image is None:
        return jsonify({"status": "error", "message": "image file is required"}), 400

    safe_filename, error = _validate_image(image)
    if error:
        return jsonify({"status": "error", "message": error}), 400

    crop_id = request.form.get("crop_id", type=int)
    if crop_id is None:
        return jsonify({"status": "error", "message": "crop_id is required"}), 400
    crop = crud.get_crop(g.user["uid"], crop_id)
    if crop is None:
        return jsonify({"status": "error", "message": "Crop not found."}), 404

    user = _current_user_or_401()
    if user is None:
        return jsonify(_STALE_SESSION[0]), _STALE_SESSION[1]

    # Daily quota — checked BEFORE the upload is saved so over-limit requests
    # leave no orphan files. Count-then-insert isn't atomic across gunicorn's
    # 4 threads; the worst case is one extra diagnosis, accepted for the demo.
    if user["daily_limit"] is not None:
        used = crud.count_diagnoses_since(user["id"], crud.kst_today_start_utc())
        if used >= user["daily_limit"]:
            return jsonify({
                "status": "error",
                "message": f"Daily diagnosis limit reached ({user['daily_limit']}/day). "
                           "Try again tomorrow.",
            }), 429

    user_input = request.form.get("user_input", "")
    # Server-authoritative personalization: the client no longer sends these —
    # they come from the account and the registered crop.
    effective_purpose = crop["purpose_override"] or user["purpose"] or "self_consumption"
    profile = {
        "certification": user["certification"],
        "growing_environment": crop["growing_environment"],
        "purpose": effective_purpose,
    }

    filename = f"{uuid.uuid4().hex}_{safe_filename}"
    image_path = os.path.join(UPLOAD_DIR, filename)
    image.save(image_path)

    try:
        result = pipeline.diagnose(
            image_path, profile=profile, user_input=user_input,
            harvest_date=crop["harvest_date"],
        )
    except Exception:
        app.logger.exception("pipeline.diagnose failed for %s", filename)
        return jsonify({
            "status": "error",
            "message": "Analysis failed — the file may not be a valid photo. Please try another image.",
        }), 500

    # Recorded inside result_json (i.e. BEFORE save) so history re-entries can
    # show the purpose used at diagnosis time, not the current profile value.
    result["effective_purpose"] = effective_purpose
    diagnosis_id = crud.save_diagnosis(
        crop_id=crop["id"],
        class_id=result["class_id"],
        confidence=result["confidence"],
        status=result["status"],
        result=result,
        follow_up_target_date=None,
        user_id=user["id"],
        # Healthy/uncertain results have no treatment to follow up on — mark
        # them so the dashboard banner and history badge skip them.
        follow_up_status="not_needed" if result["status"] in ("healthy", "uncertain") else None,
    )
    result["diagnosis_id"] = diagnosis_id
    return jsonify(result)


@app.route("/api/diagnose/<int:diagnosis_id>/ask", methods=["POST"])
@auth.require_auth
def diagnose_ask(diagnosis_id):
    if crud.get_diagnosis(g.user["uid"], diagnosis_id) is None:
        return jsonify({"status": "error", "message": "Diagnosis not found."}), 404

    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()
    if not question:
        return jsonify({"status": "error", "message": "question is required"}), 400

    answer = chat.answer_question(question)
    return jsonify(answer)


@app.route("/api/diagnose/<int:diagnosis_id>/follow-up", methods=["PUT"])
@auth.require_auth
def diagnose_follow_up(diagnosis_id):
    body = request.get_json(silent=True) or {}
    status = body.get("follow_up_status")
    if status not in ("resolved", "escalate"):
        return jsonify({"status": "error", "message": "follow_up_status must be resolved or escalate"}), 400
    if not crud.set_follow_up_status(g.user["uid"], diagnosis_id, status):
        return jsonify({"status": "error", "message": "Diagnosis not found."}), 404
    return jsonify({"status": "ok"})


def _shape_history_entry(row):
    """Server row -> the exact entry shape the pages have always rendered."""
    result = json.loads(row["result_json"])
    result["diagnosis_id"] = row["id"]

    status = row["status"]
    if status == "uncertain":
        disease = "Unidentified (low confidence)"
    elif status == "healthy":
        disease = "Healthy — no disease"
    else:
        disease = result.get("disease") or "Diagnosed"

    # Dates are KST — same boundary the daily limit uses.
    created = datetime.datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    date_kst = created.replace(tzinfo=datetime.timezone.utc).astimezone(crud.KST)

    return {
        "id": row["id"],
        "date": date_kst.date().isoformat(),
        # Fallbacks for entries whose crop was deleted since the diagnosis.
        "cropName": row["crop_name"] or result.get("crop") or "Crop",
        "emoji": row["crop_emoji"] or "🌱",
        "color": row["crop_color"] or "#3f7d20",
        "disease": disease,
        "confidence": round(row["confidence"]),
        "followUpStatus": row["follow_up_status"],
        "result": result,
    }


@app.route("/api/history", methods=["GET"])
@auth.require_auth
def history():
    rows = crud.get_history(g.user["uid"])
    return jsonify([_shape_history_entry(row) for row in rows])


# --- admin -------------------------------------------------------------
@app.route("/api/admin/users", methods=["GET"])
@auth.require_admin
def admin_users():
    return jsonify(crud.admin_list_users(crud.kst_today_start_utc()))


@app.route("/api/admin/users/<int:user_id>/limit", methods=["PUT"])
@auth.require_admin
def admin_set_limit(user_id):
    body = request.get_json(silent=True) or {}
    limit = body.get("daily_limit", ...)
    # Strict type check: bool is an int subclass, reject it explicitly.
    valid = limit is None or (isinstance(limit, int) and not isinstance(limit, bool) and 0 <= limit <= 999)
    if limit is ... or not valid:
        return jsonify({"status": "error", "message": "daily_limit must be a non-negative integer or null."}), 400
    if not crud.set_daily_limit(user_id, limit):
        return jsonify({"status": "error", "message": "User not found."}), 404
    return jsonify({"status": "ok", "daily_limit": limit})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
