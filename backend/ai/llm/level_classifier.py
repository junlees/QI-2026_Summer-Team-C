"""Classify how much the user already understands about crop diseases.

Feeds explain.py so it can pick a matching tone/vocabulary. Runs once per
diagnosis request (no per-user persistence yet).
"""

_DEFAULT_RESULT = {
    "understanding_level": "Intermediate",
    "reason": "No user input was provided, so the default (Intermediate) level was applied.",
    "recommended_tone": "Explain basic agricultural terms plainly, while keeping key information clear and concise.",
}

_PROMPT_TEMPLATE = """# Persona
You are an agricultural education expert and UX analyst. Based on the sentence or question the user typed, and/or their profile information, you must accurately determine this user's "understanding level" of agriculture and crop diseases/pests.

# Input Data
- User's input: {user_input}
- Additional user info (e.g. experience, crops grown, short bio): {user_profile}

# Classification Criteria
1. [Beginner]: Unfamiliar with agricultural terminology, cannot distinguish disease from pest damage, uses very intuitive/simple expressions like "the leaves are wilting" or "something's eating the leaves".
2. [Intermediate]: Recognizes basic agricultural terms (e.g. foliar feeding, aphids, etiolation), describes symptoms fairly specifically, but lacks precise knowledge of treatment methods or active ingredients.
3. [Advanced]: Directly references professional agricultural terms or pathogen/pest names, and can cite specific pesticide active ingredients or treatment history they've used before.

# Output Format (Strict JSON Only)
Respond with ONLY the JSON structure below. Do not include any other explanation or markdown text.

{{
  "understanding_level": "Beginner" | "Intermediate" | "Advanced",
  "reason": "In 2 sentences or fewer, explain the specific reason you classified the user as Beginner/Intermediate/Advanced.",
  "recommended_tone": "Describe the tone/manner appropriate for responding to this user (e.g. 'simple analogies an elementary schooler could follow', 'include technical terms but keep explanations precise')."
}}

Write all values in English.
"""


def classify_understanding_level(user_input, user_profile):
    """user_input: free-text string (may be empty). user_profile: dict."""
    from . import client  # local import keeps client's API-key check lazy

    if not user_input or not user_input.strip():
        return dict(_DEFAULT_RESULT)

    prompt = _PROMPT_TEMPLATE.format(
        user_input=user_input.strip(),
        user_profile=user_profile or {},
    )
    try:
        result = client.generate_json(prompt)
    except Exception:
        return dict(_DEFAULT_RESULT)

    if result.get("understanding_level") not in ("Beginner", "Intermediate", "Advanced"):
        return dict(_DEFAULT_RESULT)
    return result
