"""Booking: hand the visitor Gichogu's Cal.com link.

Why a link rather than the Cal.com API:

Cal.com's API can list slots and create bookings, and Agno ships CalComTools
for exactly that. It was the original plan. But handing over the booking page
is better here:

  - Availability on the page is always correct. An agent reading slots through
    an API can offer one that was taken thirty seconds ago, and a double-booking
    is a worse experience than one extra click.
  - No numeric event-type ID to keep in sync, no API key, and no dependence on
    which Cal.com plan the account is on (availability endpoints vary by plan).
  - The visitor picks their own timezone on the page. Getting that wrong over
    voice — where the agent must transcribe a spoken time — is a real failure
    mode we avoid entirely.
  - Cal.com sends its own confirmations and reminders.

capture_lead still records that someone was interested, so a booking and a lead
are not mutually exclusive.

If real availability lookups are wanted later, agno.tools.calcom.CalComTools
does it — but expose only get_available_slots and create_booking. Its
get_upcoming_bookings would leak other people's meetings to anonymous visitors,
and cancel/reschedule would let a stranger alter them.
"""

from __future__ import annotations

import logging

from core import config
from core import ui_payload

logger = logging.getLogger("core.tools.booking")


async def get_booking_link() -> str:
    """Get the link where someone can book a meeting with Gichogu.

    Use this when a visitor wants to meet, talk, get on a call, or asks about
    availability. Give them the link and say briefly what the session is for.
    Do not invent specific times — the page shows his real availability.
    """
    url = config.CALCOM_BOOKING_URL
    if not url:
        logger.warning("CALCOM_BOOKING_URL is not set")
        return (
            "No booking link is configured. Offer to take their name and email "
            f"instead so {config.OWNER_NAME} can reach out."
        )

    spoken = (
        f"Booking link: {url}\n\n"
        "Give the visitor this link so they can pick a time that suits them. "
        "Say it is for an AI and automation consultation. Do not state specific "
        "available times — the page shows real availability and they choose "
        "their own timezone there. Out loud, say only \"cal dot com slash "
        "macharia\" and STOP — never spell out or read the rest of the "
        "address. Spelling a slug letter by letter is unusable to someone "
        "listening, and in the written chat a card with the full link is "
        "already on their screen. Afterwards you may offer to "
        "take their details as well, so he knows to expect them."
    )

    # The text chat renders a card from this; voice strips it and speaks the
    # sentence above unchanged. See core/ui_payload.py.
    return ui_payload.attach(
        spoken,
        {
            "type": "booking",
            "url": url,
            "label": "Book a chat",
            "note": "AI and automation consultation",
        },
    )
