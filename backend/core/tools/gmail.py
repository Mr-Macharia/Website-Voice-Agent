"""Gmail through Composio.

Composio exposes 20 Gmail tools, and which subset the agent is given is a
security decision, not a convenience one. This module is built around an
explicit allowlist because the full set includes GMAIL_DELETE_MESSAGE,
GMAIL_DELETE_THREAD and GMAIL_BATCH_DELETE_MESSAGES — irreversible operations
on the owner's real mailbox, exposed to an agent that anyone on the internet
can type into.

GMAIL_SCOPE controls the allowlist:

  notify  (default) — drafts only. The agent can compose, never send or read.
  read    — drafts plus reading and searching mail.
  full    — everything Composio offers, destructive tools included.

Composio has no SEND tool in this account's toolset; CREATE_EMAIL_DRAFT is the
closest thing, which is a useful property: a draft is reviewable before it
leaves, so a prompt-injected "email this person" still lands in the owner's
drafts rather than in a stranger's inbox.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from core import config

logger = logging.getLogger("core.tools.gmail")

# Read-only and compose-only. Nothing here mutates or destroys existing mail.
_SCOPES: dict[str, tuple[str, ...]] = {
    "notify": (
        "GMAIL_CREATE_EMAIL_DRAFT",
    ),
    "read": (
        "GMAIL_CREATE_EMAIL_DRAFT",
        "GMAIL_FETCH_EMAILS",
        "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
        "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
        "GMAIL_GET_CONTACTS",
    ),
}

# Never handed out under any scope short of "full": irreversible.
_DESTRUCTIVE = (
    "GMAIL_DELETE_MESSAGE",
    "GMAIL_DELETE_THREAD",
    "GMAIL_BATCH_DELETE_MESSAGES",
    "GMAIL_DELETE_DRAFT",
    "GMAIL_DELETE_LABEL",
    "GMAIL_DELETE_FILTER",
)

_tools: Optional[list] = None


def allowed_slugs() -> Optional[tuple[str, ...]]:
    """Tool slugs permitted by the configured scope. None means all of them."""
    scope = (config.GMAIL_SCOPE or "notify").lower()
    if scope == "full":
        return None
    return _SCOPES.get(scope, _SCOPES["notify"])


def get_tools() -> list:
    """Gmail tools as Agno callables, or [] if Gmail isn't configured.

    Cached per process: each call otherwise hits Composio's API to fetch tool
    schemas, which would add a network round trip to agent construction.
    """
    global _tools
    if _tools is not None:
        return _tools

    if not config.gmail_available():
        logger.info(
            "Gmail disabled — missing %s", ", ".join(config.missing_for("gmail"))
        )
        _tools = []
        return _tools

    try:
        from composio import Composio

        from core.composio_agno import AgnoProvider

        client = Composio(api_key=config.COMPOSIO_API_KEY, provider=AgnoProvider())
        slugs = allowed_slugs()

        if slugs is None:
            logger.warning(
                "GMAIL_SCOPE=full — the agent can read, modify and DELETE mail. "
                "This is a public-facing agent; prefer 'notify' or 'read'."
            )
            _tools = client.tools.get(user_id=config.COMPOSIO_USER_ID, toolkits=["GMAIL"])
        else:
            _tools = client.tools.get(user_id=config.COMPOSIO_USER_ID, tools=list(slugs))

        names = [getattr(t, "__name__", "?") for t in _tools]
        if any(d.lower() in n.lower() for n in names for d in _DESTRUCTIVE):
            logger.error("Destructive Gmail tool present in agent toolset: %s", names)

        logger.info("Gmail tools loaded (scope=%s): %s", config.GMAIL_SCOPE, names)
        return _tools
    except Exception as e:
        logger.error("Could not load Gmail tools: %s", e)
        _tools = []
        return _tools
