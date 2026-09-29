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

Counters are per endpoint. Each entry is keyed `scope:client` and stores the
limit and window it is counted under, so one endpoint's traffic never spends
another's allowance, and eviction judges every entry by its own rules. A single
shared counter once blocked a real visitor's first lead after a few voice tool
calls, and let a flood on a generous endpoint evict a throttle earned on a
strict one.

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

# Of those, how many may be *currently throttled* and therefore protected from
# eviction. Small on purpose: it is the reserve that stops a flood clearing a
# real throttle, not a second general-purpose store.
_MAX_THROTTLED = 512

# key -> (count, window_started, limit, window_seconds)
_hits: "OrderedDict[str, tuple[int, float, int, int]]" = OrderedDict()


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


def _evict(now: float) -> None:
    """Make room without letting a flood clear someone else's throttle.

    Eviction order is a security property, not a tuning detail. Plain LRU let
    one host clear its own throttle: the key comes from the client-controlled
    `X-Forwarded-For` header, so flooding `_MAX_TRACKED` distinct values pushed
    the attacker's own in-window entry out of the store and the next request
    started a fresh allowance.

    Expiry-first eviction alone does NOT fix that -- a flood's own entries are
    all in-window too, so nothing is expired and it falls straight back to LRU.
    That was measured, not assumed.

    So entries that are currently over the limit are protected: they are only
    evicted once they expire, or once the protected set itself exceeds
    `_MAX_THROTTLED`. A flood evicts spent and under-limit buckets, which cost
    nothing to lose, and cannot reach the bucket that is actively holding
    someone back.

    `_MAX_THROTTLED` keeps the protection itself bounded, since "throttled"
    is a state an attacker can enter deliberately. Reaching it takes one full
    limit-exceeding burst per protected key, which is far more expensive than
    the single cheap flood this closes.

    Every entry is judged by the limit and window it was counted under, never
    by the caller's. Judging by the caller's let a flood on `/api/voice/tool`
    (limit 60) treat a throttled `/api/leads` entry (count 6, limit 5) as
    under-limit and evict it -- the same bypass, arriving through a different
    endpoint.

    A later "cleanup" that restores `popitem(last=False)` here, or passes the
    caller's limit back in, would silently reintroduce the bypass.
    """
    if len(_hits) <= _MAX_TRACKED:
        return

    # Pass 1: drop expired entries, oldest first. They are spent.
    for key in list(_hits):
        if len(_hits) <= _MAX_TRACKED:
            return
        _, started, _, window_seconds = _hits[key]
        if now - started >= window_seconds:
            del _hits[key]

    # Pass 2: drop live entries that are still under their limit, oldest
    # first. A flood's own keys land here, which is the point.
    throttled = 0
    for key in list(_hits):
        count, _, limit, _ = _hits[key]
        if count > limit:
            throttled += 1
            continue
        if len(_hits) <= _MAX_TRACKED:
            return
        del _hits[key]

    # Pass 3: everything left is throttled. Protect them up to a bound, then
    # fall back to LRU so the store can never grow without limit.
    while len(_hits) > _MAX_TRACKED and throttled > _MAX_THROTTLED:
        _hits.popitem(last=False)
        throttled -= 1


def check(
    request, limit: int, window_seconds: int, scope: str
) -> Optional[int]:
    """Count this request against `scope`. Returns seconds to wait when over.

    `None` means allowed. Non-raising by contract: any internal failure allows
    the request rather than taking a working endpoint down.

    `scope` names the endpoint and is required with no default: a call site
    that forgets it fails at its first request instead of quietly sharing a
    bucket with every other endpoint.
    """
    try:
        key = f"{scope}:{client_key(request)}"
        now = time.monotonic()

        count, started, _, _ = _hits.get(key, (0, now, limit, window_seconds))
        if now - started >= window_seconds:
            count, started = 0, now

        count += 1
        _hits[key] = (count, started, limit, window_seconds)
        _hits.move_to_end(key)

        if len(_hits) > _MAX_TRACKED:
            _evict(now)

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
VOICE_TOKEN_LIMIT = config.VOICE_TOKEN_RATE_LIMIT
VOICE_TOKEN_WINDOW = config.VOICE_TOKEN_RATE_WINDOW
