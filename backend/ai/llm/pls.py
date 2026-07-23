"""Deterministic PLS (pre-harvest interval) approximation.

The knowledge base only has free-text PHI ranges (e.g. "14-21 days") and
ingredient *classes*, not real registered product names/exact PHI days —
those must be confirmed on PSIS before real use (see the knowledge base's
own disclaimer). This module extracts a conservative number from that text
so the app can show a "days remaining until harvest" demo figure, without
letting the LLM invent it.
"""
import re

# Broadly recognized organic-compatible active-ingredient keywords. Used only
# as a rough demo hint — real organic-certification eligibility must be
# confirmed against the certifier's approved-input list, not guessed here.
_ORGANIC_KEYWORDS = [
    "copper", "sulfur", "bacillus", "spinosad", "neem", "azadirachtin", "pyrethrin",
]


def _max_days_from_phi_note(phi_note):
    numbers = [int(n) for n in re.findall(r"\d+", phi_note or "")]
    return max(numbers) if numbers else None


def _looks_organic_compatible(ingredient_text):
    text = (ingredient_text or "").lower()
    return any(kw in text for kw in _ORGANIC_KEYWORDS)


def build_product_suggestion(kb_entry, harvest_date=None, today=None):
    """Return a demo-level product/PLS suggestion dict, or None if not applicable.

    All numbers here are approximations derived from the knowledge base
    text — always labeled as reference-only, never a real registered
    product name or an authoritative PHI day count.
    """
    import datetime

    t = kb_entry.get("treatment", {})
    ingredient = t.get("treatment_active_ingredients") or t.get("prevention_active_ingredients")
    if not ingredient:
        return None

    phi_days = _max_days_from_phi_note(t.get("phi_note", ""))
    organic_hint = _looks_organic_compatible(ingredient)

    result = {
        "product_name": f"{ingredient} (reference only · confirm the actual registered product name via PSIS)",
        "active_ingredient": ingredient,
        "safe_usage_period_days": phi_days,
        "organic_compatible_hint": organic_hint,
        "pls_check_text": None,
    }

    if isinstance(harvest_date, str):
        try:
            harvest_date = datetime.date.fromisoformat(harvest_date)
        except ValueError:
            harvest_date = None

    if phi_days is not None and harvest_date is not None:
        today = today or datetime.date.today()
        days_to_harvest = (harvest_date - today).days
        if days_to_harvest >= phi_days:
            result["pls_check_text"] = (
                f"Safe: {days_to_harvest} day(s) remain until the expected harvest date, "
                f"which satisfies the pre-harvest interval ({phi_days} days). (reference estimate)"
            )
        else:
            result["pls_check_text"] = (
                f"Caution: only {days_to_harvest} day(s) remain until the expected harvest date, "
                f"but the pre-harvest interval is {phi_days} days. Reconsider the spray timing. (reference estimate)"
            )
    else:
        result["pls_check_text"] = "No pre-harvest interval reference value available — confirm against the actual product on PSIS."

    return result
