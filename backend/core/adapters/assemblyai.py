"""Expose core tools to the AssemblyAI Voice Agent API.

The Voice Agent API takes tools as flat JSON Schema — no decorators, no SDK
types, just dicts sent inside session.update. That is a different shape from
the LiveKit adapter next door, but the underlying core/tools functions are
identical; only the description of them changes.

Tools run as *client-side function tools*: the browser receives tool.call and
posts it back here, because the logic needs Postgres, the pgvector knowledge
base, and the Composio session. Only the dispatch travels through the browser.

Session context (session_id, source) isn't carried by a tool call, so leads
captured on the voice path are tagged source="voice" here, as in the LiveKit
adapter.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable

from core import config
from core import ui_payload
from core.tools import about as _about
from core.tools import booking as _booking
from core.tools import gmail as _gmail
from core.tools import leads as _leads
from core.tools import search as _search

logger = logging.getLogger("core.adapters.assemblyai")


# --- Tool schemas ---------------------------------------------------------
# Descriptions are the model's main signal for when to call, so they carry the
# same guidance as the LiveKit docstrings.
#
# The `description`, `examples`, and `pattern` hints on a parameter do double
# duty: they improve tool-calling accuracy AND turn detection. Knowing what a
# complete email address looks like is what stops the agent replying halfway
# through "alex at example dot..." — so they are worth writing carefully.

_SEARCH_WEB = {
    "type": "function",
    "name": "search_web",
    "description": (
        "Search the web for up-to-date information such as news, weather, "
        "facts, prices, or events. Use it rather than answering from memory "
        "whenever the answer could have changed recently."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search topic or query string.",
            },
        },
        "required": ["query"],
    },
}

_SEARCH_ABOUT_OWNER = {
    "type": "function",
    "name": "search_about_owner",
    "description": (
        f"Search {config.OWNER_NAME}'s background, projects, skills and "
        "experience. Use this for ANY question about him — who he is, what he "
        "builds, where he has worked, what he knows, how to reach him. Always "
        "use it rather than answering from memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What you want to know about him, in plain words.",
            },
        },
        "required": ["query"],
    },
}

_GET_BOOKING_LINK = {
    "type": "function",
    "name": "get_booking_link",
    "description": (
        f"Get the link where someone can book a meeting with {config.OWNER_NAME}. "
        "Use this when a visitor wants to meet, talk, get on a call, or asks "
        "about availability. Give them the link and say briefly what the "
        "session is for. Do not invent specific times — the page shows his "
        "real availability."
    ),
    "parameters": {"type": "object", "properties": {}},
}

_CAPTURE_LEAD = {
    "type": "function",
    "name": "capture_lead",
    "description": (
        f"Pass a visitor's contact details to {config.OWNER_NAME}. Use when "
        "someone shows interest in working with him, or wants him to get in "
        "touch. Ask for their details once, naturally — never pressure them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The visitor's name.",
                "examples": ["Alex Mwangi", "Sarah"],
            },
            "email": {
                "type": "string",
                # Spoken addresses arrive in many shapes ("alex at acme dot
                # com"). The hint tells the agent what a *complete* one looks
                # like, so it waits for the whole thing instead of replying
                # halfway through. No `pattern` — a strict regex here traps
                # the caller in a re-ask loop on anything unusual.
                "description": (
                    "Their email address, as a normal address. The visitor may "
                    "say it aloud as 'alex at acme dot com' — write it as "
                    "alex@acme.com."
                ),
                "format": "email",
                "examples": ["alex@acme.com", "s.mwangi@example.co.ke"],
            },
            "company": {
                "type": "string",
                "description": "Their company or organisation, if mentioned.",
            },
            "intent": {
                "type": "string",
                "description": "Short label for what they want.",
                "examples": ["hiring", "collaboration", "consulting"],
            },
            "message": {
                "type": "string",
                "description": "Anything else worth passing on, in their own words.",
            },
        },
        # Deliberately loose: a visitor who offers only a name and interest is
        # still a lead worth having. Requiring more would make the agent
        # interrogate people.
        "required": [],
    },
}


# --- Dispatch -------------------------------------------------------------
# Maps a tool name to the core function behind it. Kept separate from the
# schemas so an unconfigured tool is never advertised but is still dispatchable
# if the model somehow calls it.
_HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    "search_web": _search.search_web,
    "search_about_owner": _about.search_about_owner,
    "get_booking_link": _booking.get_booking_link,
}


async def _capture_lead(**kwargs: Any) -> str:
    return await _leads.capture_lead(
        name=kwargs.get("name", ""),
        email=kwargs.get("email", ""),
        company=kwargs.get("company", ""),
        intent=kwargs.get("intent", ""),
        message=kwargs.get("message", ""),
        source="voice",
    )


_HANDLERS["capture_lead"] = _capture_lead


def _gmail_schema(fn: Callable) -> dict | None:
    """Best-effort flat schema for a Composio callable.

    Composio returns plain functions with a docstring and annotations rather
    than a schema. Anything we can't describe is skipped rather than offered
    half-formed — an undescribed tool is one the model calls wrongly.
    """
    name = getattr(fn, "__name__", None)
    doc = inspect.getdoc(fn)
    if not name or not doc:
        return None

    properties: dict[str, dict] = {}
    required: list[str] = []
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None

    for param_name, param in sig.parameters.items():
        if param_name.startswith("_") or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        properties[param_name] = {
            "type": "string",
            "description": param_name.replace("_", " "),
        }
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "function",
        "name": name,
        "description": doc.split("\n\n")[0],
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def get_tool_schemas() -> list[dict]:
    """Tool definitions for session.update, filtered by what's configured.

    Offering a tool that can only fail wastes a turn and teaches the model to
    apologise; better to not advertise it.
    """
    # search_about_owner is always offered, even with knowledge unconfigured:
    # it then returns a "say you don't know" instruction, which is safer than
    # leaving the model to free-associate about a real person.
    schemas = [_SEARCH_WEB, _SEARCH_ABOUT_OWNER]

    if config.booking_available():
        schemas.append(_GET_BOOKING_LINK)

    if config.leads_available():
        schemas.append(_CAPTURE_LEAD)

    # An optional Gmail tool must never take down the session. The LiveKit
    # adapter learned this the hard way: one bad tool raised and killed the
    # whole voice session rather than just that tool.
    for fn in _gmail.get_tools():
        try:
            schema = _gmail_schema(fn)
            if schema is None:
                continue
            schemas.append(schema)
            _HANDLERS[schema["name"]] = fn
        except Exception as e:  # never let an optional tool break voice
            logger.warning(
                "Skipping Gmail tool %s for voice: %s",
                getattr(fn, "__name__", "?"), e,
            )

    return schemas


async def dispatch(name: str, arguments: dict[str, Any]) -> str:
    """Run a tool call and return its result as a string.

    Errors come back as text the agent can read out and recover from, never as
    exceptions: a raised error mid-conversation leaves the visitor listening to
    silence. The message names what failed and what to do next, because that is
    what the model will act on.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        logger.warning("Unknown tool call: %s", name)
        return (
            f"The tool '{name}' isn't available. Tell the visitor you can't do "
            "that right now and carry on with the conversation."
        )

    try:
        result = handler(**(arguments or {}))
        if inspect.isawaitable(result):
            result = await result
        # Tools may append a UI payload for the text chat to render a card or
        # form from. Voice has no components and reads this string aloud, so
        # the marker is stripped here rather than spoken.
        return ui_payload.strip_payload(str(result))
    except TypeError as e:
        # Wrong or missing arguments — recoverable by asking again.
        logger.warning("Bad arguments for %s: %s", name, e)
        return (
            f"Could not run '{name}' with those details. Ask the visitor to "
            "repeat what you need, then try again."
        )
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return (
            f"Could not complete '{name}': {e}. Tell the visitor it didn't work "
            "and offer to pass the message on another way."
        )
