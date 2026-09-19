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

### F-08 [P2] open - Two BookingCards racing one Cal embed leaves the chat copy showing a failure

**File:** frontend/src/components/chat/ChatArea/Messages/tools/BookingCard.tsx:66
**Found:** 2026-09-20 by user browser testing during feature 16 Step 3
**Why it matters:** A voice booking mounts two `BookingCard`s from one payload:
`onToolPayload` (`AssemblyAIVoiceModal.tsx:178-203`) pushes a card turn into the
modal transcript AND calls `appendCardToChat`, which mirrors the same payload
into the main chat panel. Both mount and both call `cal('inline', ...)`.
That call is a global singleton keyed on Cal's own state, not per-element, so
Cal binds its iframe to whichever container it last received. The losing card
never receives an iframe, so its `MutationObserver` never fires, the
`EMBED_TIMEOUT_MS` (10s) timer expires, and it falls back to
"The calendar could not load here — this link still works."

Observed live: during a voice session the modal card rendered the calendar
correctly while the mirrored chat card showed the failure text. Asking again
from text mode after the modal closed rendered correctly, because only one card
was competing by then. The fallback link is always correct, so a visitor can
still book — this degrades the written record, it does not block booking.

**Suggested fix:** Give each embed its own Cal namespace
(`cal('init', <unique-namespace>)` then mount through `Cal.ns[namespace]`),
which `lib/calEmbed.ts:54-67` already builds the queue machinery for. Cheaper
alternative: render the inline calendar only in the card that is actually
visible and let the mirrored chat copy be link-only, since its job is to leave a
written record rather than to be booked from twice.
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
