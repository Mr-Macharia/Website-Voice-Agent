# Fix: Remove the unused Cal namespace helper

**Type:** Fix
**Status:** verified
**Branch:** fix/remove-unused-cal-namespace
**Fixes:** F-10

## The problem

`frontend/src/lib/calEmbed.ts:118` exports `loadCalNamespace`, which has **zero
callers** anywhere in `frontend/src`.

It was written during the F-08 booking-card fix while attempting a per-card
namespace approach. That approach was then abandoned: embed.js upgrades
namespaces into real embed instances in a single loop that runs once at script
load, so a namespace registered later gets a queue and never an instance, and
its calendar never appears. `BookingCard` solved the problem a different way.

The function survived the change. An exported function with no callers reads as
available API, and this one is named for exactly the problem it cannot solve —
the next person reaching for "the namespace helper" would be reaching for the
dead end.

Its docblock, however, is the most valuable thing produced by that fix: it
records with the exact source excerpt *why* namespaces cannot work, which took
four failed attempts to establish.

`getCal` (line 79) is also unused, but it predates F-08 and is out of scope here.

## The fix

Delete `loadCalNamespace` and move its explanation into a comment on
`loadCalApi`'s namespace branch, which is the code the explanation is actually
about.

**Keep the namespace machinery in `loadCalApi`.** Lines 53-67 create
`Cal.ns[namespace]` when an `init` call names one. That branch is **not** dead
code: it mirrors Cal's own published snippet, and removing it would make our
stub diverge from the contract embed.js expects when it replays the queue. Only
the wrapper goes.

**Must not break:**

- `loadCalApi` keeps its exact behaviour and signature. `BookingCard` is its
  only caller (2 references) and must not change.
- The `ns?: Record<string, CalApi>` field stays on the `CalApi` type — the stub
  still populates it.
- Booking cards keep working in text chat and voice: this is a dead-code
  removal, so a visible change means something went wrong.

## Build steps

- [x] **Step 1 — Delete the wrapper, keep the knowledge.**
      In `frontend/src/lib/calEmbed.ts`: remove the `loadCalNamespace` function
      and its docblock (lines ~86-145). Add a condensed comment on the
      namespace branch inside `loadCalApi` recording that namespaces only
      become real embed instances in the one loop embed.js runs at script load,
      so a namespace registered afterwards never renders — keeping the
      `h.instance = new v(...)` excerpt and the embed.js version, since that is
      the evidence. Leave `loadCalApi`, `getCal`, the `CalApi` type and the
      `ns` branch otherwise untouched.
      **Done when:** `grep -rn "loadCalNamespace" frontend/src` returns
      nothing; `grep -c "loadCalApi" frontend/src/components/chat/ChatArea/Messages/tools/BookingCard.tsx`
      still returns 2; and `npm run typecheck`,
      `cd frontend && npm run lint`, and `cd frontend && npm run build` pass.

## Verify

Static checks:

    npm run typecheck
    cd frontend && npm run lint
    cd frontend && npx prettier --check src/lib/calEmbed.ts
    cd frontend && npm run build

Then in the browser, with `npm run dev:all` running — this is a dead-code
removal, so the point is that **nothing changes**:

1. Ask to book in text chat. The booking card renders a working calendar.
2. Ask to book a second time. The newest card shows the calendar; the older one
   shows "Pick a time on cal.com" with no failure text.
3. Open voice mode and ask to book. The modal card shows the calendar; the
   mirrored chat card is link-only. Close the modal — the chat card takes over.

Case 3 is the F-08 behaviour most likely to be disturbed if the wrong thing is
deleted, so it is the one worth running even though no code path should change.

## Findings

### remove-unused-cal-namespace/F-10 [P3] closed - loadCalNamespace is exported but has no callers

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
**Resolution:** Fixed on `fix/remove-unused-cal-namespace`. Deleted
`loadCalNamespace` and its docblock from `lib/calEmbed.ts` (-48 lines) and
moved the explanation onto `loadCalApi`'s namespace branch, which is the code
it actually describes: why embed.js only upgrades namespaces to real instances
in one loop at script load, with the `h.instance = new v(...)` excerpt and the
v1.6.0 fingerprint kept as evidence.

The namespace machinery inside `loadCalApi` was deliberately NOT removed. It
mirrors Cal's published snippet and embed.js expects `ns` to exist when it
replays the queue, so deleting it would diverge our stub from that contract
even though nothing we write registers a namespace; a comment now records this.

`grep -rn "loadCalNamespace" frontend/src` returns nothing, `loadCalApi` keeps
its exact signature and both `BookingCard` call sites, and the `CalApi.ns`
field and both `ns` assignments survive. typecheck, lint, prettier and build
all pass. `getCal` is also unused but predates F-08 and was left alone.

Closed by /audit 2026-09-22 (scope: current; all four lenses). Re-read the
resulting file in full rather than only the diff, since a deletion's risk is in
what it leaves behind. `loadCalNamespace` is gone with no references anywhere;
`loadCalApi` keeps its signature and both `BookingCard` call sites; the
`CalApi.ns` field, `c.ns = {}` and the `ns[namespace]` assignment all survive.

Confirmed the kept machinery is correct to keep: our only `init` call passes an
object (`cal('init', { origin: CAL_ORIGIN })`), so `typeof namespace ===
'string'` is false and the branch is unreachable from our own code. It stays
because `lib/calEmbed.ts` exists to reproduce Cal's loader snippet verbatim --
a rationale `BookingCard`'s own header documents independently -- and removing
the branch would also mean removing `c.ns = {}`, which embed.js reads when it
replays the queue. `npm run typecheck` exits 0.

One note for accuracy: the comment's `h.instance = new v(...)` excerpt and the
v1.6.0 fingerprint were verified during the F-08 work from a local copy of
embed.js that is no longer on disk, so this pass could not re-derive them from
source. They are carried forward as recorded evidence, not re-proven here.
