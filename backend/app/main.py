from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import db, followup
from app.explain import generate_explanation
from app.model_client import ModelEndpointError, ModelEndpointTimeout, classify_image
from app.pls import check_pls_for_products

app = FastAPI(title="AgriSage API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _crop_disease_name(class_name: str) -> tuple[str, str]:
    info = db.get_disease_info(class_name)
    if info:
        return info["crop"], info["disease_name"]
    # healthy label: "Crop___healthy"
    crop_en = class_name.split("___")[0]
    return crop_en, "Healthy (No Disease)"


def _classify_or_raise(image_bytes: bytes, top_k: int = 3):
    try:
        return classify_image(image_bytes, top_k=top_k)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="The model hasn't been trained yet. Run backend/model/train.py first.",
        )
    except ModelEndpointTimeout as e:
        raise HTTPException(status_code=504, detail=str(e))
    except ModelEndpointError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/diagnose")
async def diagnose(image: UploadFile = File(...)):
    """FR-1: Image diagnosis. Returns the top-3 predicted classes with confidence."""
    image_bytes = await image.read()
    predictions = _classify_or_raise(image_bytes, top_k=3)
    top = predictions[0]
    crop, disease_name = _crop_disease_name(top["class_name"])
    return {
        "predictions": predictions,
        "top": {
            "class_name": top["class_name"],
            "crop": crop,
            "disease_name": disease_name,
            "confidence": top["confidence"],
            "is_healthy": db.is_healthy(top["class_name"]),
        },
    }


@app.post("/api/pipeline")
async def full_pipeline(
    image: UploadFile = File(...),
    expected_harvest_date: str | None = Form(None),
    organic_only: bool = Form(False),
):
    """Runs FR-1 through FR-4 in one call (reproduces the full user flow)."""
    image_bytes = await image.read()
    predictions = _classify_or_raise(image_bytes, top_k=3)

    top = predictions[0]
    class_name = top["class_name"]
    confidence = top["confidence"]
    crop, disease_name = _crop_disease_name(class_name)
    healthy = db.is_healthy(class_name)

    explanation = generate_explanation(crop, disease_name, confidence, healthy, organic_only=organic_only)

    recommendation = None
    pls_results = None
    if not healthy:
        recommendation = db.recommend_products(class_name, organic_only=organic_only)
        if recommendation and expected_harvest_date:
            pls_results = check_pls_for_products(
                recommendation["products"], expected_harvest_date
            )

    low_confidence = confidence < 0.6

    case = None
    if not healthy:
        case = followup.create_case(crop, class_name)

    return {
        "predictions": predictions,
        "diagnosis": {
            "class_name": class_name,
            "crop": crop,
            "disease_name": disease_name,
            "confidence": confidence,
            "is_healthy": healthy,
            "low_confidence_warning": low_confidence,
        },
        "explanation": explanation,
        "recommendation": recommendation,
        "pls_results": pls_results,
        "followup_case": case,
    }


@app.post("/api/recommend")
def recommend(class_name: str = Form(...), organic_only: bool = Form(False)):
    """FR-3: Personalized pesticide recommendation."""
    rec = db.recommend_products(class_name, organic_only=organic_only)
    if rec is None:
        raise HTTPException(status_code=404, detail="No recommendation data for this class.")
    return rec


@app.post("/api/pls-check")
def pls_check(
    class_name: str = Form(...),
    expected_harvest_date: str = Form(...),
    organic_only: bool = Form(False),
):
    """FR-4: Automated PLS (Pre-Harvest Interval) safety compliance check."""
    rec = db.recommend_products(class_name, organic_only=organic_only)
    if rec is None:
        raise HTTPException(status_code=404, detail="No recommendation data for this class.")
    results = check_pls_for_products(rec["products"], expected_harvest_date)
    return {"crop": rec["crop"], "disease_name": rec["disease_name"], "products": results}


@app.post("/api/followup/{case_id}")
async def followup_check(case_id: str, image: UploadFile = File(...)):
    """FR-5: Follow-up check - assess improvement from a re-submitted photo."""
    image_bytes = await image.read()
    try:
        case = followup.submit_followup_photo(case_id, image_bytes)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="The model hasn't been trained yet. Run backend/model/train.py first.",
        )
    except ModelEndpointTimeout as e:
        raise HTTPException(status_code=504, detail=str(e))
    except ModelEndpointError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if case is None:
        raise HTTPException(status_code=404, detail="No case found with this case_id.")
    return case


@app.get("/api/followup/{case_id}")
def followup_get(case_id: str):
    case = followup.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="No case found with this case_id.")
    return case


app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
