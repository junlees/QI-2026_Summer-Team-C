import os

from flask import Flask, jsonify, send_from_directory

# Serve the static frontend that lives in ../frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")


@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "landing.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# --- API ---------------------------------------------------------------
# Placeholder for the diagnosis model. Wire the real model in later
# (see backend/models/). Kept separate from the static routes above so the
# frontend can start calling POST /api/diagnose during development.
@app.route("/api/diagnose", methods=["POST"])
def diagnose():
    return jsonify(
        {
            "status": "not_implemented",
            "message": "Diagnosis model is not connected yet.",
        }
    ), 501


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
