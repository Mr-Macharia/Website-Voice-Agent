"""Expose core tools to the LiveKit voice agent.

LiveKit needs @function_tool-decorated async functions whose docstrings are the
LLM-facing schema. The core functions already have that shape, so these wrappers
are thin — they exist to keep the livekit import out of core/tools/.

Session context (session_id, source) isn't available to a bare function_tool,
so leads captured on the voice path are tagged source="voice" here.
"""

from __future__ import annotations

from livekit.agents import function_tool

from core import config
from core.tools import about as _about
from core.tools import booking as _booking
from core.tools import leads as _leads
from core.tools import gmail as _gmail
from core.tools import search as _search


@function_tool
async def search_web(query: str) -> str:
    """Search the web for up-to-date information such as news, weather, facts, prices, or events.

    Args:
        query: Search topic or query string.
    """
    return await _search.search_web(query)


@function_tool
async def search_about_owner(query: str) -> str:
    """Search Gichogu Macharia's background, projects, skills and experience.

    Use this for ANY question about Gichogu — who he is, what he builds, where
    he has worked, what he knows, how to reach him. Always use it rather than
    answering from memory.

    Args:
        query: What you want to know about him, in plain words.
    """
    return await _about.search_about_owner(query)


@function_tool
async def get_booking_link() -> str:
    """Get the link where someone can book a meeting with Gichogu.

    Use this when a visitor wants to meet, talk, get on a call, or asks about
    availability. Give them the link and say briefly what the session is for.
    Do not invent specific times — the page shows his real availability.
    """
    return await _booking.get_booking_link()


@function_tool
async def capture_lead(
    name: str = "",
    email: str = "",
    company: str = "",
    intent: str = "",
    message: str = "",
) -> str:
    """Pass a visitor's contact details to Gichogu.

    Use when someone shows interest in working with him, or wants him to get in
    touch. Ask for their details once, naturally — never pressure them.

    Args:
        name: The visitor's name.
        email: Their email address.
        company: Their company or organisation, if mentioned.
        intent: Short label for what they want, e.g. "hiring", "collaboration".
        message: Anything else worth passing on, in their own words.
    """
    return await _leads.capture_lead(
        name=name,
        email=email,
        company=company,
        intent=intent,
        message=message,
        source="voice",
    )


def get_tools() -> list:
    """Tools for the voice agent, filtered by what's actually configured.

    Offering a tool that can only fail wastes a turn and teaches the model to
    apologise; better to not advertise it.
    """
    # search_about_owner is always offered, even with knowledge unconfigured:
    # it then returns a "say you don't know" instruction, which is safer than
    # leaving the model to free-associate about a real person.
    tools = [search_web, search_about_owner]

    if config.booking_available():
        tools.append(get_booking_link)

    if config.leads_available():
        tools.append(capture_lead)

    # Composio returns plain callables; LiveKit accepts those as tools too.
    tools.extend(_gmail.get_tools())

    return tools
