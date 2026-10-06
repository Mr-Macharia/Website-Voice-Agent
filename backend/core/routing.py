"""Jev routing: cheap, typed decisions about a visitor message.

Jev (TypeSafe's System One model) never writes text or calls tools. It answers
narrow questions about a piece of state and returns calibrated probabilities,
which code turns into decisions. Here that means: does this message need the
knowledge base, and which kind of request is it — so the slow, expensive LLM is
asked only to write the reply.

Everything here fails open. If Jev is off, unconfigured, slow or erroring,
route() returns None and the caller behaves exactly as it did before.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from core import config

logger = logging.getLogger("core.routing")

# Nothing configures the root logger for the AgentOS server, so INFO records
# would be dropped and the shadow lines would never appear in the terminal.
# This logger therefore carries its own handler.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[jev] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

INTENTS = ("about_owner", "book_meeting", "leave_details", "current_info", "small_talk")


@dataclass(frozen=True)
class Route:
    needs_owner_knowledge: float  # 0-1 probability
    intent: str
    intent_confidence: float  # 0-1
    shares_contact_details: float  # 0-1 probability
    latency_ms: float


_client = None


def _get_client():
    """One async client per process, built lazily so the SDK is only imported
    when routing is actually enabled."""
    global _client
    if _client is None:
        from typesafe_sdk import AsyncTypeSafeClient

        _client = AsyncTypeSafeClient(
            api_key=config.TYPESAFE_API_KEY,
            model=config.JEV_MODEL,
            timeout=config.JEV_TIMEOUT,
        )
    return _client


def _questions() -> dict:
    from typesafe_sdk import Choice, Noul, NoulCriteria

    owner = config.OWNER_NAME
    return {
        "needs_owner_knowledge": Noul(
            instructions={
                "question": (
                    f"Does `message` ask for a fact about {owner} that has to "
                    f"be looked up: his background, projects, skills, "
                    f"experience, availability or how to reach him?"
                ),
                "focus": "Judge whether lookup is needed, not whether the topic is interesting.",
            },
            criteria=NoulCriteria(
                true={
                    "what": f"Asks about {owner}, his work or his availability",
                    "examples": ["What has he built?", "Where has he worked?"],
                },
                false={
                    "what": "Greetings, thanks, or questions not about him",
                    "not_for": f"Any question about {owner}",
                    "examples": ["Hi!", "Thanks, that helps"],
                },
            ),
        ),
        "shares_contact_details": Noul(
            instructions={
                "question": "Does `message` contain the visitor's own name, email address or phone number?",
                "focus": "The visitor giving their own details, not asking for someone else's.",
            },
        ),
        "intent": Choice(
            instructions={
                "question": "What is the visitor mainly trying to do in `message`?",
                "focus": "Pick the single primary request.",
            },
            criteria={
                "about_owner": {
                    "what": f"Wants to know about {owner}",
                    "not_for": "Booking a call or leaving contact details",
                    "examples": ["What does he do?", "Has he used Python?"],
                },
                "book_meeting": {
                    "what": "Wants to schedule a call or meeting",
                    "not_for": "Asking about his skills",
                    "examples": ["Can I book a call?", "When is he free?"],
                },
                "leave_details": {
                    "what": "Wants to be contacted or is giving contact details",
                    "not_for": "Booking a specific time",
                    "examples": ["Have him email me", "My email is a@b.com"],
                },
                "current_info": {
                    "what": "Needs up-to-date public information from the web",
                    "not_for": f"Questions about {owner}",
                    "examples": ["What's the latest Python release?"],
                },
                "small_talk": {
                    "what": "Greeting, thanks or chit-chat",
                    "not_for": "Any real request",
                    "examples": ["Hello", "Thanks!"],
                },
            },
        ),
    }


async def route(message: str) -> Optional[Route]:
    """Classify one visitor message. None means 'no decision — behave as before'."""
    if not config.jev_available() or not message.strip():
        return None

    start = time.perf_counter()
    try:
        response = await _get_client().system_one(
            state={"message": message[:2000]},
            questions=_questions(),
        )
        a = response.answers
        return Route(
            needs_owner_knowledge=a["needs_owner_knowledge"].noul,
            intent=a["intent"].choice,
            intent_confidence=a["intent"].confidence,
            shares_contact_details=a["shares_contact_details"].noul,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:  # network, auth, rate limit, bad shape — never fatal
        logger.warning("Jev routing failed (%s); falling back to default behaviour", e)
        return None


# --- Shadow mode ------------------------------------------------------------
# In "shadow" mode Jev runs beside the agent and only logs. A pre-hook starts
# the classification as a background task (zero added latency); a post-hook,
# once the reply is done, logs Jev's decision next to the tools the agent
# actually called. That comparison is the evidence for trusting Jev in "on" mode.
import asyncio  # noqa: E402

_pending: dict[str, "asyncio.Task[Optional[Route]]"] = {}


def shadow_pre_hook(run_input, run_context) -> None:
    if config.JEV_ROUTING_MODE != "shadow" or not config.jev_available():
        return
    try:
        message = run_input.input_content_string()
        _pending[run_context.run_id] = asyncio.create_task(route(message))
    except Exception as e:  # a logging aid must never break a reply
        logger.warning("Jev shadow pre-hook failed: %s", e)


async def shadow_post_hook(run_output, run_context) -> None:
    task = _pending.pop(getattr(run_context, "run_id", ""), None)
    if task is None:
        return
    try:
        decision = await asyncio.wait_for(task, timeout=config.JEV_TIMEOUT)
        used = [t.tool_name for t in (run_output.tools or []) if t.tool_name]
        if decision is None:
            logger.info("jev_shadow decision=none agent_tools=%s", used)
            return
        logger.info(
            "jev_shadow intent=%s(%.2f) needs_knowledge=%.2f contact=%.2f "
            "jev_ms=%.0f agent_tools=%s",
            decision.intent,
            decision.intent_confidence,
            decision.needs_owner_knowledge,
            decision.shares_contact_details,
            decision.latency_ms,
            used,
        )
    except Exception as e:
        logger.warning("Jev shadow post-hook failed: %s", e)
