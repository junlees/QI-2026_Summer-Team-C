import json
import os

import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

from model.train import AgriSageCNN, IMG_SIZE

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model")
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

_EVAL_TF = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

_model = None
_classes = None


def _load():
    global _model, _classes
    if _model is not None:
        return
    with open(os.path.join(MODEL_DIR, "classes.json"), encoding="utf-8") as f:
        _classes = json.load(f)
    model = AgriSageCNN(len(_classes))
    state = torch.load(os.path.join(MODEL_DIR, "best_model.pt"), map_location=DEVICE)
    model.load_state_dict(state)
    model.eval()
    model.to(DEVICE)
    _model = model


def classify_image(image_bytes: bytes, top_k: int = 3):
    _load()
    img = Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
    x = _EVAL_TF(img).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        logits = _model(x)
        probs = F.softmax(logits, dim=1)[0]
    top_probs, top_idx = torch.topk(probs, min(top_k, len(_classes)))
    results = [
        {"class_name": _classes[i], "confidence": round(float(p), 4)}
        for p, i in zip(top_probs.tolist(), top_idx.tolist())
    ]
    return results
