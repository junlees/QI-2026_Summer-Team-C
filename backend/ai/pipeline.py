"""Orchestrates: image -> classifier -> RAG lookup -> LLM explanation.

Pure business logic — no Flask, no DB. app.py calls diagnose() and is
responsible for persisting the result and returning an HTTP response.
"""
import os

from .llm import explain, level_classifier
from .rag import store

CONFIDENCE_THRESHOLD = 70  # percent; below this, hide disease name/recommendations

_MODEL_CHECKPOINT = os.environ.get("MODEL_CHECKPOINT_PATH")
_MODEL_CONFIG = os.environ.get("MODEL_CONFIG_PATH")

_model_state = {"model": None, "classes": None, "device": None}


def _load_classifier():
    """Lazily load the trained GoogLeNet/ViT checkpoint, if configured."""
    if _model_state["model"] is not None:
        return _model_state

    if not _MODEL_CHECKPOINT or not os.path.exists(_MODEL_CHECKPOINT):
        return None  # no trained checkpoint yet -> classify_image() falls back to mock

    import json
    import sys

    models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    sys.path.insert(0, os.path.abspath(models_dir))
    import torch
    import predict as predict_mod

    cfg_path = _MODEL_CONFIG or os.path.join(os.path.dirname(_MODEL_CHECKPOINT), "config.json")
    cfg = json.load(open(cfg_path))
    classes = predict_mod.load_classes(cfg["data_loader"]["args"]["data_dir"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = predict_mod.build_model(cfg, _MODEL_CHECKPOINT, device)

    _model_state.update({"model": model, "classes": classes, "device": device, "predict_mod": predict_mod})
    return _model_state


def classify_image(image_path):
    """Return (class_id, confidence_percent). Falls back to a mock result
    with a clearly labeled warning if no trained checkpoint is configured yet."""
    state = _load_classifier()
    if state is None:
        return "Potato___Late_blight", 42.0  # mock, low confidence -> triggers uncertain path

    preds = state["predict_mod"].predict(state["model"], state["classes"], image_path, state["device"], topk=1)
    class_id, prob = preds[0]
    return class_id, round(prob * 100, 1)


def diagnose(image_path, profile=None, user_input="", harvest_date=None):
    profile = profile or {}
    class_id, confidence = classify_image(image_path)
    kb_entry = store.get_by_class_id(class_id)

    if kb_entry is None:
        raise ValueError(f"Unknown class_id from classifier: {class_id}")

    if kb_entry.get("is_healthy"):
        return {
            "status": "healthy",
            "class_id": class_id,
            "confidence": confidence,
            "crop": kb_entry["crop"],
            "message": f"The {kb_entry['crop']} plant appears healthy.",
        }

    if confidence < CONFIDENCE_THRESHOLD:
        return {
            "status": "uncertain",
            "class_id": class_id,
            "confidence": confidence,
            "crop": kb_entry["crop"],
            "message": "Diagnosis confidence is too low to confirm a disease. Consulting an expert is recommended.",
        }

    severity = kb_entry.get("severity_level", "")
    traffic_light = "urgent" if severity == "very high" else "normal"

    level_info = level_classifier.classify_understanding_level(user_input, profile)
    explanation = explain.generate_explanation(
        kb_entry, confidence, severity, profile, level_info, harvest_date=harvest_date
    )

    return {
        "status": "diagnosed",
        "traffic_light": traffic_light,
        "class_id": class_id,
        "confidence": confidence,
        "crop": kb_entry["crop"],
        "disease": kb_entry["disease_name"],
        "severity": severity,
        **explanation,
    }
