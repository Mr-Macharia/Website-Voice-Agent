# Feature: Sidebar cleanup for public deployment

**From build-plan:** feature 16
**Build attempt:** 1
**Type:** Feature
**Status:** verified
**Branch:** feature/sidebar-cleanup-for-public-deployment

## Goal

The sidebar currently exposes four developer controls to every visitor: the
backend endpoint URL, the Agent/Team mode switch, an auth token field, and the
raw model name. On a public portfolio site none of these are meaningful to a
visitor, and two are actively harmful — the endpoint is editable and persisted,
and the model name is internal detail.

After this feature the sidebar shows only what a visitor can act on: the header,
New Chat, Live Voice Agent, and Sessions. The backend URL comes from build-time
configuration instead of a text field.

## In scope

- Remove the `Backend` endpoint control (label, display, edit mode, refresh
  button) from the sidebar.
- Remove the `AUTH TOKEN` control from the sidebar.
- Remove the `Mode` label and the Agent/Team selector from the sidebar.
- Remove the `EntitySelector` (agent picker) and the `ModelDisplay` from the
  sidebar, so no model or provider name is rendered.
- Source `selectedEndpoint` from `NEXT_PUBLIC_AGENT_OS_URL` at build time,
  falling back to `http://localhost:7777` when unset.
- Purge the persisted `selectedEndpoint` from existing browsers, so a visitor
  who previously loaded this app is not pinned to a stale `localhost` value.
- Keep agent selection working via the existing auto-select path in
  `useChatActions.initialize()`.

## Out of scope

- **Cookie-based visitor sessions and the CORS allowlist** — build-plan item 17.
- **Vercel/Heroku deployment config and the F-07 rate-limit fix** — item 18.
- Removing `deepseek` from backend configuration, provider ordering, or
  guardrail comments. Item 16 removes the *display* of the model name only;
  `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL_ID` and the provider order in
  `backend/server.py` are live configuration and must not change.
- Deleting the `DeepseekLogo` icon or the `deepseek` entry in
  `lib/modelProvider.ts`. `getProviderIcon` becomes unused by the sidebar but
  the icon registry is shared; leave it.
- Adding authentication. See "Security note" below.
- Changing `mode`, `agents`, `teams` or `authToken` in the store. Their
  consumers outside the sidebar keep working unchanged.

## Security note (not a change in this feature)

`NEXT_PUBLIC_OS_SECURITY_KEY` is inlined into the client bundle by Next.js and
is therefore already public to every visitor. Repository evidence shows
`backend/server.py` has no `HTTPBearer`, no auth `Depends`, and no bearer
validation on any route: the token is sent as an `Authorization` header by
`useAIStreamHandler`, `useSessionLoader`, `useChatActions` and `SessionItem`,
but nothing on the backend reads it.

Removing the sidebar field therefore removes a control that never protected
anything. It does not weaken any existing boundary, and it does not add one.
Backend authorization is a separate decision, not part of this feature.

## Build loop

`workflow.stepReview` is `feature`: build all steps, then present one review
packet. `workflow.checkpointCommits` is `disabled`: make no commits. `/complete`
creates the single work commit.

Run `npm run typecheck` as the narrow check while iterating, and the full
frontend gate once at the end.

## Build steps

- [x] **Step 1 — Source the endpoint from build-time config and purge the stale
      persisted value.**
      In `frontend/src/store.ts`, set the `selectedEndpoint` initial value from
      `process.env.NEXT_PUBLIC_AGENT_OS_URL || 'http://localhost:7777'`.
      Bump the persist `name` from `endpoint-storage` to a new key (for example
      `voice-agent-storage`) so browsers holding a stale `endpoint-storage`
      value fall back to the configured default rather than a dead
      `http://localhost:7777`. Remove `selectedEndpoint` from `partialize` so
      the endpoint is never persisted again and always comes from config.
      Add `NEXT_PUBLIC_AGENT_OS_URL` to `.env.example` with a comment noting it
      is inlined at build time and must be set in Vercel before the build.
      **Done when:** `npm run typecheck` passes; with
      `NEXT_PUBLIC_AGENT_OS_URL` unset the app still reaches
      `http://localhost:7777`; and after loading the app, `localStorage` holds
      no `selectedEndpoint` under the new key.

- [x] **Step 2 — Remove the four sidebar controls.**
      In `frontend/src/components/chat/Sidebar/Sidebar.tsx`: delete the
      `Endpoint` component and its render, the `<AuthToken />` render, the
      `Mode` label block, `<ModeSelector />`, `<EntitySelector />`, and the
      `ModelDisplay` component and its render. Remove the now-unused
      `hasEnvToken`/`envToken` props from `Sidebar`, and the imports that become
      unused (`getProviderIcon`, `ModeSelector`, `EntitySelector`, `AuthToken`,
      `isValidUrl`, `toast`, `truncateText`, `useQueryState` and `motion`
      helpers only if genuinely unreferenced after the deletions).
      Keep the `isEndpointActive` guard around `<Sessions />` and keep the
      `isEndpointLoading` skeleton path if it still guards Sessions; if the
      skeleton only guarded the removed selectors, delete it too.
      In `frontend/src/app/page.tsx`, drop the `hasEnvToken`/`envToken`
      computation and pass no props to `<Sidebar />`.
      Delete `AuthToken.tsx`, `ModeSelector.tsx` and `EntitySelector.tsx` only
      if nothing else imports them; otherwise leave the files and remove only
      the sidebar usage. Update `Sidebar/index.ts` if it re-exports a deleted
      file.
      **Done when:** `npm run typecheck` and `npm run lint` pass with no unused
      imports or unused-variable warnings; the sidebar renders only the header,
      New Chat, Live Voice Agent and Sessions; and no endpoint, token, mode,
      agent name or model name appears anywhere in the sidebar.

- [x] **Step 3 — Confirm chat, sessions and voice still work end to end.**
      No new code is expected in this step; it exists to catch a regression
      from Step 2. `useChatActions.initialize()` auto-selects the first agent
      when no `?agent=` query param is present, and `backend/server.py`
      registers `agents=[text_agent, voice_agent]` with `text_agent` first, so
      the chat must land on `text_agent` with no selector present. Fix any
      regression found here inside this step.
      **Done when:** with the backend running, a fresh load with no query
      params sends a message and receives a streamed reply; the Sessions list
      populates and an earlier session reloads with its messages; the Live
      Voice Agent modal opens and connects; and the browser console shows no
      new errors. Record the evidence in the review packet.

## Step 3 evidence (user browser session, 2026-09-20)

Verified live by the user with `npm run dev:all`:

- Sidebar renders only the header, New Chat, Live Voice Agent and Sessions. No
  endpoint, auth token, mode, agent name or model name.
- A fresh load with no query params streamed a knowledge-base answer about
  Gichogu's background, confirming `initialize()` still auto-selects
  `text_agent` with no `EntitySelector` present.
- The Live Voice Agent modal opened, connected, and held a spoken conversation.
- `get_booking_link` fired in voice mode and the booking card rendered.
- No new console errors reported.

One pre-existing defect was surfaced by this session and recorded as **F-08
[P2]**: a voice booking mounts two `BookingCard`s from one payload (modal turn
plus chat mirror) and Cal's `inline` call is a global singleton, so the losing
card times out and shows "The calendar could not load here". It is a feature 15
defect in `BookingCard.tsx` / `AssemblyAIVoiceModal.tsx`, untouched by this
feature, and is left for its own `/fix` rather than folded in here. The fallback
link is always correct, so booking is never blocked.

## Files / areas

| Area | Path |
|---|---|
| Sidebar controls | `frontend/src/components/chat/Sidebar/Sidebar.tsx` |
| Deleted/unused components | `frontend/src/components/chat/Sidebar/{AuthToken,ModeSelector,EntitySelector}.tsx` |
| Sidebar exports | `frontend/src/components/chat/Sidebar/index.ts` |
| Endpoint config + persistence | `frontend/src/store.ts` |
| Sidebar props | `frontend/src/app/page.tsx` |
| Env documentation | `.env.example` |

**Do not change:** `backend/`, `frontend/src/api/`, `useAIStreamHandler.tsx`,
`useSessionLoader.tsx`, `useChatActions.ts`, `Sessions/`, or
`frontend/src/lib/modelProvider.ts`.

## Data / contracts

- **`NEXT_PUBLIC_AGENT_OS_URL`** — string, absolute origin with scheme and no
  trailing slash (for example `https://example-backend.herokuapp.com`). Read
  via `process.env` at build time, so it must be present in the Vercel project
  before the build runs; changing it requires a rebuild, not a restart. When
  unset or empty, the value is exactly `http://localhost:7777`.
- **Persist key change** — the zustand persist `name` changes, which
  intentionally abandons the old `endpoint-storage` entry. The old key is left
  in visitors' browsers as an orphan; this is acceptable and must not be
  "cleaned up" by reading it, because reading it back would reintroduce the
  stale endpoint this step exists to discard.
- **`authToken`** stays in the store with its `''` default. All four consumers
  keep sending it; `useAIStreamHandler.tsx:167` already guards with
  `if (authToken)`, so an empty token sends no `Authorization` header.
- **`mode`** stays in the store at its `'agent'` default. `EntitySelector`,
  `Sessions.tsx:99` and `useAIStreamHandler.tsx:146` still branch on it; with
  the selector gone it simply never changes from `'agent'`.

## Testing

No unit test runner is configured on the frontend, so verification is manual
plus the static gate. Do not claim a test run that cannot happen.

```
npm run typecheck
cd frontend && npm run lint
cd frontend && npx prettier --check <touched files>
cd frontend && npm run build
```

`npm run validate` is known broken independently of this work (it shells out to
`pnpm`, which is not installed). Run the steps individually via `npm`.

Browser verification is Step 3's `Done when`. `verification.uiEvidence` is
`when-available`; this feature is entirely visual, so browser evidence is
expected rather than optional. If the dev server cannot be started, stop and ask
rather than marking Step 3 done on build output alone.

## Notes for the AI

- `getProviderIcon` (`lib/modelProvider.ts`) becomes unreferenced by the
  sidebar. Leave the module and the `deepseek` entry alone — the icon registry
  is shared and deleting entries is out of scope.
- The sidebar has two `NewChatButton` definitions in play: a local one in
  `Sidebar.tsx:41` and a separate `Sidebar/NewChatButton.tsx`. Only the local
  one is rendered. Do not "fix" this here.
- `Sidebar.tsx:262` computes `activeAgentName` from `agents` and passes it to
  `VoiceModal`. `agents` is still populated by `initialize()`, so this keeps
  working with the selector removed. Keep it and its `'Clyde'` fallback.
- Removing `<EntitySelector />` does not break agent selection: `initialize()`
  auto-selects `agents[0]` and writes `?agent=`, and the backend registers
  `text_agent` first for exactly this reason (`server.py:1114-1117`).
- Coding standards: backend calls go through `src/api/` — this feature adds no
  new calls. Keep `SCREAMING_SNAKE_CASE` for the new env constant if one is
  introduced.
- The `isEndpointActive` state still gates `<Sessions />` and is still set by
  `initialize()`. Do not remove the state itself.
