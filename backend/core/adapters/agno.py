"""Expose core tools to the Agno text agent.

Agno Toolkits register sync methods, while the core tools are async. Agno runs
tool calls in a worker thread, so there is no running loop to attach to — each
call gets its own short-lived loop via asyncio.run().

Docstrings here are the LLM-facing schema and deliberately mirror the LiveKit
adapter word for word, so voice and text agents see identical tools.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from agno.tools import Toolkit

from core import config
from core.tools import about as _about
from core.tools import booking as _booking
from core.tools import leads as _leads
from core.tools import search as _search

logger = logging.getLogger("core.adapters.agno")


def _run(coro_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Run an async core tool from Agno's sync tool-calling path."""
    try:
        return asyncio.run(coro_fn(*args, **kwargs))
    except RuntimeError as e:
        # Defensive: if Agno ever calls tools from inside a running loop,
        # asyncio.run() raises. Fall back to a dedicated loop in a new thread.
        if "running event loop" not in str(e):
            raise
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro_fn(*args, **kwargs))).result()


class SiteTools(Toolkit):
    """Every tool the website agent can use."""

    def __init__(self) -> None:
        super().__init__(name="site_tools")

        self.register(self.search_about_owner)
        self.register(self.search_web)

        if config.booking_available():
            self.register(self.get_booking_link)
        if config.leads_available():
            self.register(self.capture_lead)

    def search_about_owner(self, query: str) -> str:
        """Search Gichogu Macharia's background, projects, skills and experience.

        Use this for ANY question about Gichogu — who he is, what he builds, where
        he has worked, what he knows, how to reach him. Always use it rather than
        answering from memory.

        Args:
            query (str): What you want to know about him, in plain words.
        Returns:
            str: Relevant excerpts from his knowledge base.
        """
        return _run(_about.search_about_owner, query)

    def search_web(self, query: str) -> str:
        """Search the web for up-to-date information such as news, weather, facts, prices, or events.

        Args:
            query (str): Search topic or query string.
        Returns:
            str: Titles and summaries of the top web results.
        """
        return _run(_search.search_web, query)

    def get_booking_link(self) -> str:
        """Get the link where someone can book a meeting with Gichogu.

        Use this when a visitor wants to meet, talk, get on a call, or asks
        about availability. Give them the link and say briefly what the session
        is for. Do not invent specific times — the page shows his real
        availability.

        Returns:
            str: The booking URL and how to present it.
        """
        return _run(_booking.get_booking_link)

    def capture_lead(
        self,
        name: str = "",
        email: str = "",
        company: str = "",
        intent: str = "",
        message: str = "",
    ) -> str:
        """Pass a visitor's contact details to Gichogu.

        Use when someone shows interest in working with him, or wants him to get
        in touch. Ask for their details once, naturally — never pressure them.

        Args:
            name (str): The visitor's name.
            email (str): Their email address.
            company (str): Their company or organisation, if mentioned.
            intent (str): Short label for what they want, e.g. "hiring".
            message (str): Anything else worth passing on, in their own words.
        Returns:
            str: Confirmation that the details were saved.
        """
        return _run(
            _leads.capture_lead,
            name=name,
            email=email,
            company=company,
            intent=intent,
            message=message,
            source="text",
        )
