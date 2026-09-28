# Fix: Route LeadForm's submit through src/api

**Type:** Fix
**Status:** verified
**Branch:** fix/leadform-src-api
**Fixes:** F-06

## The problem

`coding-standards.md`: "API calls to the backend go through `src/api/`
(`os.ts`, `routes.ts`); don't inline fetch calls to backend endpoints
elsewhere." `LeadForm` builds its own request instead, and the finding is
worse in the code than in the ledger entry.

**`frontend/src/components/chat/ChatArea/Messages/Messages.tsx:185`**
builds the URL with a hardcoded production fallback:

    endpoint={`${selectedEndpoint || 'http://localhost:7777'}/api/leads`}

Every other backend call in the app resolves its base URL through
`useStore`'s `selectedEndpoint`, which itself falls back to
`NEXT_PUBLIC_AGENT_OS_URL` (set at build time — see feature 17's deployment
doc). If `selectedEndpoint` is ever empty in production, this is the one
request in the whole app that silently points at `localhost:7777` instead of
failing loudly or reaching the real backend.

**`frontend/src/components/chat/ChatArea/Messages/tools/LeadForm.tsx:92`**
then calls `fetch(endpoint, ...)` directly with **no `credentials:
'include'`**. Feature 17 added the visitor cookie and updated all 8 backend
fetch call sites to send it — this one didn't exist as a distinct call site
at the time (it was inline in `Messages.tsx`'s JSX), so it was missed. The
practical effect: a lead submitted through the form is not attributed to the
visitor's cookie session the way a lead captured by the agent through
`capture_lead` is, and the backend's visitor-scoping middleware
(`backend/server.py`) never sees it on this request.

## The fix

Two changes, same reason: this call becomes indistinguishable from every
other backend call in the app.

1. **Add `SubmitLead` to `APIRoutes`** (`frontend/src/api/routes.ts`),
   following the existing `(agentOSUrl: string) => ...` shape exactly:
   `SubmitLead: (agentOSUrl: string) => \`${agentOSUrl}/api/leads\``.
2. **Build the endpoint from `APIRoutes.SubmitLead(selectedEndpoint)`** at the
   call site in `Messages.tsx`, removing the hardcoded
   `'http://localhost:7777'` fallback. `selectedEndpoint` already carries
   its own build-time-configured default; duplicating a second, different
   fallback here is exactly the drift the standard exists to prevent.
3. **Add `credentials: 'include'`** to the `fetch` call in `LeadForm.tsx`,
   matching the other 8 call sites feature 17 updated.

**Must not break:**

- The request body, method, and success/failure branching in `LeadForm.tsx`
  are unchanged — only the URL construction and the `credentials` option move.
- `LeadForm`'s `endpoint` prop keeps its current type (`string`); the
  component itself does not need to know about `APIRoutes`.
- A lead submitted anonymously (no visitor cookie reachable) must still
  succeed — `credentials: 'include'` sends a cookie if one exists but does
  not require one; the backend's `/api/leads` handler is not being changed.

## Build steps

- [x] **Step 1 — Move the endpoint through `APIRoutes` and add credentials.**
      Add `SubmitLead` to `frontend/src/api/routes.ts`. In `Messages.tsx`,
      replace the inline template string with
      `APIRoutes.SubmitLead(selectedEndpoint)`. In `LeadForm.tsx`, add
      `credentials: 'include'` to the `fetch` call.
      **Done when:** `grep -n "localhost:7777" frontend/src/components/chat/ChatArea/Messages/Messages.tsx`
      returns nothing; `APIRoutes.SubmitLead` exists and is used at the one
      call site; `credentials: 'include'` appears in `LeadForm.tsx`'s fetch;
      and `npm run typecheck`, `cd frontend && npm run lint`, and
      `cd frontend && npm run build` all pass.

## Verify

Static checks:

    npm run typecheck
    cd frontend && npm run lint
    cd frontend && npx prettier --check src/api/routes.ts src/components/chat/ChatArea/Messages/Messages.tsx src/components/chat/ChatArea/Messages/tools/LeadForm.tsx
    cd frontend && npm run build

Then in the browser, with `npm run dev:all` running:

1. Trigger the lead form (ask the agent to take your details, or however it
   currently renders) and submit it. It must still insert exactly one row —
   this is a routing change, not a validation or backend change, so nothing
   about submit behavior should look different.
2. In the Network tab, confirm the `/api/leads` request carries the
   `visitor_id` cookie (feature 17's cookie), the way `/api/voice/token` and
   the chat endpoints already do.
3. Confirm the request goes to the real backend origin, not
   `localhost:7777`, when running against a non-default `selectedEndpoint`.

## Findings

### leadform-src-api/F-06 [P3] closed - LeadForm inlines a backend fetch instead of using src/api

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
**Resolution:** Fixed on `fix/leadform-src-api`. Added `SubmitLead` to
`APIRoutes` and built the endpoint through it in `Messages.tsx`, removing a
hardcoded `'http://localhost:7777'` fallback that was not in the original
finding -- it was the one request in the app that would have silently
pointed at localhost if `selectedEndpoint` were ever empty in production.
Also added `credentials: 'include'` to `LeadForm.tsx`'s fetch, matching the
8 call sites feature 17 updated; this one was missed because it wasn't a
distinct call site (inline JSX) when that feature landed. `grep -n
"localhost:7777" Messages.tsx` returns nothing; typecheck, lint, prettier
and build all pass.

Closed by /audit 2026-09-28 (scope: current; all four lenses). Re-read all
three changed files in full, not just the diff. Confirmed
`selectedEndpoint` is a required string in the store, synchronously
initialized from `DEFAULT_ENDPOINT` (`NEXT_PUBLIC_AGENT_OS_URL` first,
localhost only as a build-time fallback) and deliberately excluded from
`localStorage` persistence -- the store's own comment records that this app
already hit and fixed a stale-`localhost:7777`-from-cache bug once, by
removing `selectedEndpoint` from persistence. `LeadForm`'s inline `||
'http://localhost:7777'` was a second, forgotten instance of the same
anti-pattern; removing it in favor of `APIRoutes.SubmitLead(selectedEndpoint)`
does not introduce a new failure mode, it removes a redundant one that could
only ever be wrong. `npm run typecheck` exits 0. Security: `credentials:
'include'` matches the other 8 call sites feature 17 already covers, no new
exposure. Performance: no change to request shape or payload.
