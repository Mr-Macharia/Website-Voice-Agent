"""The knowledge base about the site owner.

One Knowledge object, built lazily and cached per process. The Agno text agent
consumes it directly via Agent(knowledge=...); the LiveKit voice agent can't
(livekit's Agent has no knowledge parameter) so it goes through the
search_about_owner tool, which calls retrieve() below. Same index either way.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from core import config

logger = logging.getLogger("core.knowledge")

_knowledge: Optional[Any] = None


def get_knowledge() -> Optional[Any]:
    """The shared Knowledge object, or None if knowledge isn't configured.

    Returns None rather than raising so the agent still runs (web search,
    conversation) when the database or embedding key is absent.
    """
    global _knowledge
    if _knowledge is not None:
        return _knowledge

    if not config.knowledge_available():
        logger.warning(
            "Knowledge disabled — missing %s. The agent will not be able to "
            "answer questions about %s.",
            ", ".join(config.missing_for("knowledge")),
            config.OWNER_NAME,
        )
        return None

    try:
        from agno.knowledge.knowledge import Knowledge

        from core import db

        _knowledge = Knowledge(
            name=f"{config.OWNER_NAME} knowledge base",
            description=f"Background, projects and experience of {config.OWNER_NAME}.",
            vector_db=db.get_vector_db(),
            contents_db=db.get_agno_db(),
            max_results=config.KNOWLEDGE_TOP_K,
        )
        return _knowledge
    except Exception as e:
        logger.error("Failed to build knowledge base: %s", e)
        return None


def _format_results(results: list[Any]) -> str:
    """Render retrieved documents for the LLM.

    Source labels are included so the model can say where something came from,
    but kept terse — this text is prompt tokens, and on voice it delays audio.
    """
    if not results:
        return ""

    chunks = []
    for doc in results:
        content = (getattr(doc, "content", None) or "").strip()
        if not content:
            continue
        meta = getattr(doc, "meta_data", None) or {}
        source = meta.get("source") or meta.get("name") or ""
        chunks.append(f"[{source}]\n{content}" if source else content)

    return "\n\n---\n\n".join(chunks)


async def retrieve(query: str, limit: Optional[int] = None) -> str:
    """Search the knowledge base. Returns formatted context, or "" if nothing."""
    knowledge = get_knowledge()
    if knowledge is None:
        return ""

    try:
        results = await knowledge.asearch(
            query=query, max_results=limit or config.KNOWLEDGE_TOP_K
        )
        return _format_results(results or [])
    except Exception as e:
        logger.error("Knowledge search failed for %r: %s", query, e)
        return ""
