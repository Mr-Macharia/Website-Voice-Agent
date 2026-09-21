# Feature: Cookie-based visitor sessions

**From build-plan:** feature 17
**Build attempt:** 1
**Type:** Feature
**Status:** verified
**Branch:** feature/cookie-based-visitor-sessions

## Goal

A visitor's chat history should survive a reload and follow them across tabs,
without asking anyone to sign in. An opaque HttpOnly cookie identifies the
browser; sessions are stamped with that id and only that visitor's sessions come
back.

Today nothing identifies a visitor. `GET /sessions` returns **every session in
the database to anyone who asks** — the sidebar list a visitor sees is other
people's conversations. That is the real defect this feature closes, and it is
why the CORS change travels with it rather than after it.

## In scope

- An opaque `visitor_id` cookie: HttpOnly, Secure, SameSite=None, Path=/,
  5-day Max-Age, set by the backend when absent.
- Middleware that reads the cookie and puts its value on `request.state` so
  Agno's existing user-scope machinery enforces it server-side.
- Stamping agent runs with the visitor id so new sessions are owned.
- CORS narrowed from `allow_origins=["*"]` to an exact allowlist from config.
- The frontend sending credentials on backend calls.

## Out of scope

- **Login, accounts, or any durable identity.** A cookie is a browser, not a
  person. Clearing cookies or opening a private window is a new visitor, and
  that is the intended behaviour, not a bug to work around.
- **Migrating existing sessions.** Rows already in Postgres have no `user_id`
  and will stop appearing in the sidebar. See Data / contracts.
- **Rate limiting by cookie.** A cookie is client-controlled; an attacker drops
  or rotates it. `core/rate_limit.py` stays keyed on IP. F-07 is item 18.
- **The voice WebSocket and `/api/llm/*`.** AssemblyAI calls the proxy
  server-to-server with no browser and no cookie.
- Vercel/Heroku deployment config — item 18.

## Security contract

- **The cookie value is the only trusted source of visitor identity.** A
  `user_id` query parameter from the client must never widen what a caller can
  read. Agno's `get_scoped_user_id` returns `request.state.user_id` whenever
  `request.state.user_isolation_enabled` is true, and that return value
  overrides the query param inside `resolve_db_and_scope`. The middleware must
  set both fields, so scoping is enforced by the router, not by us filtering.
- **The value is server-generated and opaque**: `secrets.token_urlsafe(32)`.
  Never derive it from an IP, user agent, or anything a visitor supplies, and
  never accept a client-proposed id.
- **Reject a malformed cookie** rather than trusting it: if the value is not
  the exact expected shape, treat the request as having no cookie and mint a
  fresh one. A cookie is attacker-controlled input.
- **`allow_credentials=True` with `allow_origins=["*"]` is already broken** —
  browsers refuse to send credentials to a wildcard origin, so cookies cannot
  work until the allowlist lands. The two halves of this feature are not
  separable.
- The cookie carries no personal data and is not a tracking identifier beyond
  grouping one browser's own chats.

## Build loop

`workflow.stepReview` is `feature`: build all steps, then present one review
packet. `workflow.checkpointCommits` is `disabled`: make no commits.

`qualityGates.regular.independentReview` is `when-sensitive`. This feature is a
security boundary change, so **an independent review is required** before
`/complete` will merge it.

## Build steps

- [x] **Step 1 — Config: the CORS allowlist and cookie settings.**
      In `backend/core/config.py`, add `CORS_ALLOWED_ORIGINS` (comma-separated,
      parsed to a list, default `http://localhost:3000`), `VISITOR_COOKIE_NAME`
      (default `visitor_id`), `VISITOR_COOKIE_DAYS` (default 5), and
      `VISITOR_COOKIE_SECURE` (default true; false only for local http).
      Follow the existing `_get` / `_get_int` helpers and
      `SCREAMING_SNAKE_CASE`. Document each in `.env.example`.
      **Done when:** `python -c "from core import config; print(config.CORS_ALLOWED_ORIGINS)"`
      from `backend/` prints the parsed list, and an unset env yields the
      documented default rather than an empty list.

- [x] **Step 2 — Replace the wildcard CORS with the allowlist.**
      In `backend/server.py`, replace `allow_origins=["*"]` with
      `allow_origins=core_config.CORS_ALLOWED_ORIGINS`, keeping
      `allow_credentials=True`. Narrow `allow_methods` and `allow_headers` only
      if every current caller still works; otherwise leave them and say so.
      **Done when:** the backend starts; a request with
      `Origin: http://localhost:3000` returns that exact origin in
      `access-control-allow-origin` with `access-control-allow-credentials:
      true`; and a request with an unlisted Origin returns no
      `access-control-allow-origin` header. Verify with `curl -i -H "Origin: ..."`.

- [x] **Step 3 — Issue and read the visitor cookie.**
      Add `backend/core/visitor.py`: a `new_visitor_id()` using
      `secrets.token_urlsafe(32)`, and a strict `is_valid_visitor_id(value)`
      (expected length and URL-safe base64 alphabet only).
      Add an HTTP middleware on `base_app` that reads the cookie, validates it,
      falls back to minting a new one, sets `request.state.user_id` and
      `request.state.user_isolation_enabled = True`, and writes the cookie on
      the response when it was absent or invalid. It must skip WebSocket scopes
      and the server-to-server routes named in Out of scope.
      **Done when:** a first `curl -i http://localhost:7777/api/info` returns a
      `set-cookie` with `HttpOnly`, `SameSite=None`, `Secure` and
      `Max-Age=432000`; a second request replaying that cookie returns **no**
      `set-cookie`; and a request sending a garbage cookie value gets a fresh
      one rather than reusing the garbage.

- [x] **Step 4 — Scope sessions to the visitor.**
      Confirm against the installed Agno (2.9.0) that setting
      `request.state.user_id` plus `request.state.user_isolation_enabled` is
      sufficient for `agno/os/middleware/user_scope.py:get_scoped_user_id` to
      return the visitor id, and that `GET /sessions` therefore filters by it.
      Stamp new runs with the same id so sessions are created owned — check how
      `resolve_run_user_id` (same module, line 135) obtains it for the run
      endpoints before choosing where to set it.
      If the installed version does not honour these fields on the run path,
      **stop and report** rather than filtering results ourselves in a wrapper:
      a client-supplied `user_id` that still reaches the DB unfiltered is the
      hole this step exists to close.
      **Done when:** with two different cookie values, each `GET /sessions`
      returns only the sessions created under that cookie, verified with two
      `curl` cookie jars against a running backend and a real chat message sent
      under each.

- [x] **Step 5 — Send credentials from the frontend.**
      Add `credentials: 'include'` to the backend `fetch` calls in
      `frontend/src/api/os.ts` and the streaming call in
      `frontend/src/hooks/useAIStreamHandler.tsx`. Per
      `coding-standards.md`, backend calls belong in `src/api/` — do not add a
      new inline fetch; extend the existing helpers.
      **Done when:** `npm run typecheck`, `npm run lint` and the frontend build
      pass, and in the browser Network tab the `/sessions` request carries the
      `visitor_id` cookie.

- [x] **Step 6 — Confirm the whole flow in the browser.**
      **Done when:** a fresh private window starts with an empty session list;
      sending a message creates a session that appears in the sidebar; a reload
      keeps it; a second tab shows the same list; a different private window
      shows **none** of the first window's sessions; the voice modal still
      connects and books; and the console shows no CORS errors. Record the
      evidence in the review packet.

## Verification evidence (curl, 2026-09-21)

Against a running backend on :7777.

**Step 2 — CORS.** `Origin: http://localhost:3000` returns
`access-control-allow-origin: http://localhost:3000` with
`access-control-allow-credentials: true`. `Origin: https://evil.example.com`
returns no `access-control-allow-origin` header.

**Step 3 — Cookie.** First request sets
`visitor_id=<43 chars>; HttpOnly; Max-Age=432000; Path=/; SameSite=none; Secure`.
Replaying that cookie returns no `set-cookie`. A request sending
`visitor_id=../../etc/passwd` receives a freshly minted value instead.

**Step 4 — Scoping.** A run posted with visitor A's cookie returned
`"user_id": "K6WQcNAgXul7..."` — the cookie value — so Agno stamps runs from
`request.state.user_id` on the run path, not only on reads. A then lists 1
session; a separate visitor B lists 0.

**Spoof test (not in the original plan, added because it is the actual
security claim):** B requesting
`/sessions?...&user_id=<A's id>` still returns 0 sessions. The cookie-derived
scope overrides the client's query parameter, which is the behaviour
`resolve_db_and_scope` documents. Enforcement is in the router, not in a filter
this feature applies afterwards.

Pre-existing sessions created before this feature return 0 rows for every
visitor, as predicted in Data / contracts.

**Step 6 — Browser (user, 2026-09-21).** Confirmed live: a fresh private window
starts with an empty session list, sending a message creates a session that
appears in the sidebar, a reload keeps it, a second tab shows the same list, a
separate private window sees none of the first window's sessions, the voice
modal still connects and books, and no CORS errors appear in the console.

## Files / areas

| Area | Path |
|---|---|
| Config + allowlist | `backend/core/config.py`, `.env.example` |
| CORS middleware | `backend/server.py` (~line 226) |
| Cookie helpers | `backend/core/visitor.py` (new) |
| Cookie middleware | `backend/server.py`, near `base_app` |
| Frontend credentials | `frontend/src/api/os.ts`, `frontend/src/hooks/useAIStreamHandler.tsx` |

## Data / contracts

- **`visitor_id` cookie** — `secrets.token_urlsafe(32)` (43 URL-safe base64
  characters). HttpOnly, Secure, SameSite=None, Path=/, Max-Age 432000 (5 days).
  Rolling renewal is **not** in scope: the cookie expires 5 days after it was
  issued, so a returning visitor on day 6 is a new visitor. Say so in the code
  comment rather than leaving it to be discovered.
- **`CORS_ALLOWED_ORIGINS`** — comma-separated absolute origins, scheme and
  host, no trailing slash, no wildcard. An empty or unset value falls back to
  `http://localhost:3000`, never to `*`.
- **Existing sessions have no `user_id`.** Once isolation is on they stop
  appearing for anyone. They are not deleted and remain in Postgres. This is
  acceptable — they are development chats — but it is a visible one-way change
  and must be stated in the review packet, not discovered after merge.
- **`SameSite=None` requires `Secure`**, which requires HTTPS. On plain
  `http://localhost` the browser will reject a `Secure` cookie, which is why
  `VISITOR_COOKIE_SECURE` exists. It defaults to true; local development sets
  it false. Production must never run with it false.

## Testing

No unit test runner is configured on either side, so verification is manual.
Do not claim a test run that cannot happen.

```
cd backend && python -c "from core import config; print(config.CORS_ALLOWED_ORIGINS)"
npm run typecheck
cd frontend && npm run lint
cd frontend && npm run build
```

`npm run validate` is broken independently of this work (it shells out to
`pnpm`, which is not installed). Prettier resolves its Tailwind plugin only when
run from `frontend/`.

Steps 2, 3 and 4 are verified with `curl` against a running backend; step 6 is
verified in the browser. `verification.uiEvidence` is `when-available`, and this
feature changes what a visitor sees in the sidebar, so browser evidence is
expected rather than optional.

## Notes for the AI

- Agno 2.9.0 is installed. The relevant machinery is
  `agno/os/middleware/user_scope.py`: `get_scoped_user_id` (line 79) reads
  `request.state.user_id`, `request.state.scopes` and
  `request.state.user_isolation_enabled`; `resolve_db_and_scope` (line 170)
  prefers that scoped id over the caller's `user_id` query param. Read these
  before writing the middleware — they are the enforcement point.
- Do not add a JWT. `get_scoped_user_id` reads `request.state`, which any
  middleware can populate.
- `base_app` already exists and `AgentOS(base_app=base_app)` wraps it, so a
  middleware added to `base_app` covers the AgentOS routes too. Confirm this
  during Step 3 rather than assuming it.
- Read configuration through `core/config.py`, never `os.getenv()` directly
  (`coding-standards.md`).
- The frontend currently sends **no** credentials anywhere; `credentials:
  'include'` is a new addition at every call site, not a change to an existing
  value.
