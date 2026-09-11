"""Lead capture: persist to Postgres, then notify the owner.

Two rules that are not negotiable:

1. The Postgres write is the source of truth. The email is best-effort — if
   SMTP fails the lead is still safe, and the visitor never hears about it.
2. This is a fixed outbound notification to the owner only. The agent is NOT
   given a general-purpose email tool; a public-facing LLM that can send
   arbitrary mail is a spam relay one prompt injection away.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from core import config

logger = logging.getLogger("core.tools.leads")

SMTP_TIMEOUT = 10.0

# Deliberately permissive: rejecting a real address is worse than accepting a
# slightly odd one. This only catches obvious nonsense from a mis-heard voice
# transcript.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(email: str) -> bool:
    return bool(email and _EMAIL_RE.match(email.strip()))


def _insert_lead(
    name: str,
    email: str,
    company: str,
    intent: str,
    message: str,
    session_id: Optional[str],
    source: str,
) -> int:
    from core import db

    engine = db.get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            db.leads_table.insert().values(
                name=name or None,
                email=email or None,
                company=company or None,
                intent=intent or None,
                message=message or None,
                session_id=session_id,
                source=source,
            )
        )
        return int(result.inserted_primary_key[0])


def _send_notification(lead_id: int, name: str, email: str, company: str,
                       intent: str, message: str, source: str) -> None:
    """Plain stdlib SMTP. No Google client stack, no OAuth flow."""
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = f"New lead from your site: {name or email or 'unknown'}"
    msg["From"] = config.LEAD_SMTP_USER
    msg["To"] = config.LEAD_NOTIFY_EMAIL
    msg.set_content(
        f"Lead #{lead_id} via {source}\n\n"
        f"Name:    {name or '-'}\n"
        f"Email:   {email or '-'}\n"
        f"Company: {company or '-'}\n"
        f"Intent:  {intent or '-'}\n\n"
        f"Message:\n{message or '-'}\n"
    )

    with smtplib.SMTP(config.LEAD_SMTP_HOST, config.LEAD_SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
        smtp.starttls()
        smtp.login(config.LEAD_SMTP_USER, config.LEAD_SMTP_APP_PASSWORD)
        smtp.send_message(msg)


async def _notify(lead_id: int, **fields: str) -> None:
    """Best effort. Any failure is logged and swallowed."""
    if not config.lead_notification_available():
        logger.info(
            "Lead #%s stored but not emailed — missing %s",
            lead_id,
            ", ".join(config.missing_for("lead_notification")),
        )
        return

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_send_notification, lead_id, **fields),
            timeout=SMTP_TIMEOUT + 5,
        )
        logger.info("Lead #%s notification sent", lead_id)
    except Exception as e:
        # Never re-raise: the lead is already durable in Postgres.
        logger.error("Lead #%s stored but notification failed: %s", lead_id, e)


async def capture_lead(
    name: str = "",
    email: str = "",
    company: str = "",
    intent: str = "",
    message: str = "",
    session_id: Optional[str] = None,
    source: str = "text",
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
    if not config.leads_available():
        logger.warning("capture_lead called but DATABASE_URL is not set")
        return (
            "Couldn't save that right now. Give them Gichogu's email so they "
            "can reach him directly."
        )

    if email and not _valid_email(email):
        return (
            "That email doesn't look right. Read it back to them and ask them "
            "to confirm it."
        )

    if not (email or name):
        return "Ask for at least a name or an email before saving anything."

    try:
        lead_id = await asyncio.to_thread(
            _insert_lead, name, email, company, intent, message, session_id, source
        )
    except Exception as e:
        logger.error("Failed to store lead: %s", e)
        return (
            "Couldn't save that right now. Apologise briefly and suggest they "
            "email Gichogu directly."
        )

    await _notify(
        lead_id,
        name=name,
        email=email,
        company=company,
        intent=intent,
        message=message,
        source=source,
    )

    return (
        f"Saved. Tell them their details are with {config.OWNER_NAME} and he'll "
        f"be in touch."
    )
