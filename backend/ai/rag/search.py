"""Semantic search over the knowledge base for free-text user questions.

Only 38 entries total, so a full local vector DB (FAISS/Chroma) would be
overkill: embeddings are cached to disk once and compared with plain
cosine similarity in-memory.
"""
import json
import os

import numpy as np

from . import store

_CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "embeddings_cache.json")

_index = None  # list of (class_id, vector) once loaded


def _embed_all():
    from ..llm import client

    vectors = []
    for entry in store.list_entries():
        text = store.render_entry_markdown(entry)
        vec = client.embed_text(text, task_type="RETRIEVAL_DOCUMENT")
        vectors.append({"class_id": entry["class_id"], "vector": vec})
    return vectors


def _load_index():
    global _index
    if _index is not None:
        return _index

    if os.path.exists(_CACHE_PATH):
        with open(_CACHE_PATH, encoding="utf-8") as f:
            cached = json.load(f)
        if len(cached) == len(store.list_entries()):
            _index = [(item["class_id"], np.array(item["vector"])) for item in cached]
            return _index

    vectors = _embed_all()
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(vectors, f)
    _index = [(item["class_id"], np.array(item["vector"])) for item in vectors]
    return _index


def _cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def search(query, top_k=3):
    from ..llm import client

    index = _load_index()
    query_vec = np.array(client.embed_text(query, task_type="RETRIEVAL_QUERY"))

    scored = [(class_id, _cosine(query_vec, vec)) for class_id, vec in index]
    scored.sort(key=lambda x: x[1], reverse=True)

    results = []
    for class_id, score in scored[:top_k]:
        entry = store.get_by_class_id(class_id)
        results.append({"entry": entry, "score": score})
    return results
