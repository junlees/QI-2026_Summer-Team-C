"""FR-2: Diagnosis explanation generation.

Only the already-confirmed classification result (crop, disease name) is passed
to the LLM; the LLM never makes a new diagnosis. If ANTHROPIC_API_KEY is set,
Claude API is called; otherwise this falls back to a template-based explanation
(works fully offline / without an API key for local testing).
"""
import json
import os

_client = None


def _get_client():
    global _client
    if _client is None and os.environ.get("ANTHROPIC_API_KEY"):
        from anthropic import Anthropic
        _client = Anthropic()
    return _client


SYSTEM_PROMPT = (
    "You are AgriSage's farming explanation assistant. Base your explanation only on "
    "the already-confirmed image classification result (crop, disease name) provided to "
    "you. Never make a new diagnosis or change the classification result yourself. Write "
    "in plain language a beginner grower can understand, and respond with JSON only. "
    "Keys: greeting, disease_title, disease_explanation, cause, recommended_products, "
    "reasoning, spray_interval, severity, severity_note, other_precautions."
)


def generate_explanation(
    crop: str, disease_name: str, confidence: float, is_healthy: bool, organic_only: bool = False
):
    client = _get_client()
    if client is None:
        return _template_explanation(crop, disease_name, confidence, is_healthy, organic_only)

    user_prompt = (
        f"Crop: {crop}\nDisease name: {disease_name}\nClassification confidence: {confidence:.1%}\n"
        f"Healthy: {'yes' if is_healthy else 'no'}\nOrganic-only filter: {'yes' if organic_only else 'no'}\n"
        "Based only on the confirmed classification result above, write a greeting, disease "
        "explanation, cause, recommended products with reasoning, spray interval, and safety "
        "precautions (severity + other precautions) as JSON."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = resp.content[0].text
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start:end + 1])
        data["source"] = "llm"
        return data
    except Exception as e:
        fallback = _template_explanation(crop, disease_name, confidence, is_healthy, organic_only)
        fallback["llm_error"] = str(e)
        return fallback


def _template_explanation(
    crop: str, disease_name: str, confidence: float, is_healthy: bool, organic_only: bool = False
):
    if is_healthy:
        return {
            "greeting": "Welcome to farming! Here is the explanation of your diagnosis and the steps you should take.",
            "disease_title": "Healthy",
            "disease_explanation": (
                f"Your {crop.lower()} leaves were classified as healthy, with no visible disease "
                f"symptoms (confidence {confidence:.0%})."
            ),
            "cause": "No abnormal cause was found.",
            "recommended_products": "No treatment is needed at this time.",
            "reasoning": "The plant shows no signs of infection, so no pesticide application is recommended.",
            "spray_interval": "Not applicable.",
            "severity": "None",
            "severity_note": "Keep up your current care routine (watering, fertilizing, airflow).",
            "other_precautions": "Recheck your leaves periodically so you catch early signs of trouble.",
            "source": "template",
        }

    # Curated demo content: Potato Late Blight + organic-only filter.
    if crop == "Potato" and disease_name == "Late Blight" and organic_only:
        return {
            "greeting": (
                "Welcome to farming! Here is the explanation of your diagnosis and the steps "
                "you should take to protect your potato crop."
            ),
            "disease_title": "Late Blight",
            "disease_explanation": (
                'Your potatoes are affected by Late Blight. In simple terms, this disease causes dark '
                'brown spots on the leaves that look "water-soaked," as if the tissue is rotting from '
                "moisture. A key sign to look for is a white, fuzzy mold-like growth forming a border "
                "on the underside of those infected leaves."
            ),
            "cause": (
                "This disease is caused by a pathogen that spreads very rapidly during cool and humid "
                "(damp) weather. These conditions allow the fungus-like organism to multiply and jump "
                "from plant to plant quickly."
            ),
            "recommended_products": "Copper-based fungicides (such as Bordeaux mixture) and other organic-certified materials.",
            "reasoning": (
                "Because you are maintaining an organic certification for self-consumption, we have "
                "selected only naturally-derived options. Chemical fungicides (like dimethomorph) have "
                "been excluded because they are not allowed under organic standards."
            ),
            "spray_interval": (
                "You must apply the treatment every 5 to 7 days. Because the disease spreads so fast, "
                "staying consistent with this schedule is vital to saving your crop."
            ),
            "severity": "Very high",
            "severity_note": (
                "You should prioritize treatment immediately to prevent the total loss of your plants."
            ),
            "other_precautions": (
                "Specific chemical handling precautions are not available. Always follow the "
                "instructions on the specific product label you purchase."
            ),
            "source": "template",
        }

    return {
        "greeting": "Welcome to farming! Here is the explanation of your diagnosis and the steps you should take.",
        "disease_title": disease_name,
        "disease_explanation": (
            f"Your {crop.lower()} was classified with '{disease_name}' (confidence {confidence:.0%})."
        ),
        "cause": "Excess moisture, poor airflow, and pathogen/bacterial spread are the most common causes.",
        "recommended_products": "See the recommended products and PHI (safe-use period) table below.",
        "reasoning": (
            "Products were filtered to organic-certified options only."
            if organic_only
            else "Both conventional and organic-certified options are shown; pick based on your certification needs."
        ),
        "spray_interval": "Follow the product label's recommended spray interval.",
        "severity": "Moderate to high",
        "severity_note": "Remove infected leaves and debris to slow the spread, then treat promptly.",
        "other_precautions": (
            "Check the recommended products' PHI (pre-harvest interval) before spraying, and "
            "re-check the plant 3-5 days after treatment."
        ),
        "source": "template",
    }
