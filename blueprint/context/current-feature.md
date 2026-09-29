# Fix: Per-endpoint rate limits

**Type:** Fix
**Status:** verified
**Branch:** fix/per-endpoint-rate-limits
**Fixes:** F-13, F-10

## The problem

Two findings, one root cause, fixed in dependency order.

**F-13 (P1): the limiter shares one counter per IP across every endpoint.**
`backend/core/rate_limit.py`'s `check()` keys `_hits` on `client_key(request)`
alone, so `/api/leads`, `/api/voice/token` and `/api/voice/tool` all count
into one bucket, each judged against its own limit. Both effects below were
reproduced against `rate_limit` directly:

- **Real visitors blocked.** One voice token plus 5 agent tool calls leaves
  the counter at 7, so the visitor's *first* lead-form submission returns 429
  for 299 seconds. This is live in production.
- **The F-07 fix is bypassable.** `_evict` judges every entry against the
  *calling* endpoint's limit and window. An attacker throttled on
  `/api/leads` (count 6, limit 5) floods `/api/voice/tool` (limit 60, window
  60s) with spoofed forwarded IPs; eviction sees 6 <= 60, treats the entry as
  under-limit, evicts it, and the next lead is allowed.

**F-10 (P1): `/api/livekit/token` (`backend/server.py:564`) has no rate
limit.** It mints a LiveKit token with room-join/publish grants, unlike its
sibling `/api/voice/token`. Adding it to the current shared counter would
make F-13 worse, which is why F-13 comes first.

## The fix

**Step 1 — scope the limiter per endpoint (F-13).** `check()` takes a
required `scope` string and keys entries as `f"{scope}:{client}"`, so each
endpoint counts separately. Each entry stores its own `limit` and `window`
alongside `count` and `started`, and `_evict` judges every entry by the rules
it was counted under instead of the caller's. The three existing call sites
pass `"leads"`, `"voice_token"` and `"voice_tool"`. `scope` has no default:
a call site that forgets it fails with a `TypeError` at the first request
rather than silently sharing a bucket.

The eviction order, the `_MAX_TRACKED` / `_MAX_THROTTLED` bounds, and the
non-raising contract of `check()` are unchanged. The module docblock and the
`_evict` docstring gain a note that entries are per-endpoint and judged by
their own limits, since a later cleanup that drops either would silently
reintroduce this bypass.

**Step 2 — rate-limit `/api/livekit/token` (F-10).** Add `request: Request`
to `generate_livekit_token` and call `rate_limit.check(request,
rate_limit.VOICE_TOKEN_LIMIT, rate_limit.VOICE_TOKEN_WINDOW,
scope="livekit_token")` before minting. It reuses the voice-token limit (30
per 5 minutes) because both endpoints mint one voice session per call; it
gets its own scope so the two transports never share a bucket. No new env
vars. On 429 it returns `{"detail": "..."}` with `Retry-After`, matching
`/api/voice/token`.

**Must not break:**

- A normal visitor: one voice session with several tool calls, then a lead
  submission, must all be allowed.
- The original F-07 single-endpoint reproduction must still hold: a throttled
  key survives a 4096-key flood on its own endpoint.
- The store stays bounded at `_MAX_TRACKED`.
- `check()` stays non-raising for internal failures; the new required
  argument is a programming contract, not a runtime failure path.
- The existing 429 bodies of `/api/leads` and `/api/voice/token` are
  unchanged.

## Out of scope

- **F-14**, the Next.js `/api/livekit/token` route. It is the *primary*
  LiveKit token path and runs on Vercel serverless, where an in-memory
  limiter cannot work. It only mints when LiveKit credentials are set on
  Vercel. Step 2 covers the Python fallback route only.
- F-11 and F-12, unrelated to the limiter.
- Moving the limiter to Redis. Still one dyno.

## Build steps

- [x] **Step 1 — Scope the limiter per endpoint (F-13).**
      Change `check()` and `_evict()` in `backend/core/rate_limit.py` as
      above, and pass a scope at the three call sites in
      `backend/server.py` (lines ~347, ~447, ~519).
      **Done when:** a throwaway script against `rate_limit` shows all of:
      (a) one voice token + 5 tool calls leaves the visitor's first lead
      allowed; (b) an attacker throttled on leads stays throttled after a
      4196-key flood on the voice-tool scope; (c) the original F-07
      reproduction still holds on the leads scope alone; (d) the store stays
      at or below `_MAX_TRACKED`; and `uv run python -c "import server"`
      succeeds from `backend/`.

- [x] **Step 2 — Rate-limit `/api/livekit/token` (F-10).**
      Wire `rate_limit.check(..., scope="livekit_token")` into
      `generate_livekit_token` as above.
      **Done when:** a script shows the 31st call in a window is blocked
      with a positive `Retry-After` while a separate client is unaffected;
      `grep -n 'rate_limit.check' backend/server.py` shows four call sites;
      and `uv run python -c "import server"` succeeds.

## Verification evidence (2026-09-29)

Scripts run with `uv run python` from `backend/`.

**Step 1 (F-13).** Against `rate_limit` directly:

| Case | Result |
|---|---|
| (a) First lead after 1 voice token + 5 tool calls | allowed (was 429 for 299s) |
| (b) Throttled on leads, then 4196-key flood on `voice_tool` | still blocked, retry 299s (was allowed) |
| (c) Original F-07 reproduction, same scope | still blocked, retry 299s |
| (d) Store bounded | 4096 <= 4096 |
| `check()` called without `scope` | `TypeError` |

**Step 2 (F-10).** Through the real endpoint via FastAPI `TestClient`: the
first 30 `GET /api/livekit/token` calls return 200; call 31 returns 429 with
`Retry-After: 299` and `{"detail": "Too many voice sessions started ..."}`;
a separate client still gets 200. `grep -c rate_limit.check backend/server.py`
is 4.

**Final gate.** `npm run typecheck` passes; `uv run python -c "import
server"` succeeds. Browser check (voice + tool calls, then lead form) is
outstanding and is the user's.

## Verify

Use `uv run python`, not the system `python3`: the backend venv holds
`livekit`, and `python3 -c "import server"` fails outside it.

    cd backend && uv run python -c "import server"
    npm run typecheck

No test runner is configured, so the Step 1 and Step 2 scripts are the
evidence. Record their output in this spec.

Then with `npm run dev:all`: open voice, let the agent make a few tool calls,
then submit the lead form. It must save on the first try. That is the
visitor-facing bug this fix exists for.

This changes a security boundary on four public endpoints, so
`independentReview: when-sensitive` applies: an independent review is
required before `/complete`. Ask the reviewer to test across scopes, not
just within one — that is the gap that let the F-07 bypass through two
previous reviews.
