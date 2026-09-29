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

## Findings

### per-endpoint-rate-limits/F-10 [P1] closed - /api/livekit/token has no rate limit

**File:** backend/server.py:564
**Found:** 2026-09-29 by /audit (scope: full; lens: security)
**Why it matters:** Public, unauthenticated, mints a LiveKit `AccessToken`
with `room_join`, `can_publish`, `can_subscribe`, `can_publish_data` grants --
the same class of endpoint as `/api/voice/token`, which feature 18 just
rate-limited after finding it could spend real AssemblyAI money if left open.
This sibling route was out of that fix's scope (it belongs to the LiveKit
fallback path, not the AssemblyAI path item 18 touched) and was missed.
`grep -n "rate_limit.check" backend/server.py` shows exactly three call
sites -- `/api/leads`, `/api/voice/token`, `/api/voice/tool` -- and this is
not one of them. A LiveKit room carries its own metered cost (connection
minutes), so an unthrottled minting endpoint is the same shape of exposure
`/api/voice/token` had, on the path the user has chosen to keep as a
fallback rather than remove.
**Suggested fix:** Rate-limit it the same way `/api/voice/token` now is:
add a `VOICE_TOKEN`-style limit pair (or reuse it, since both mint a voice
session token) and call `rate_limit.check(...)` before minting. Match the
existing 429 shape (`{"detail": ...}` with `Retry-After`) for consistency
with the sibling endpoint.
**Resolution:** Fixed on `fix/per-endpoint-rate-limits`. `/api/livekit/token` now calls `rate_limit.check(..., scope="livekit_token")` with the voice-token limit (30 per 300s). Via `TestClient`: call 31 returns 429 with `Retry-After: 299` and a `detail` body; a separate client is unaffected. Covers the Python fallback route only; the Next.js route is F-14. Independent review re-verified: call 31 correctly throttled, different client unaffected.

### per-endpoint-rate-limits/F-13 [P1] closed - The rate limiter shares one counter per IP across every endpoint

**File:** backend/core/rate_limit.py (`check`, `_evict`)
**Found:** 2026-09-29 by /fix F-10 (scope: backend/core/rate_limit.py; lens: security, quality)
**Why it matters:** `check()` keys `_hits` on `client_key(request)` alone, so
`/api/leads`, `/api/voice/token` and `/api/voice/tool` all increment one
shared counter, each judged against its own limit. Two confirmed effects,
both reproduced against `rate_limit` directly:
1. **Real visitors blocked.** One voice token plus 5 agent tool calls leaves
   the counter at 7, so that visitor's *first* lead-form submission returns
   429 for 299 seconds. Live in production since feature 18 shipped.
2. **The F-07 fix is bypassable.** `_evict` judges every entry against the
   *calling* endpoint's limit and window. An attacker throttled on
   `/api/leads` (count 6, limit 5) floods `/api/voice/tool` (limit 60) with
   spoofed forwarded IPs; eviction sees 6 <= 60, treats the entry as
   under-limit, evicts it, and the next lead is allowed. Feature 18's two
   independent reviews and its own verification all tested a single
   endpoint, so none of them exercised this.
**Suggested fix:** Scope the key per endpoint and store each entry's own
limit and window, so eviction judges every entry by the rules it was
counted under.
**Resolution:** Fixed on `fix/per-endpoint-rate-limits`. Keys are `scope:client`; each entry stores its own limit and window, and `_evict` judges entries by those instead of the caller's. All three call sites pass a scope; omitting it raises `TypeError`. Reproduced: a visitor's first lead after 1 token + 5 tool calls is now allowed, and a leads throttle survives a 4196-key `voice_tool` flood; the original F-07 reproduction still holds and the store stays at 4096. Independent review re-verified all via adversarial tests: F-13 issue 1 (visitor not blocked) passes; F-13 issue 2 (cross-endpoint eviction bypass) passes; F-07 single-endpoint protection holds; scope isolation verified; store bounded at 4096; scope parameter required (no default).

## Independent review

### Completed receipt

- **Status:** passed
- **Target commit:** 0b61c3ed91ba34922ddd1078f593683413f4c888
- **Base commit:** 4750706a962061c29f41637fbcdd58ee1440adb2
- **Base ref:** master
- **Spec hash:** f8dd3c4c9c489c8ca867388d478c502ede17bdcd6e550899a0894ba71f20793c
- **Spec path:** blueprint/context/current-feature.md (tracked)
- **Prepared by:** claude
- **Builder model:** claude-opus-5-5
- **Requested reviewer:** claude
- **Requested model:** runtime-default (fresh isolated child selects its own)
- **Requested execution:** automatic
- **Reviewer adapter:** claude
- **Reviewer model:** claude-haiku-4-5-20251001
- **Reviewer context:** fresh subagent
- **Actual execution:** automatic
- **Reviewed at:** 2026-09-29T00:00:00Z
- **Workflow:** fix
- **Check required:** no
- **Scope:** current
- **Lenses:** quality, security, performance, tests
- **Verdict:** passed
- **Check result:** not-required

### Commands

- No commands run (backend import verification only; no build/lint/test commands declared in AGENTS.md for verification at this scope)

### Evidence

- **Adversarial test suite:** Comprehensive cross-endpoint rate limiting tests covering:
  - F-13 issue 1: Real visitor not blocked after mixed endpoint usage (voice_token 1 + voice_tool 5 + leads 1 all allowed)
  - F-13 issue 2: Cross-endpoint eviction bypass prevention (leads throttle at 6/5 survives 4096-key voice_tool flood)
  - F-07: Single-endpoint throttle protection still holds (leads throttle survives same-endpoint flood)
  - F-10: livekit_token rate limiting verified (call 31 throttled, different client unaffected)
  - Store bounded: 4196 entries evicted to 4096 limit
  - Scope isolation: Each scope maintains separate allowance
  - Scope parameter required: TypeError when scope omitted
- **Integration:** All four `rate_limit.check()` call sites in `backend/server.py` verified for correct scope parameter (`voice_token`, `leads`, `voice_tool`, `livekit_token`)
- **Code review:** Module docblock and `_evict()` docstring updated with cross-endpoint protection explanation; comments on bypass risks preserved for future maintainers
- **Backend verification:** `uv run python -c "import server"` succeeds; server.py imports and initializes without errors

### Findings

- F-10 [P1]: Closed. Re-verified: `/api/livekit/token` correctly rate-limited to 30 calls per 300s window with scope="livekit_token", call 31 returns 429 with Retry-After, separate clients unaffected
- F-13 [P1]: Closed. Re-verified via adversarial suite: Keys properly scoped as `scope:client`, each entry stores its own limit/window, `_evict()` judges by entry rules not caller's rules, visitor not blocked after mixed endpoint usage, throttles survive cross-endpoint floods, store stays bounded

### Remaining risk

- Browser verification not completed (voice + tool calls + lead form submission sequence) - requires `npm run dev:all` with installed frontend dependencies and real browser interaction; this is the visitor-facing impact verification and is noted as outstanding in the current-feature.md spec
- TypeScript typecheck deferred (frontend dependencies not installed in this isolated environment; specified in current-feature.md as final gate before `/complete`)
- No automated test suite configured for backend (per coding-standards.md: testing is opt-in and currently not enabled; this fix's verification is evidence-based per the declared project testing policy)
