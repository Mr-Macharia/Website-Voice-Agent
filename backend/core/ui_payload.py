"""Attach structured UI data to a tool's return string.

A tool return has two audiences that want different things. The text chat can
render a real component -- a booking card, a lead form -- but only if it gets
parseable data. The voice channel *speaks* the same string aloud, so it must
stay a natural sentence.

So the sentence stays exactly as it was and a single-line marker is appended:

    Booking link: https://cal.com/...  (the speakable part)
    <<<ui:{"type":"booking","url":"https://cal.com/..."}>>>

Rules that make this safe:

- One line, at the very end, so a partial stream chunk either has the whole
  marker or none of it.
- Compact JSON with no newlines, so the marker can never be split across lines.
- Everything before the marker is untouched, so `strip()` on the visible part
  gives the original sentence back byte for byte.

`strip_payload` is the counterpart, used anywhere the string reaches a speaker
or a text bubble. The frontend has a matching parser in
`frontend/src/lib/toolPayload.ts`; the delimiters must stay in sync with it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

OPEN = "<<<ui:"
CLOSE = ">>>"

# Anchored to the end of the string, on its own line. DOTALL is deliberately
# NOT set: the payload is always compact JSON, so a stray newline means the
# marker is malformed and should be left alone rather than half-matched.
_PAYLOAD_RE = re.compile(
    r"\n*" + re.escape(OPEN) + r"(?P<json>[^\n]*?)" + re.escape(CLOSE) + r"\s*$"
)


def attach(text: str, payload: dict[str, Any]) -> str:
    """Append a UI payload to a tool's speakable return string."""
    if not payload:
        return text
    try:
        # separators avoids spaces; ensure_ascii keeps it single-byte-safe.
        blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        # A tool must never fail because its UI hint would not serialize.
        return text
    if "\n" in blob:
        return text
    return f"{text.rstrip()}\n{OPEN}{blob}{CLOSE}"


def extract(text: str) -> Optional[dict[str, Any]]:
    """Return the UI payload from a tool result, or None."""
    if not text or OPEN not in text:
        return None
    m = _PAYLOAD_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group("json"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def strip_payload(text: str) -> str:
    """Remove the UI payload, leaving only the speakable sentence."""
    if not text or OPEN not in text:
        return text
    return _PAYLOAD_RE.sub("", text).rstrip()
