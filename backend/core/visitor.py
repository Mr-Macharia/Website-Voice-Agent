"""The opaque cookie that identifies a browser.

A visitor's chat history should survive a reload and follow them across tabs
without anyone signing in. This is the whole identity story: a random value in
an HttpOnly cookie, minted server-side, meaning nothing outside this app.

It is not a login and must never be treated as one. Clearing cookies or opening
a private window is a new visitor, which is the intended behaviour. Anyone
holding the cookie value is that visitor, so the value never appears in a URL,
a log line, or a response body.

The value is also attacker-controlled input: a cookie is whatever the client
sends. `is_valid_visitor_id` rejects anything that is not the exact shape this
module mints, and the caller treats a rejected cookie as no cookie at all.
"""

from __future__ import annotations

import re
import secrets

# secrets.token_urlsafe(32) yields 43 characters from the URL-safe base64
# alphabet. Matching the exact length as well as the alphabet keeps a
# truncated or padded value from being accepted as a different visitor.
_TOKEN_BYTES = 32
_VISITOR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def new_visitor_id() -> str:
    """Mint a fresh, unguessable visitor id."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def is_valid_visitor_id(value: str | None) -> bool:
    """True only for a value this module could have minted.

    Never trust the cookie's contents: a client can send any string. A value
    that fails here is discarded and replaced rather than repaired.
    """
    if not value:
        return False
    return bool(_VISITOR_ID_RE.match(value))
