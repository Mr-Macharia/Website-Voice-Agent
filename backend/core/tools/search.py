"""Web search. Moved verbatim in behaviour from the previous duplicated copies.

Conventions every tool in this package follows:
  - async def, returns a plain string
  - no framework imports (no agno, no livekit) — adapters handle that
  - blocking work goes through asyncio.to_thread with a timeout, so the voice
    pipeline never stalls waiting on the network
  - never raises; failures come back as speakable English
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("core.tools.search")

SEARCH_TIMEOUT = 10.0


def _search_sync(query: str, max_results: int = 4) -> str:
    from ddgs import DDGS

    results = DDGS().text(query, max_results=max_results)
    if not results:
        return f"No search results found for {query}."

    formatted = []
    for r in results:
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        if title or body:
            formatted.append(f"Title: {title}\nSummary: {body}")

    return "\n\n".join(formatted) if formatted else f"No search results found for {query}."


async def search_web(query: str) -> str:
    """Search the web for up-to-date information such as news, weather, facts, prices, or events.

    Args:
        query: Search topic or query string.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_search_sync, query), timeout=SEARCH_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning("web search timed out: %s", query)
        return "The search timed out. Tell the caller you could not look that up right now."
    except Exception as e:
        logger.warning("web search failed: %s", e)
        return f"Search service temporarily offline: {e}"
