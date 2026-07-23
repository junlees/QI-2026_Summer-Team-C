"""Free-text Q&A grounded in the knowledge base via semantic search (RAG)."""

_PROMPT_TEMPLATE = """# Role
You are a crop disease/pest consulting expert. Answer the user's question based ONLY on the "Reference Material" below.
If the reference material doesn't cover something, say "That information isn't in the provided material" instead of guessing.

# User Understanding Level
- Level: {level}
- Recommended tone: {tone}

# Reference Material
{context}

# User Question
{question}

# Answer (plain text, in English, using vocabulary matching the user's understanding level)
"""


def answer_question(question, level_info=None, top_k=3):
    from . import client
    from ..rag import search

    level_info = level_info or {"understanding_level": "Intermediate", "recommended_tone": "Clear and concise"}

    results = search.search(question, top_k=top_k)
    from ..rag import store
    context = "\n\n".join(store.render_entry_markdown(r["entry"]) for r in results)

    prompt = _PROMPT_TEMPLATE.format(
        level=level_info["understanding_level"],
        tone=level_info["recommended_tone"],
        context=context,
        question=question,
    )
    answer = client.generate_text(prompt)

    return {
        "answer": answer,
        "sources": [r["entry"]["class_id"] for r in results],
    }
