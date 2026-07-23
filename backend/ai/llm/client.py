"""OpenAI API client setup: config loading, text generation, embeddings."""
import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_GENERATION_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )
    _client = OpenAI()
    return _client


def get_embedding_model():
    """Return the active embedding model name (used for cache invalidation)."""
    return _EMBEDDING_MODEL


def generate_text(prompt, json_mode=False):
    """Call OpenAI with a single prompt string, return raw text."""
    client = _get_client()
    messages = [{"role": "user", "content": prompt}]
    kwargs = {}
    if json_mode:
        # OpenAI's json_object mode requires the word "JSON" in the messages.
        messages.insert(0, {"role": "system", "content": "Respond only with a valid JSON object."})
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=_GENERATION_MODEL, messages=messages, **kwargs
    )
    return response.choices[0].message.content


def generate_json(prompt):
    """Call OpenAI expecting a JSON object back; tolerate stray code fences."""
    raw = generate_text(prompt, json_mode=True)
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def embed_text(text, task_type="RETRIEVAL_DOCUMENT"):
    """Embed a text string.

    task_type is kept for caller compatibility (a Gemini-era concept);
    OpenAI embeddings do not use it.
    """
    client = _get_client()
    result = client.embeddings.create(model=_EMBEDDING_MODEL, input=text)
    return result.data[0].embedding
