"""A small in-process rate limiter for the public, unauthenticated endpoints.

Why this exists: `/api/leads` writes a row to Postgres *and* emails the owner's
own mailbox on every request, and `/api/voice/tool` runs real tools. Both are
reachable without a key, so without a limit a trivial loop fills the leads table
and floods an inbox.

Why not slowapi or redis: two routes on a single dyno. A fixed-window counter in
memory needs no dependency and no network hop. The trade-offs are honest and
worth stating:

  - Per process. Scale past one dyno and each gets its own allowance. That is
    the point at which this should move to Redis, not before.
  - Fixed window, not sliding. A burst can straddle a boundary and see up to
    twice the limit. Irrelevant at these limits; it exists to stop scripted
    abuse, not to meter an API.
  - Memory is bounded on purpose (see `_MAX_TRACKED`). An unbounded dict keyed
    on client IP is itself a memory-growth vector on a public endpoint.

Cookies are deliberately not used as the key. A cookie is a header the client
writes, so an abuser either omits it or rotates it per request; keying on one
would be a limiter with a one-line bypass.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Optional

from core import config


# Above this many tracked clients, the oldest entries are dropped. A burst from
# many addresses evicts rather than growing without bound; the cost of evicting
# an in-window attacker is that they get one fresh allowance, which is far
# cheaper than an unbounded dict.
_MAX_TRACKED = 4096

_hits: "OrderedDict[str, tuple[int, float]]" = OrderedDict()


def client_key(request) -> str:
    """The best available identifier for the caller.

    Heroku terminates TLS at its router, so `request.client.host` is the router
    for every visitor. `X-Forwarded-For`'s first hop is the original client.
    That header is spoofable, but a caller willing to forge it can equally use
    many source addresses, and without it the limiter would treat all traffic
    behind the proxy as one client and throttle real visitors.
    """
    try:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first[:64]
        client = getattr(request, "client", None)
        host = getattr(client, "host", None)
        return str(host)[:64] if host else "unknown"
    except Exception:
        # Never raise on the hot path; an unidentifiable caller shares one
        # bucket rather than bypassing the limit entirely.
        return "unknown"


def check(request, limit: int, window_seconds: int) -> Optional[int]:
    """Count this request. Returns seconds to wait when over the limit.

    `None` means allowed. Non-raising by contract: any internal failure allows
    the request rather than taking a working endpoint down.
    """
    try:
        key = client_key(request)
        now = time.monotonic()

        count, started = _hits.get(key, (0, now))
        if now - started >= window_seconds:
            count, started = 0, now

        count += 1
        _hits[key] = (count, started)
        _hits.move_to_end(key)

        while len(_hits) > _MAX_TRACKED:
            _hits.popitem(last=False)

        if count > limit:
            return max(1, int(window_seconds - (now - started)))
        return None
    except Exception:
        return None


def reset() -> None:
    """Clear all counters. For tests and manual verification."""
    _hits.clear()


# Defaults are deliberately generous: a real visitor submits the lead form once,
# and a voice conversation makes a handful of tool calls per minute.
LEADS_LIMIT = config.LEADS_RATE_LIMIT
LEADS_WINDOW = config.LEADS_RATE_WINDOW
VOICE_TOOL_LIMIT = config.VOICE_TOOL_RATE_LIMIT
VOICE_TOOL_WINDOW = config.VOICE_TOOL_RATE_WINDOW
