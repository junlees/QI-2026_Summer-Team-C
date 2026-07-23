"""Orchestrates: image -> classifier -> RAG lookup -> LLM explanation.

Pure business logic — no Flask, no DB. app.py calls diagnose() and is
responsible for persisting the result and returning an HTTP response.
"""
import os

from .llm import explain, level_classifier
from .rag import store

CONFIDENCE_THRESHOLD = 70  # percent; below this, hide disease name/recommendations

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_model_state = {"model": None, "classes": None, "device": None}


def _resolve_path(path):
    """Resolve env-var paths against the repo root so relative values work
    regardless of CWD (repo root, backend/, gunicorn --chdir backend)."""
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.join(_REPO_ROOT, path)

def _ensure_models_on_path():
    """Add backend/models to sys.path (idempotent) so its modules import."""
    import sys

    models_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models"))
    if models_dir not in sys.path:
        sys.path.insert(0, models_dir)


def _load_classes(cfg, ckpt_path, predict_mod):
    """Class index -> name list. A committed classes.json (MODEL_CLASSES_PATH,
    or one sitting next to the checkpoint) wins; otherwise fall back to listing
    the training data_dir, which only exists on dev machines."""
    import json

    classes_path = _resolve_path(os.environ.get("MODEL_CLASSES_PATH")) or os.path.join(
        os.path.dirname(ckpt_path), "classes.json"
    )
    if os.path.exists(classes_path):
        return json.load(open(classes_path))
    return predict_mod.load_classes(cfg["data_loader"]["args"]["data_dir"])


def _load_classifier():
    """Lazily load the trained GoogLeNet/ViT checkpoint, if configured."""
    if _model_state["model"] is not None:
        return _model_state

    ckpt_path = _resolve_path(os.environ.get("MODEL_CHECKPOINT_PATH"))
    if not ckpt_path or not os.path.exists(ckpt_path):
        return None  # no trained checkpoint yet -> classify_image() falls back to mock

    import json

    _ensure_models_on_path()
    import torch
    import predict as predict_mod

    cfg_path = _resolve_path(os.environ.get("MODEL_CONFIG_PATH")) or os.path.join(
        os.path.dirname(ckpt_path), "config.json"
    )
    cfg = json.load(open(cfg_path))
    classes = _load_classes(cfg, ckpt_path, predict_mod)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = predict_mod.build_model(cfg, ckpt_path, device)

    _model_state.update({"model": model, "classes": classes, "device": device, "predict_mod": predict_mod})
    return _model_state


def _detect_leaf(image_path):
    """Detect the center-most leaf and crop it. Returns (result_dict, reason);
    result_dict is None on any failure — detection must never crash the pipeline."""
    try:
        _ensure_models_on_path()
        import leaf_detect

        return leaf_detect.detect_and_crop_leaf(image_path), None
    except Exception as exc:  # ImportError (no cv2), unreadable image, ...
        return None, f"{type(exc).__name__}: {exc}"


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

    detection, detect_reason = _detect_leaf(image_path)
    if detection is not None:
        classify_path = detection["cropped_path"]
        leaf_detection = {
            "applied": True,
            "num_candidates": detection["num_candidates"],
            "method": detection["method_used"],
            "bbox": detection["bbox"],
            "cropped_image": os.path.basename(detection["cropped_path"]),
            "fallback": detection["fallback"],
        }
    else:
        classify_path = image_path
        leaf_detection = {"applied": False, "reason": detect_reason}

    class_id, confidence = classify_image(classify_path)
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
            "leaf_detection": leaf_detection,
        }

    if confidence < CONFIDENCE_THRESHOLD:
        return {
            "status": "uncertain",
            "class_id": class_id,
            "confidence": confidence,
            "crop": kb_entry["crop"],
            "message": "Diagnosis confidence is too low to confirm a disease. Consulting an expert is recommended.",
            "leaf_detection": leaf_detection,
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
        "leaf_detection": leaf_detection,
        **explanation,
    }
