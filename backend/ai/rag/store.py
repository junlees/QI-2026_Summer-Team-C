"""Disease knowledge base: JSON load + exact-match lookup by class_id.

This is the deterministic retrieval path used by the diagnosis pipeline
(classifier already outputs class_id, so no embedding search is needed
here). See search.py for the free-text semantic search path.
"""
import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "AgriSage_Disease_Knowledge_Base_EN.json")

_cache = None


def load_kb():
    global _cache
    if _cache is None:
        with open(_DATA_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def list_entries():
    return load_kb()["classes"]


def get_by_class_id(class_id):
    for entry in list_entries():
        if entry["class_id"] == class_id:
            return entry
    return None


def render_entry_markdown(entry):
    """Render one knowledge-base entry as a natural-language block.

    Used both as LLM prompt context and as the text that gets embedded
    for semantic search, so the two paths stay consistent.
    """
    if entry.get("is_healthy"):
        return (
            f"## {entry['crop']} - {entry['disease_name']}\n"
            f"This is a healthy-plant class. No disease detected, no treatment needed."
        )

    t = entry.get("treatment", {})
    return (
        f"## {entry['crop']} - {entry['disease_name']}\n"
        f"Pathogen: {entry.get('pathogen', '')}\n"
        f"Severity: {entry.get('severity_level', '')}\n"
        f"Symptoms: {entry.get('symptoms', '')}\n"
        f"Causal conditions: {entry.get('causal_conditions', '')}\n"
        f"Prevention active ingredients: {t.get('prevention_active_ingredients', '')}\n"
        f"Treatment active ingredients: {t.get('treatment_active_ingredients', '')}\n"
        f"Application method: {t.get('application_method', '')}\n"
        f"Application timing: {t.get('application_timing', '')}\n"
        f"Spray interval: {t.get('spray_interval', '')}\n"
        f"Resistance management: {t.get('resistance_management', '')}\n"
        f"Cultural control: {t.get('cultural_control', '')}\n"
        f"Pre-harvest interval (PHI) note: {t.get('phi_note', '')}\n"
        f"PPE note: {t.get('ppe_note', '')}\n"
        f"Korea registration note: {entry.get('korea_registration_note', '')}"
    )
