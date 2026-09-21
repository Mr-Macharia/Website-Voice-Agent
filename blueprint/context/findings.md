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

### F-07 [P2] open - LRU eviction lets one host reset its own rate-limit bucket

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
**Resolution:**

### F-09 [P3] open - The voice control bar derives behavior from a display string

**File:** frontend/src/components/voice/VoiceAgentControlBar.tsx:26
**Found:** 2026-09-20 by /audit (scope: current; lens: quality)
**Why it matters:** `const isLiveKit = mode.toLowerCase().includes('livekit')`
makes one prop do two jobs: `mode` is rendered verbatim to the visitor at line
60, and it is simultaneously parsed to choose which icon to show. The three
values passed today (`VOICE_MODE_LABEL`, `"LiveKit WebRTC"`, `"LiveKit voice"`)
all resolve correctly, so this is not a live bug. But the coupling is invisible
from the call sites: centralizing the label in `VOICE_MODE_LABEL` (this fix)
means a future copy edit happens in `lib/agentIdentity.ts`, one file removed
from the substring test that depends on it. Renaming the label to something
containing "livekit", or renaming the LiveKit modes to drop it, silently
switches the icon with no type error and nothing failing.
**Suggested fix:** Pass the transport as its own prop — for example
`transport?: 'livekit' | 'assemblyai'` — and keep `mode` purely for display.
Small and local: three call sites and one component. Not urgent, and out of
scope for the F-04 fix, which only moved literals.
**Resolution:**

### F-10 [P3] open - loadCalNamespace is exported but has no callers

**File:** frontend/src/lib/calEmbed.ts:118
**Found:** 2026-09-21 by /audit (scope: current; lens: quality)
**Why it matters:** The F-08 fix added `loadCalNamespace` while attempting the
namespace approach, then abandoned that approach when embed.js turned out to
instantiate namespaces only once at script load. The function survived the
change and now has zero callers anywhere in `frontend/src`. Its docblock is
genuinely valuable -- it records, with the exact source excerpt, why namespaces
cannot solve this problem, which is the single most expensive thing learned
during four failed attempts. But an exported function with no callers reads as
available API, and the next person may reach for it precisely because it is
named for the problem it cannot solve.
**Suggested fix:** Keep the explanation, drop the code: move the docblock's
content into a comment near `loadCalApi` (or into the `BookingCard` header
where the ownership protocol is described) and delete the function. Alternative:
keep it and mark it `@internal`/unused-by-design with an explicit pointer to
`BookingCard`'s ownership comment. Either is fine; leaving a silently unused
export is the option to avoid. Note `getCal` at line 79 is also unused, but it
predates this fix and is out of scope for this entry.
**Resolution:**
