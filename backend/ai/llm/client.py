"""Gemini API client setup: config loading, text generation, embeddings."""
import json
import os
import re

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

_GENERATION_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
_EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004")

_configured = False


def _ensure_configured():
    global _configured
    if _configured:
        return
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )
    genai.configure(api_key=api_key)
    _configured = True


def generate_text(prompt, json_mode=False):
    """Call Gemini with a single prompt string, return raw text."""
    _ensure_configured()
    model = genai.GenerativeModel(_GENERATION_MODEL)
    kwargs = {}
    if json_mode:
        kwargs["generation_config"] = {"response_mime_type": "application/json"}
    response = model.generate_content(prompt, **kwargs)
    return response.text


def generate_json(prompt):
    """Call Gemini expecting a JSON object back; tolerate stray code fences."""
    raw = generate_text(prompt, json_mode=True)
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def embed_text(text, task_type="RETRIEVAL_DOCUMENT"):
    _ensure_configured()
    result = genai.embed_content(model=_EMBEDDING_MODEL, content=text, task_type=task_type)
    return result["embedding"]
