"""Output guardrails.

Prompt instructions are not a reliable control surface for this model. During
testing the agent repeatedly wrote a plausible but entirely invented booking
link (https://calendly.com/gichogu) rather than calling get_booking_link, and
three successive prompt revisions did not stop it. A visitor following that
link lands nowhere.

So the rule is enforced in code instead: any URL in agent output that is not on
the allowlist is removed before the text reaches the visitor. The model cannot
ignore this the way it can ignore an instruction.

This mirrors the existing tts_node markdown stripping — behaviour we need
guaranteed gets enforced in the pipeline, not requested in the prompt.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from core import config

logger = logging.getLogger("core.guardrails")

# Bare-domain matches too, since models often write "calendly.com/gichogu"
# without a scheme.
_URL_RE = re.compile(
    r"""(?ix)
    \b
    (?: https?://  |  www\. )
    [^\s<>"'\)\]]+
    |
    \b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|dev|ai|co|tech|me|app)
    (?:/[^\s<>"'\)\]]*)?
    """
)


def _allowed_hosts() -> set[str]:
    """Hosts the agent is permitted to emit, derived from real config."""
    hosts: set[str] = set()
    for url in (config.CALCOM_BOOKING_URL, config.SITE_URL):
        if not url:
            continue
        parsed = urlparse(url if "://" in url else f"https://{url}")
        if parsed.netloc:
            hosts.add(parsed.netloc.lower().removeprefix("www."))
    # Owner-controlled profiles that appear in the knowledge base.
    hosts.update({"github.com", "linkedin.com", "cal.com"})
    return hosts


def _host_of(candidate: str) -> str:
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    return parsed.netloc.lower().removeprefix("www.")


def strip_unapproved_urls(text: str) -> str:
    """Remove URLs pointing anywhere the agent has no business sending people.

    Kept deliberately blunt: dropping a legitimate link is a minor annoyance,
    while emitting a fabricated one misleads a real person.
    """
    if not text:
        return text

    allowed = _allowed_hosts()

    def _replace(match: re.Match[str]) -> str:
        url = match.group(0)
        host = _host_of(url)
        if host in allowed or any(host.endswith(f".{a}") for a in allowed):
            return url
        logger.warning("Stripped unapproved URL from agent output: %s", url)
        return "[link removed]"

    return _URL_RE.sub(_replace, text)
