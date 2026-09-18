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


# A fourth shape, seen on the AssemblyAI path: the model narrates its own
# retrieval step as a connector and then gives the real answer in the SAME
# sentence — "Based on that, his work involves building AI systems", "The user
# asked X. So based on the last call, he is an engineer."
#
# These must be stripped as a PREFIX, not as a sentence: _TOOL_PREAMBLE_RE
# consumes to the next terminator, which here would swallow the answer too.
# Restating the question back to the visitor ("The user asked...") is the same
# defect — it is the model talking about the conversation instead of having it.
_REASONING_PREFIX_RE = re.compile(
    r"""(?ix)
    ^\s*
    (?:
        # Restating the question back, often with the quote included.
        the \s+ (?:user|visitor) \s+ asked\b
        [^.!?\n]*                       # rest of the clause
        (?: [\"'\u201c\u201d] [^\"'\u201c\u201d]* [\"'\u201c\u201d] )?   # a quoted question
        [^.!?\n]* [.!?]* \s*
    )?
    (?:
        (?:so\s+|and\s+)? based \s+ on \s+
        (?:that|this|the\s+(?:last|previous|above)(?:\s+\w+)?)
        \s* [,:]? \s*
      | (?:so|therefore) \s* [,:] \s*
    )
    """,
)


def _recapitalize(text: str) -> str:
    """Upper-case the first letter after a prefix strip.

    Removing a leading connector leaves the real answer starting mid-sentence
    ("his work involves..."), which reads and speaks as a fragment.
    """
    if text and text[0].islower():
        return text[0].upper() + text[1:]
    return text


# A third leak shape, and the one that actually broke the audio: the model
# announces the tool call before making it — "I'll look up what Gichogu works
# on and what exactly he's done." — then stops, runs the tool, and starts a
# SECOND utterance with the real answer.
#
# Measured live: agent -> speaking at 07:59:28.153, preamble delivered by
# 07:59:31.991, speaking -> thinking at 07:59:31.992, back to speaking at
# 07:59:33.727. That is a ~1.7s dead stop mid-answer and a fresh TTS segment
# after it, heard as an unnatural pause and a change in tone. Because the gap
# is the tool round trip, it appears to track "generation speed", which is why
# it was mistaken for a TTS pacing fault.
#
# persona.py already forbids this twice (the "Do not narrate what you are about
# to do" rule names "I'll check his background" almost verbatim, and the
# conversation rules repeat "Never say 'let me check'"). The model does it
# anyway — the same reason the URL rule lives here rather than in the prompt.
#
# Deliberately narrow: anchored to the start of the reply and limited to a
# single leading sentence, so a genuine answer that happens to contain "I'll
# look into that for you" mid-paragraph is untouched. If the preamble is the
# whole message, the result is empty and no audio segment is emitted at all,
# which removes the stop/restart instead of moving it.
_TOOL_PREAMBLE_RE = re.compile(
    r"""(?ix)
    ^\s*
    (?:ok(?:ay)?[,.]?\s*|sure[,.]?\s*|alright[,.]?\s*)?   # optional lead-in
    (?:
        i(?:'|’)?ll \s+ (?:go\s+)?(?:look(?!\s+forward)|check|search|find|see|dig|pull)
      | i \s+ will \s+ (?:go\s+)?(?:look(?!\s+forward)|check|search|find|see|dig|pull)
      | let \s+ me \s+ (?:go\s+)?(?:look|check|search|find|see|dig|pull)
      | (?:one\s+moment|hold\s+on|just\s+a\s+(?:moment|sec(?:ond)?))
      | i(?:'|’)?m \s+ (?:going\s+to|gonna) \s+ (?:look|check|search|find|see)
      | i \s+ (?:can|could) \s+ (?:look|check|search) \s+ that \s+ up
      # Reasoning narrated in the first person rather than announced as an
      # action. Heard live on the AssemblyAI path: "I should look up what
      # Gichogu Macharia actually does for work first." The model is thinking
      # out loud before its tool call, which is the same defect as the
      # announcements above and produces the same stop/restart in the audio.
      | i \s+ (?:should|need\s+to|have\s+to|must) \s+
        (?:go\s+)?(?:look|check|search|find|see|dig|pull|consult|verify|confirm)
      | (?:let(?:'|’)?s|i(?:'|’)?d\s+better) \s+
        (?:go\s+)?(?:look|check|search|find|see)
    )
    \b[^.!?\n]*        # rest of that sentence only
    [.!?]*\s*           # its terminator, if any
    """,
)


def strip_tool_preamble(text: str) -> str:
    """Drop a leading "I'll look that up" announcement before a tool call."""
    if not text:
        return text
    cleaned, n = _TOOL_PREAMBLE_RE.subn("", text, count=1)
    if n:
        logger.warning("Stripped spoken tool preamble")
        return _recapitalize(cleaned.lstrip())
    return cleaned.lstrip()


def strip_meta_instructions(text: str) -> str:
    """Drop leaked system-prompt boilerplate from the START of a reply."""
    if not text:
        return text

    text, prefix_stripped = _META_PREFIX_RE.subn("", text, count=1)
    if prefix_stripped:
        logger.warning("Stripped leaked meta-instruction prefix")

    text, reasoning_stripped = _REASONING_PREFIX_RE.subn("", text, count=1)
    if reasoning_stripped:
        logger.warning("Stripped leaked reasoning prefix")
        text = _recapitalize(text.lstrip())

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
    return strip_unapproved_urls(
        strip_control_tokens(strip_tool_preamble(strip_meta_instructions(text)))
    )
