import datetime
import json
import os
import uuid

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from ai import pipeline
from ai.llm import chat
from db import crud, models

# Serve the static frontend that lives in ../frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB
models.init_db()


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


@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "landing.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# --- API ---------------------------------------------------------------
@app.route("/api/diagnose", methods=["POST"])
def diagnose():
    image = request.files.get("image")
    if image is None:
        return jsonify({"status": "error", "message": "image file is required"}), 400

    safe_filename, error = _validate_image(image)
    if error:
        return jsonify({"status": "error", "message": error}), 400

    harvest_date, error = _parse_harvest_date(request.form.get("harvest_date"))
    if error:
        return jsonify({"status": "error", "message": error}), 400

    crop_id = request.form.get("crop_id")
    user_input = request.form.get("user_input", "")
    profile = {
        "certification": request.form.get("certification"),
        "growing_environment": request.form.get("growing_environment"),
        "purpose": request.form.get("purpose"),
    }

    filename = f"{uuid.uuid4().hex}_{safe_filename}"
    image_path = os.path.join(UPLOAD_DIR, filename)
    image.save(image_path)

    result = pipeline.diagnose(image_path, profile=profile, user_input=user_input, harvest_date=harvest_date)

    diagnosis_id = crud.save_diagnosis(
        crop_id=crop_id,
        class_id=result["class_id"],
        confidence=result["confidence"],
        status=result["status"],
        result=result,
        follow_up_target_date=None,
    )
    result["diagnosis_id"] = diagnosis_id
    return jsonify(result)


@app.route("/api/diagnose/<int:diagnosis_id>/ask", methods=["POST"])
def diagnose_ask(diagnosis_id):
    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()
    if not question:
        return jsonify({"status": "error", "message": "question is required"}), 400

    answer = chat.answer_question(question)
    return jsonify(answer)


@app.route("/api/history", methods=["GET"])
def history():
    rows = crud.get_history()
    for row in rows:
        row["result"] = json.loads(row.pop("result_json"))
    return jsonify(rows)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
