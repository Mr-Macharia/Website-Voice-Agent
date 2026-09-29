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

### F-11 [P2] fixed - The localhost fallback pattern F-06 removed still exists in two voice call sites

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
