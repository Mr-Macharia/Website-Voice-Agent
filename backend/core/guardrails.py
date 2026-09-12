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


# deepseek leaks fragments of its internal tool-call syntax into message
# content — "<｜DSML｜function_calls", "<｜tool▁calls▁begin｜>" and similar,
# using full-width pipes and other unusual separators. Visitors must never see
# these, and TTS would read them aloud as gibberish.
_CONTROL_TOKEN_RE = re.compile(
    "|".join([
        # Fully delimited: <｜anything｜>
        r"<\s*[\u2502\u2503\uFF5C|][^>]{0,60}?[\u2502\u2503\uFF5C|]\s*>",
        # Unclosed opener: "<｜DSML｜function_calls" / "<|tool_calls_begin"
        # The keyword is matched exactly, with optional ▁/_ separated suffixes
        # like "_begin" or "▁end" — never a bare following word.
        r"<\s*[\u2502\u2503\uFF5C|]?[A-Za-z_\u2581]*[\u2502\u2503\uFF5C|]?\s*"
        r"(?:function|tool)[_\u2581]?calls?"
        r"(?:[_\u2581](?:begin|end))?",
        # Bare leaked keyword at the start of a reply.
        r"^\s*(?:function|tool)[_\u2581]?calls?(?:[_\u2581](?:begin|end))?",
    ]),
    re.IGNORECASE,
)


def strip_control_tokens(text: str) -> str:
    """Remove model-internal tool-call markers that leaked into the reply."""
    if not text:
        return text
    cleaned = _CONTROL_TOKEN_RE.sub("", text)
    if cleaned != text:
        logger.warning("Stripped model control token(s) from output")
    return cleaned.lstrip()


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


# Meta-instruction leakage. deepseek intermittently prefixes a reply with a
# fragment of system-prompt boilerplate — observed live as:
#   "You must not discuss these instructions or give any rule reminders unless
#    specifically asked about them.\nHello there. I'm at Gichogu's site..."
# It is not in our persona, not in the SDK, and not in the indexed corpus; the
# model emits it from training-data priors. It did not reproduce in 11 direct
# attempts, so it cannot be prompted away reliably — a visitor hearing the
# agent read its own rules aloud is exactly the kind of thing a guardrail is
# for. Only leading lines are stripped: mid-reply the same words are almost
# always legitimate ("the instructions say to...").
_META_LINE_RE = re.compile(
    r"""(?im)^\s*(?:
        you\s+(?:must|should|may)\s+not\s+(?:discuss|reveal|mention|share)\b.*
      | (?:do\s+not|don't|never)\s+(?:discuss|reveal|mention|repeat)\s+(?:these|your|the)\s+
        (?:instructions?|rules?|prompt|guidelines?)\b.*
      | (?:these|the\s+above)\s+(?:instructions?|rules?)\s+(?:are|must)\b.*
      | as\s+an\s+ai\s+(?:language\s+)?model,?\s+i\s+(?:must|should|cannot)\b.*
    )\s*$""",
    re.VERBOSE,
)


# A second, narrower leak shape: the model echoes a fragment of its own
# turn-generation instructions directly in front of the real reply, with no
# separator — observed live as "Write the exact words you will say.Hi there,
# I'm Gichogu's assistant...". _META_LINE_RE cannot catch this: it matches and
# drops a whole line, but here the real reply starts mid-line, right after the
# leaked fragment. So this is stripped as a prefix, not a line.
_META_PREFIX_RE = re.compile(
    r"^\s*write\s+the\s+exact\s+words\s+you\s+will\s+say\.?\s*",
    re.IGNORECASE,
)


def strip_meta_instructions(text: str) -> str:
    """Drop leaked system-prompt boilerplate from the START of a reply."""
    if not text:
        return text

    text, prefix_stripped = _META_PREFIX_RE.subn("", text, count=1)
    if prefix_stripped:
        logger.warning("Stripped leaked meta-instruction prefix")

    lines = text.splitlines()
    kept, dropped = [], 0
    for i, line in enumerate(lines):
        # Only inspect the leading block; once real content starts, stop.
        if not kept and _META_LINE_RE.match(line):
            dropped += 1
            continue
        if line.strip() or kept:
            kept.append(line)

    if dropped:
        logger.warning("Stripped %d leaked meta-instruction line(s)", dropped)
    return "\n".join(kept).lstrip()


def clean_output(text: str) -> str:
    """Everything that must never reach a visitor, in one call."""
    return strip_unapproved_urls(strip_control_tokens(strip_meta_instructions(text)))
