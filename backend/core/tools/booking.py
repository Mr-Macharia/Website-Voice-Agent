"""Cal.com booking, deliberately narrowed.

CalComTools ships five functions. We expose two.

get_upcoming_bookings would let an anonymous visitor list other people's
meetings with Gichogu (names, emails, times). cancel_booking and
reschedule_booking would let a stranger alter them. On a public website those
are data-exposure and vandalism vectors, so they are disabled at construction
time — not merely left out of the prompt, which a determined model could
ignore.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from core import config

logger = logging.getLogger("core.tools.booking")

CALCOM_TIMEOUT = 15.0

_toolkit: Optional[Any] = None

_UNAVAILABLE = (
    "Booking isn't set up right now. Offer to take the visitor's name and email "
    "instead so Gichogu can follow up."
)


def _get_toolkit() -> Optional[Any]:
    global _toolkit
    if _toolkit is not None:
        return _toolkit

    if not config.booking_available():
        logger.warning(
            "Cal.com disabled — missing %s", ", ".join(config.missing_for("booking"))
        )
        return None

    try:
        from agno.tools.calcom import CalComTools

        _toolkit = CalComTools(
            api_key=config.CALCOM_API_KEY,
            event_type_id=config.CALCOM_EVENT_TYPE_ID,
            user_timezone=config.CALCOM_USER_TIMEZONE,
            enable_get_available_slots=True,
            enable_create_booking=True,
            # Off by design — see module docstring.
            enable_get_upcoming_bookings=False,
            enable_reschedule_booking=False,
            enable_cancel_booking=False,
        )
        return _toolkit
    except Exception as e:
        logger.error("Failed to build Cal.com toolkit: %s", e)
        return None


async def _call(fn_name: str, *args: Any, **kwargs: Any) -> str:
    toolkit = _get_toolkit()
    if toolkit is None:
        return _UNAVAILABLE

    fn = getattr(toolkit, fn_name, None)
    if fn is None:
        logger.error("CalComTools has no %s", fn_name)
        return _UNAVAILABLE

    try:
        # CalComTools uses `requests` internally — blocking. Keep it off the
        # event loop so audio never stalls.
        result = await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs), timeout=CALCOM_TIMEOUT
        )
        return str(result)
    except asyncio.TimeoutError:
        logger.warning("Cal.com %s timed out", fn_name)
        return (
            "The calendar didn't respond in time. Apologise briefly and offer to "
            "take their details instead."
        )
    except Exception as e:
        logger.error("Cal.com %s failed: %s", fn_name, e)
        return (
            "The calendar isn't reachable right now. Offer to take their name "
            "and email so Gichogu can follow up."
        )


async def get_available_slots(start_date: str, end_date: str) -> str:
    """Get Gichogu's free meeting slots between two dates.

    Call this before offering any times — never guess availability.

    Args:
        start_date: First day to check, as YYYY-MM-DD.
        end_date: Last day to check, as YYYY-MM-DD.
    """
    return await _call("get_available_slots", start_date=start_date, end_date=end_date)


async def book_meeting(start_time: str, name: str, email: str) -> str:
    """Book a meeting with Gichogu at a confirmed free slot.

    Only call this after the visitor has picked a slot you offered AND given
    their name and email. Confirm the details back to them first.

    Args:
        start_time: Slot start in ISO 8601, e.g. 2026-03-15T15:00:00Z.
        name: The visitor's name.
        email: The visitor's email address.
    """
    # CalComTools.create_booking takes exactly (start_time, name, email) —
    # verified against the installed signature. What the meeting is about is
    # captured separately via capture_lead.
    return await _call(
        "create_booking",
        start_time=start_time,
        name=name,
        email=email,
    )
