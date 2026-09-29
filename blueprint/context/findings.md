# Findings

> **Generated file.** The findings ledger: review findings raised by `/audit`
> against the work in progress, each with a durable ID, severity (P0-P3), and
> status. `/implement` marks repaired findings `fixed`, a later `/audit` pass
> moves them to `closed`, and `/complete` refuses to merge while any P0 or P1
> finding is `open` or `fixed`, then archives resolved findings with the work
> and resets this file.

### F-09 [P3] unverified - LiveKitVoiceModal inlines a Next.js API route fetch, not through src/api

**File:** frontend/src/components/voice/LiveKitVoiceModal.tsx:1641
**Found:** 2026-09-28 by /audit (scope: current; lens: quality)
**Why it matters:** Encountered while auditing F-06's fix, outside its scope.
`fetch(`/api/livekit/token?room=${roomName}`)`, with a fallback to
`${selectedEndpoint}/api/livekit/token`, is not the AgentOS backend pattern
`coding-standards.md`'s `src/api/` rule targets (that rule is about calls to
the Python backend; this primary call is to a same-server Next.js route).
Unverified rather than open: it is inside the LiveKit fallback path, which is
out of scope for both F-06 and this pass, and it is not certain the standard
was intended to cover Next.js API routes as well as the Python backend.
**Suggested fix:** If `src/api/` is meant to cover this class of call too,
extend `APIRoutes` or add a sibling convention for local routes; otherwise
mark it explicitly out of scope in `coding-standards.md`.
**Resolution:**

### F-10 [P1] fixed - /api/livekit/token has no rate limit

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
**Resolution:** Fixed on `fix/per-endpoint-rate-limits`. `/api/livekit/token` now calls `rate_limit.check(..., scope="livekit_token")` with the voice-token limit (30 per 300s). Via `TestClient`: call 31 returns 429 with `Retry-After: 299` and a `detail` body; a separate client is unaffected. Covers the Python fallback route only; the Next.js route is F-14.

### F-11 [P2] open - The localhost fallback pattern F-06 removed still exists in two voice call sites

**File:** frontend/src/components/voice/AssemblyAIVoiceModal.tsx:137, frontend/src/components/voice/LiveKitVoiceModal.tsx:732
**Found:** 2026-09-29 by /audit (scope: full; lens: quality)
**Why it matters:** F-06 removed `${selectedEndpoint || 'http://localhost:7777'}` from `Messages.tsx`, establishing during that fix that
`selectedEndpoint` is a required string in the store, synchronously
initialized from `NEXT_PUBLIC_AGENT_OS_URL` (localhost only as a *build-time*
fallback), and deliberately excluded from `localStorage` persistence after
the app already hit and fixed a stale-cached-localhost bug once. The same
`|| 'http://localhost:7777'` construction is duplicated at two more call
sites -- both on the primary voice-connection path, higher-traffic than the
lead form F-06 touched. The duplicate fallback can only ever be wrong: if
`selectedEndpoint`'s non-empty contract ever changes, these two call sites
silently reintroduce exactly the bug F-06 closed, in a place nobody would
think to check because the "real" fallback lives in `store.ts`.
**Suggested fix:** Read `selectedEndpoint` directly in both call sites, the
way `Messages.tsx` now does, since the store guarantees it is always a
non-empty string.
**Resolution:**

### F-12 [P3] unverified - The voice-token fetch is browser-initiated but excluded from visitor-cookie scoping

**File:** frontend/src/lib/voice/AssemblyAISession.ts:142, backend/server.py:260
**Found:** 2026-09-29 by /audit (scope: full; lens: security)
**Why it matters:** `_NO_COOKIE_PATHS`'s comment states the exclusion is for
"server-to-server callers... AssemblyAI calls the LLM proxy with no browser
and no cookie." That rationale clearly covers `/api/llm/` and
`/api/voice/tool` (called by AssemblyAI itself via `AssemblyAISession`'s
client-side relay of a `tool.call` event). But the initial
`GET /api/voice/token` fetch at `AssemblyAISession.ts:142` runs directly in
the browser before any AssemblyAI session exists -- it is the request that
*starts* the session, not a callback from it. It has no `credentials:
'include'` and is excluded from cookie scoping, unlike every other
browser-initiated backend call in the app since feature 17. Unverified rather
than open because the exclusion may be intentional for an unstated reason
(voice sessions may not need visitor-cookie attribution the way chat/leads
do), and confirming that requires a product decision, not just code reading.
**Suggested fix:** Either confirm voice sessions are deliberately excluded
from visitor scoping and extend the code comment to say so explicitly, or
remove `/api/voice/token` from `_NO_COOKIE_PATHS` and add `credentials:
'include'` to its fetch, matching every other browser-initiated call.
**Resolution:**

### F-13 [P1] fixed - The rate limiter shares one counter per IP across every endpoint

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
**Resolution:** Fixed on `fix/per-endpoint-rate-limits`. Keys are `scope:client`; each entry stores its own limit and window, and `_evict` judges entries by those instead of the caller's. All three call sites pass a scope; omitting it raises `TypeError`. Reproduced: a visitor's first lead after 1 token + 5 tool calls is now allowed, and a leads throttle survives a 4196-key `voice_tool` flood; the original F-07 reproduction still holds and the store stays at 4096.

### F-14 [P2] open - The Next.js LiveKit token route mints unthrottled tokens on Vercel

**File:** frontend/src/app/api/livekit/token/route.ts
**Found:** 2026-09-29 by /fix F-10 (scope: frontend/src/app/api/livekit; lens: security)
**Why it matters:** `LiveKitVoiceModal.tsx:1641` calls this same-origin route
*first* and only falls back to the Python `/api/livekit/token` when it
fails, so this is the primary LiveKit token path. It signs a 1-hour token
with room-join/publish grants and embeds an agent dispatch, and accepts a
client-chosen `identity` and `room`. It has no rate limit, and Vercel's
serverless functions share no memory, so the in-process Python limiter
cannot cover it. Exposure is conditional: the route returns 500 unless
`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and a LiveKit URL are set on Vercel,
and the default voice path is AssemblyAI.
**Suggested fix:** Either keep LiveKit credentials off Vercel unless the
fallback is actively in use (and say so in `docs/deployment.md`), or route
the fallback's token minting through the rate-limited Python endpoint once
it can embed the same agent dispatch.
**Resolution:**
