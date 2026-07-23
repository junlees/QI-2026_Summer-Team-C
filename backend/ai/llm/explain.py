"""Generate the user-facing explanation + personalized recommendation.

Grounded strictly in the retrieved knowledge-base entry — the prompt
forbids inventing symptoms, products, or safety numbers not present in
the provided context. Tone/vocabulary adapts to the understanding-level
classification from level_classifier.py.
"""
from . import pls

_PROMPT_TEMPLATE = """# Role
You are an agricultural expert explaining a crop disease diagnosis result. Base your answer ONLY on the "Knowledge Base Info" below.
Do not invent any disease name, symptom, active ingredient, or number that isn't in the knowledge base.

# User Understanding Level
- Level: {level}
- Recommended tone: {tone}

# User Profile
{profile}

# Diagnosis Result
- Crop: {crop}
- Disease: {disease}
- Confidence: {confidence}%
- Severity: {severity}

# Knowledge Base Info
{kb_context}

# Output Format (Strict JSON Only, no other text)
{{
  "diagnosis_summary": "1-2 sentences summarizing the diagnosis",
  "disease_characteristics": "Symptom description (based on the knowledge base's symptoms field)",
  "cause": "Cause explanation (based on the knowledge base's causal_conditions field)",
  "recommended_actions": ["action 1", "action 2", "..."]
}}

Write ALL text in English, using vocabulary and tone matching the "User Understanding Level".
"""


def generate_explanation(kb_entry, confidence, severity, profile, level_info, harvest_date=None):
    from . import client
    from ..rag import store

    kb_context = store.render_entry_markdown(kb_entry)

    prompt = _PROMPT_TEMPLATE.format(
        level=level_info["understanding_level"],
        tone=level_info["recommended_tone"],
        profile=profile or {},
        crop=kb_entry["crop"],
        disease=kb_entry["disease_name"],
        confidence=round(confidence * 100, 1) if confidence <= 1 else round(confidence, 1),
        severity=severity,
        kb_context=kb_context,
    )

    try:
        body = client.generate_json(prompt)
    except Exception:
        body = {
            "diagnosis_summary": f"Diagnosed as '{kb_entry['disease_name']}'.",
            "disease_characteristics": kb_entry.get("symptoms", ""),
            "cause": kb_entry.get("causal_conditions", ""),
            "recommended_actions": [kb_entry.get("treatment", {}).get("cultural_control", "")],
        }

    product = pls.build_product_suggestion(kb_entry, harvest_date=harvest_date)

    return {
        "diagnosis_summary": body.get("diagnosis_summary", ""),
        "disease_characteristics": body.get("disease_characteristics", ""),
        "cause": body.get("cause", ""),
        "recommended_actions": body.get("recommended_actions", []),
        "product_recommendation": product,
        "understanding_level": level_info["understanding_level"],
        "description_generation_method": "LLM (Gemini)",
    }
