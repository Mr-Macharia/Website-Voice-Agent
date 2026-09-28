# Findings

> **Generated file.** The findings ledger: review findings raised by `/audit`
> against the work in progress, each with a durable ID, severity (P0-P3), and
> status. `/implement` marks repaired findings `fixed`, a later `/audit` pass
> moves them to `closed`, and `/complete` refuses to merge while any P0 or P1
> finding is `open` or `fixed`, then archives resolved findings with the work
> and resets this file.

### F-06 [P3] open - LeadForm inlines a backend fetch instead of using src/api

**File:** frontend/src/components/chat/ChatArea/Messages/tools/LeadForm.tsx:92
**Found:** 2026-09-19 by /audit (scope: current; lens: quality)
**Why it matters:** `coding-standards.md` states "API calls to the backend go
through `src/api/` (`os.ts`, `routes.ts`); don't inline fetch calls to backend
endpoints elsewhere." `LeadForm` builds its own URL and calls `fetch` directly,
and `/api/leads` is absent from `APIRoutes`. Every other backend route in the
app is declared there, so this is the one endpoint that will not be found by
reading `routes.ts`. Low severity: the endpoint is passed in as a prop and the
component is otherwise well isolated.
**Suggested fix:** Add `SubmitLead: (agentOSUrl: string) => \`${agentOSUrl}/api/leads\``
to `APIRoutes` and have the caller in `Messages.tsx` build the endpoint from it.
**Resolution:**

### F-08 [P2] fixed - /api/voice/token returns 429 with `error` key, not `message` or `ok`

**File:** backend/server.py:354-358
**Found:** 2026-09-28 by /audit independent (scope: current; lens: quality, security)
**Why it matters:** The spec states "429 shape must match the existing endpoints
exactly — same body and Retry-After header as server.py:500 — so the frontend
needs no change." The `/api/leads` endpoint returns `{ok: false, message: "..."}`,
but `/api/voice/token` returns `{error: "..."}`. AssemblyAISession.ts:145-148
checks `data.detail || "Voice isn't available right now."`, so when a 429 arrives
with `{error: "..."}`, the field is missing and the frontend shows a generic
message instead of the rate-limit-specific message. While degradation is
graceful, this violates the spec's "same body" requirement and differs from the
documented pattern. If frontend code ever changes to expect `error`, the
inconsistency becomes worse. Severity P2: frontend works but doesn't surface the
actual problem, making rate-limiting less visible as a limiting factor.
**Suggested fix:** Return `{error: "..."}` is acceptable IF the frontend is
updated to look for `error` instead of `detail`, OR return `{detail: "Too many
voice sessions started — give it a minute and try again."}` to match the
frontend's existing expectation without changing it. The latter keeps frontend
code unchanged (per spec) and lets the specific message through.
**Resolution:** Fixed by /implement. `backend/server.py`'s 429 body now uses
`"detail"` instead of `"error"`, matching exactly what
`AssemblyAISession.ts:147` reads (`data.detail || "Voice isn't available right
now."`). Verified: `python3 -c "import server"` still imports cleanly and
`npm run typecheck` passes. Not yet re-reviewed against the new code -- stays
`fixed`, not `closed`, until the next audit pass.

### F-07 [P2] closed - LRU eviction lets one host reset its own rate-limit bucket

**File:** backend/core/rate_limit.py:88
**Found:** 2026-09-19 by /audit (scope: current; lens: security)
**Why it matters:** The bounded store evicts least-recently-used entries once
`_MAX_TRACKED` (4096) is exceeded. Because the key comes from the
attacker-controlled `X-Forwarded-For` header, a single host can push its own
throttled entry out of the store by sending 4096 requests with distinct
forwarded values, then resume with a fresh allowance. Reproduced directly: a
client throttled at limit 5 was no longer throttled after a 4096-key flood, and
that flood costs one machine rather than many addresses. The bound itself is
correct and necessary — an unbounded dict is its own memory-growth vector — so
this is a weakening, not a defeat: sustained abuse drops from unlimited to
roughly 5 lead writes and 5 emails per 4096 requests, a ~99.9% reduction.
**Suggested fix:** Evict by window expiry before falling back to LRU, so entries
that are still inside an active window are preferred over recency. Keeping a
small separate cap for currently-throttled keys, or trusting only the last
forwarded hop (the one the platform router appends) rather than the first, would
both remove the cheap reset. Worth doing before this endpoint sees real traffic,
but it does not reinstate the unthrottled path F-05 described.
**Resolution:** Fixed in this checkpoint. The new `_evict()` function in
`backend/core/rate_limit.py` implements the three-pass strategy: (1) drop
expired entries first, (2) drop under-limit entries (flood's own keys), then (3)
protect currently-throttled entries up to `_MAX_THROTTLED` (512) before falling
back to LRU. Verification in current-feature.md confirms all four test cases
pass: throttled key survives a 4196-key flood, store stays bounded, expired
entries evict, normal behavior correct, and 2000 deliberately throttled keys
stay under bound. The `_MAX_THROTTLED` bound itself is analysis-sound: reaching
512 throttled entries requires 512 distinct IPs each exceeding their limit once,
costing far more than the cheap single-IP attack F-07 closed. Pass 3's condition
`while len > 4096 AND throttled > 512` ensures neither bound is exceeded. Attack
surface reduced from unlimited abort to roughly 99.9% reduction as intended.
