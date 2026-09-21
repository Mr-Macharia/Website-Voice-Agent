# Fix: Cal booking-card embed race

**Type:** Fix
**Status:** verified
**Branch:** fix/cal-booking-card-embed-race
**Fixes:** F-08

## The problem

When two `BookingCard`s are mounted at once, only one gets a calendar. The other
sits empty for 10 seconds and then collapses to
"The calendar could not load here — this link still works."

`cal('inline', { elementOrSelector, calLink, ... })`
(`BookingCard.tsx:66`) addresses Cal's **default global namespace**. The
`elementOrSelector` argument names a target, but the embed state behind it is
one global instance, so a second `inline` call re-points that single instance at
the newer element. The first container never receives an iframe, its
`MutationObserver` never fires, and `EMBED_TIMEOUT_MS` (10s) expires.

Two ways to reach this, both real:

1. **Voice booking** (the reported case). `onToolPayload`
   (`AssemblyAIVoiceModal.tsx:178-203`) pushes a card turn into the modal
   transcript *and* calls `appendCardToChat`, mirroring the same payload into
   the main chat. Both mount. Observed live 2026-09-20: the modal card rendered
   the calendar, the mirrored chat card showed the failure text.
2. **Two bookings in one chat session.** `Messages.tsx:176` renders a card per
   booking tool call, and past messages stay mounted, so asking to book twice
   races the same singleton — no voice involved.

A visitor can always still book: the "Open on cal.com" link is rendered
unconditionally and is correct in every state. This degrades the on-screen and
written record, it does not block booking.

**Reproduced 2026-09-20** in a private window with extensions disabled, which
rules out an ad-blocker, a CSP (none is configured) and a bad URL: during one
voice booking the modal card rendered the real Cal iframe ("Gichogu Macharia /
AI and Automation Consultation / Welcome to my booking link...") while the
mirrored card in the chat panel behind it showed the failure text. Same
payload, same browser, same moment -- one card won the singleton, the other
timed out. Server side was verified healthy at the same time: `embed.js` 200
(90,535 bytes), the Cal booker page 200, and `/api/voice/tool` returning the
correct `{type, url, label, note}` payload.

## The fix

Give every card its own Cal **namespace** instead of sharing the default one.
`lib/calEmbed.ts:54-67` already implements the namespace queue: `cal('init',
'<name>')` creates `Cal.ns['<name>']` with its own queue, and subsequent calls
go through that namespaced function rather than the global one.

Each `BookingCard` derives a stable unique namespace, calls
`cal('init', namespace, { origin })`, then issues `inline` and `ui` through
`Cal.ns[namespace]`. Two cards then hold two independent embed instances and
neither can steal the other's iframe.

The namespace must be a stable string for the life of the component instance
(`useRef` or `useState` initializer, not a value recomputed each render), and
must be safe as an object key. A module-level counter is sufficient and
deterministic; do not use the calLink, because two cards can share one link —
that is exactly the reported case.

**Must not break:**

- The existing fallback. If the embed genuinely fails, the card must still
  collapse to the link-only state; do not remove the timeout or the observer.
- The `mountedRef` double-mount guard — the component re-renders whenever the
  message list updates.
- The unconditional "Open on cal.com" link, in every status.
- Existing single-card behavior in text chat, which works today.
- The `theme: 'dark'`, `layout: 'month_view'` and `cal-brand` styling, and the
  `min-h-[560px]` container sizing.

**Out of scope:** changing the mirroring in `AssemblyAIVoiceModal.tsx`,
the lead form, and `Messages.tsx` layout. The repair belongs in the card and its
loader, so every render site benefits without each one knowing about Cal.

## Correction — the namespace approach does not work

Step 1 shipped namespaces and was tested live 2026-09-20: **the first booking
card rendered, the second still showed the fallback.** Better than before (the
loser was previously whichever card mounted last) but not fixed.

Root cause, read directly from the shipped `app.cal.com/embed/embed.js`
(v1.6.0, fingerprint e8a6bde7). Its bootstrap ends with:

    h.instance = new v(xe, h.q)
    for (const [a, e] of Object.entries(h.ns))
      e.instance = e.instance ?? new v(a, e.q)

That loop runs **exactly once**, when the script finishes loading. A namespace
registered before that moment is upgraded into a real embed instance. A
namespace registered *after* it gets a queue from our loader stub and nothing
else: no `instance` is ever constructed, its queued `inline` call is never
processed, and no iframe appears. The constructor `v` is module-private, so
there is no post-load path to instantiate a late namespace.

`loadCalApi` injects the script on the first `cal()` call, so the first card on
a page registers its namespace before load and works, and every card mounted
after the script lands is orphaned. That is exactly the observed result.

Namespaces are therefore only usable when every embed is known before the
script loads, which a chat that renders cards as the conversation happens can
never guarantee. Revert to the alternative this spec already recorded.

## Revised fix

Render the inline calendar in **at most one** card at a time — the newest one,
which is the one the visitor just asked for — and let every other booking card
be link-only.

A module-level registry tracks which card instance currently owns the embed.
The newest mounted card claims it; any card that does not own it renders the
card chrome, the label, the note and the "Open on cal.com" link, with no
calendar and **no failure text**, because nothing failed. The `status: 'failed'`
copy stays reserved for a genuine embed failure.

This also fixes the two-bookings-in-one-chat case: the older card stops showing
a broken calendar and shows a clean link instead.

**Must not break** (unchanged from above), plus:

- A non-owning card must not display "The calendar could not load here". It is
  not an error state; it is a deliberate link-only presentation.
- The owning card keeps the full existing behavior including the timeout and
  the real failure path.

## Correction 2 — claiming during render broke the voice card

Step 1b claimed ownership in the render phase. Tested live 2026-09-20: the text
card worked and the old card correctly went link-only, but the **voice** card
lost its calendar, with a React console error:

    Cannot update a component (`BookingCard`) while rendering a different
    component (`BookingCard`).

`claimCalOwnership` notifies every other card synchronously, so calling it
during render meant calling `setState` on a component React was not rendering.
React rejects that, the notification did not land, and the voice card was left
without its calendar.

Fixed by splitting the two jobs. The render phase only allocates the card's id
(a pure ref write, no notification). The claim moved into the mount effect,
where notifying siblings is a normal commit-phase update. A card starts
optimistically as owner and is corrected on mount; because a card subscribes
before it claims, the claimer sets itself owner and demotes every other card in
the same pass, so exactly one owner always remains.

`calOwnerId` became dead in the process and was removed — ownership now flows
through the listener callback alone.

## Correction 3 — "newest wins" gave the calendar to the wrong card

Correction 2 removed the React error, but live testing showed the calendar in
the **chat panel behind the modal** while the voice card said "Pick a time on
cal.com". The visitor was looking at the link-only card.

Cause: `onToolPayload` calls `setTurns` and then `appendCardToChat`, so the
mirrored chat card mounts second. Under "newest wins" it took the calendar,
even though the modal sits on top of it.

Recency is the wrong rule; visibility is the right one. Ownership is now
ranked: `BookingCard` takes an optional `priority` prop, set by the voice modal,
and a priority card outranks a plain one no matter when it mounted. Among equal
ranks the newest still wins, which remains correct for two bookings in one chat.
Unmounting releases ownership, so closing the modal hands the calendar to the
mirrored chat card instead of leaving none on screen.

A simulation of the claim sequence caught a further bug before the browser did:
`claimCalOwnership` returned early when outranked and therefore never notified,
leaving the rejected card on its optimistic `isOwner = true` — two calendars.
A rejected claim now re-notifies the current owner. Verified across four
sequences (modal mounts, mirror mounts, modal closes, two text bookings), each
leaving exactly one owner.

## Correction 4 — the real root cause: Cal allows one inline embed per page

Corrections 1-3 all assumed a race between two cards. They were wrong. Reading
`inline()` in embed.js v1.6.0 shows the actual constraint:

    if (this.cal.inlineEl && document.body.contains(this.cal.inlineEl)) {
      console.warn("Inline embed already exists. Ignoring this call")
      return
    }

One inline embed per Cal instance, ever. There is no teardown API and
`inlineEl` is assigned once and never cleared, so the ONLY way to free the
embed is to remove the previous element from the DOM -- the
`document.body.contains` clause is the escape hatch.

This produced the blank container seen live: the chat card won ownership and
called `inline()`, Cal ignored the call, and `mountedRef` was already true so
it never retried. An empty box, indefinitely.

Two changes complete the fix on top of the ownership work:

1. Losing ownership clears `mountedRef` and resets status, so a card that later
   regains ownership mounts afresh rather than rendering an empty container.
   The non-owner branch already unmounts the container, which is what frees
   Cal's guard.
2. The mount is deferred one frame with `requestAnimationFrame`. Closing the
   modal can remove its container and mount the chat card's in the same React
   commit, and Cal's `contains()` check is synchronous, so an immediate call
   can still see the old element and refuse.

Verified live 2026-09-20: voice booking shows the calendar in the modal,
closing the modal hands a working calendar to the mirrored chat card, a second
text booking takes the calendar while the older card shows "Pick a time on
cal.com", and the genuine failure path still reports the real error.

## Build steps

- [x] **Step 1 — Mount each card in its own Cal namespace.** _(superseded: see Correction)_
      In `lib/calEmbed.ts`, confirm or extend the loader so a namespaced API can
      be obtained for a given name, returning the namespaced callable (the
      existing `init` branch already creates `Cal.ns[namespace]`; add a small
      accessor rather than reaching into `ns` from the component).
      In `BookingCard.tsx`, generate one stable namespace per component instance
      and route `init`, `inline` and `ui` through it. Keep `mountedRef`, the
      observer, the timeout and every rendered state as they are.
      **Done when:** `npm run typecheck` and `cd frontend && npm run lint` pass,
      and `cd frontend && npm run build` succeeds.

- [x] **Step 1b — Render the calendar in only the newest card.**
      Add a module-level owner registry to `BookingCard.tsx`. The most recently
      mounted card claims ownership; a card that does not own the embed renders
      link-only with no calendar and no failure text. Keep `loadCalNamespace`
      in `calEmbed.ts` with a comment recording why namespaces alone are
      insufficient, so this is not re-attempted.
      **Done when:** typecheck, lint, prettier and build pass.

- [x] **Step 2 — Confirm both race paths in the browser.**
      With `npm run dev:all` running, verify all four cases below under Verify.
      Fix any regression found here inside this step.
      **Done when:** every Verify case below is observed, and the console shows
      no new errors.

## Verify

Browser, with backend and frontend running:

1. **Voice booking (the reported case).** Open the Live Voice Agent, ask to book.
   The card in the voice transcript shows a working calendar, **and** the
   mirrored card in the chat panel behind it also shows a working calendar —
   not "The calendar could not load here".
2. **Two bookings in one chat.** In text mode, ask to book, wait for the card,
   then ask again. Both cards show their own calendar, and picking a date in
   one does not change the other.
3. **Single card unchanged.** A fresh text-mode booking still renders one
   working calendar with the dark theme and orange brand colour.
4. **Fallback intact.** In DevTools, block `app.cal.com` (Network request
   blocking) and ask to book. The card collapses to the link-only state with
   "The calendar could not load here — this link still works", and
   "Open on cal.com" still points at the right URL.

`npm run validate` is broken independently of this work (it shells out to
`pnpm`, which is not installed). Run the checks individually via `npm`.
Prettier resolves its Tailwind plugin only when run from `frontend/`.

## Findings

### cal-booking-card-embed-race/F-08 [P2] closed - Two BookingCards racing one Cal embed leaves the chat copy showing a failure

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
**Resolution:** Fixed on `fix/cal-booking-card-embed-race`. The diagnosis in
this entry was incomplete: the cards do collide, but not as a race. Cal's
`inline()` (embed.js v1.6.0) refuses outright when a previous inline element is
still in the DOM -- "Inline embed already exists. Ignoring this call" -- and
exposes no teardown API, so only ONE inline embed can exist per page and the
sole way to free it is removing the previous element.

Namespaces were tried first and do not work: embed.js upgrades namespaces into
real instances in a single loop that runs once when the script loads, so a
namespace registered later gets a queue and never an instance. Documented in
`lib/calEmbed.ts` so it is not re-attempted.

The shipped fix renders the calendar in exactly one card. Ownership is ranked,
not merely recent: a card in the voice modal (`priority`) outranks the mirrored
chat card regardless of mount order, and among equal ranks the newest wins.
Unmounting releases ownership, losing it clears the mount guard so a card can
remount if it regains ownership, and the mount is deferred one frame so Cal's
synchronous `document.body.contains` check sees the removal. A non-owning card
shows "Pick a time on cal.com" rather than the failure text, because nothing
failed.

Verified live by the user 2026-09-20 across all four paths.

Closed by /audit 2026-09-21 (scope: current; all four lenses). Re-reviewed the
repaired code rather than the repair note. Simulated the ownership protocol
across five sequences -- modal+mirror, modal close, two text bookings, a
priority card opening over two existing chat cards, and that priority card
closing -- and every one ends with exactly one owner, with the newest
equal-ranked card reclaiming after a release rather than the oldest. Traced the
mount effect for a setState/rerun loop: losing ownership calls setStatus but
leaves the effect's deps unchanged, so it does not re-fire. Listener, observer
and timer registrations all have matching cleanup. `toolPayload.ts` is
unmodified, so URL validation and `rel="noopener noreferrer"` are intact.
`npm run typecheck` exits 0.
