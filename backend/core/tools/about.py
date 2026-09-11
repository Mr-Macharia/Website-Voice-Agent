"""The RAG tool: answering questions about the site owner.

This is the tool the grounding rules in persona.py point at. If it returns
nothing, the agent must say it doesn't know — never improvise.
"""

from __future__ import annotations

import asyncio
import logging

from core import config, knowledge

logger = logging.getLogger("core.tools.about")

RETRIEVE_TIMEOUT = 8.0

_NOTHING_FOUND = (
    f"Nothing on file about that. Tell the visitor you don't have that detail "
    f"and offer to put them in touch with {config.OWNER_NAME} directly. "
    f"Do NOT guess or invent an answer."
)


async def search_about_owner(query: str) -> str:
    """Search Gichogu Macharia's background, projects, skills and experience.

    Use this for ANY question about Gichogu — who he is, what he builds, where
    he has worked, what he knows, how to reach him. Always use it rather than
    answering from memory.

    Args:
        query: What you want to know about him, in plain words.
    """
    if not config.knowledge_available():
        logger.warning("search_about_owner called but knowledge is not configured")
        return _NOTHING_FOUND

    try:
        context = await asyncio.wait_for(
            knowledge.retrieve(query), timeout=RETRIEVE_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning("knowledge retrieval timed out: %s", query)
        return (
            "The lookup timed out. Tell the visitor you couldn't pull that up "
            "just now, and offer to take their details. Do NOT invent an answer."
        )
    except Exception as e:
        logger.error("knowledge retrieval failed: %s", e)
        return _NOTHING_FOUND

    if not context.strip():
        return _NOTHING_FOUND

    return (
        f"Here is what is on file about {config.OWNER_NAME}. Answer ONLY from "
        f"this; if it does not cover the question, say so.\n\n{context}"
    )
