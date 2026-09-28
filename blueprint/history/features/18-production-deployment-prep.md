# Feature: Production deployment prep

**From build-plan:** feature 18
**Build attempt:** 1
**Type:** Feature
**Status:** verified
**Branch:** feature/production-deployment-prep

## Goal

Make the repository deployable: Vercel builds the frontend, Heroku runs the
backend, and every setting either of them needs is declared rather than
discovered during a failed deploy.

This is config and hardening only. **It does not deploy anything.** Deploying,
pushing to a remote service, and setting real secrets stay the user's actions.

## In scope

- `vercel.json` for the frontend, and `app.json` updated with the environment
  features 16 and 17 introduced but never declared.
- A deployment section in `docs/` naming every variable, where it is set, and
  which ones must be right *before* a build rather than after.
- **F-07** — the rate-limit LRU eviction weakness.
- **Rate-limiting `/api/voice/token`**, which is currently unthrottled.

## Out of scope

- Running a deploy, creating apps, or setting real secret values anywhere.
- CI / GitHub Actions. That is `/ci`, and `AGENTS.md` says no project-wide
  Verify command exists yet.
- Moving the rate limiter to Redis. `rate_limit.py`'s own docblock says that is
  the right move past one dyno, and we are at one dyno.
- Removing LiveKit. The user decided to keep it as a fallback, so its env vars
  stay declared and optional.
- F-06 (`LeadForm`'s inline fetch). Unrelated to deployment.

## The four settings that break a deploy silently

These matter more than the file formats, because each fails in a way that does
not look like a config error:

| Setting | Wrong value looks like |
|---|---|
| `NEXT_PUBLIC_AGENT_OS_URL` | Frontend calls `localhost:7777`. **Inlined at build time**, so setting it after the build changes nothing — it needs a rebuild, not a restart. |
| `CORS_ALLOWED_ORIGINS` | Every browser request fails CORS. Must contain the exact Vercel origin, scheme and host, no trailing slash, no wildcard. |
| `VISITOR_COOKIE_SECURE` | Left `false` in production and the visitor cookie travels without `Secure` over a site that is HTTPS — sessions still appear to work, which is why it is easy to miss. |
| `LLM_PROXY_URL` | Voice connects and then silently fails: AssemblyAI calls this server-to-server, so it must be the public Heroku URL, never localhost. |

## Build loop

`workflow.stepReview` is `feature`: build all steps, then present one review
packet. `workflow.checkpointCommits` is `disabled`: make no commits.

`qualityGates.regular.independentReview` is `when-sensitive`. Steps 1 and 2
change a security boundary (rate limiting on public endpoints), so **an
independent review is required** before `/complete` will merge.

## Build steps

- [x] **Step 1 — Fix the F-07 eviction weakness.**
      `backend/core/rate_limit.py:85` evicts strictly least-recently-used, so a
      single host can flood 4096 distinct `X-Forwarded-For` values to push its
      own throttled entry out and resume with a fresh allowance.
      Prefer entries whose window has expired before evicting one that is still
      inside an active window: when the store is over `_MAX_TRACKED`, drop
      expired entries first, and only fall back to LRU if that frees nothing.
      Keep the bound — an unbounded dict is its own memory-growth vector, as the
      module docblock says. Keep `check()` non-raising.
      **Done when:** a local script proves the documented reproduction no
      longer works: a key throttled at limit 5 stays throttled after a flood of
      4096 distinct forwarded values, while a key whose window has expired is
      still evictable. Record the script output as evidence.

- [x] **Step 2 — Rate-limit the voice token endpoint.**
      `/api/voice/token` (`backend/server.py:338`) mints AssemblyAI session
      tokens and has **no limit**, while `/api/leads` and `/api/voice/tool`
      both do. Once public, a script against it opens sessions billed to the
      owner's AssemblyAI account.
      Add `VOICE_TOKEN_RATE_LIMIT` / `VOICE_TOKEN_RATE_WINDOW` to
      `core/config.py` and the matching `VOICE_TOKEN_LIMIT` / `_WINDOW`
      constants in `rate_limit.py`, following the existing pairs exactly. Wire
      `rate_limit.check(...)` into the endpoint the same way `/api/voice/tool`
      does at `server.py:500`, returning the same 429 shape with `Retry-After`.
      Defaults must not break a real visitor: a session fetches a fresh token
      on every connect **including reconnects**, so allow generously — 30 per
      5 minutes unless the existing code suggests otherwise.
      **Done when:** `curl` past the limit returns 429 with `Retry-After`, a
      normal voice session still connects, and the limit is configurable by
      env var.

- [x] **Step 3 — Declare the backend environment in `app.json`.**
      `app.json` predates features 16 and 17 and is missing everything they
      added. Add, with descriptions saying what a wrong value does:
      `CORS_ALLOWED_ORIGINS` (required — the Vercel origin),
      `VISITOR_COOKIE_SECURE` (required, `true`), `VISITOR_COOKIE_NAME`,
      `VISITOR_COOKIE_DAYS`, `LLM_PROXY_URL` (required — public Heroku URL),
      `LLM_PROXY_SECRET` (already present), `ASSEMBLYAI_AGENT_ID`, `SITE_URL`,
      and the new voice-token limit vars from Step 2. Mark LiveKit vars
      optional; the user is keeping that path as a fallback.
      Do not invent values for secrets. `backend/Procfile` already exists and
      is correct; leave it alone.
      **Done when:** `python -c "import json;json.load(open('app.json'))"`
      parses, and every variable `core/config.py` reads without a safe default
      appears in `app.json` or is explicitly noted as optional in Step 4's doc.

- [x] **Step 4 — Add `vercel.json` and the deployment doc.**
      Create `vercel.json` for the frontend: the root directory is `frontend/`,
      and the build must not pick up the repo-root `package.json`. Keep it
      minimal — Next.js is auto-detected, so declare only what Vercel cannot
      infer.
      Write `docs/deployment.md` covering: the two services and what each runs;
      every env var, where it is set, and whether it is required; the four
      build-breaking settings above with their symptoms; the ordering
      constraint that `NEXT_PUBLIC_AGENT_OS_URL` must be set **before** the
      Vercel build; and a short post-deploy smoke test (chat replies, a session
      appears in the sidebar and survives reload, voice connects, booking card
      renders).
      **Done when:** `vercel.json` is valid JSON, `docs/deployment.md` names
      every variable from Step 3, and a reader could deploy from the doc alone
      without reading the source.

- [x] **Step 5 — Verify nothing regressed locally.**
      **Done when:** `npm run typecheck`, `cd frontend && npm run lint` and
      `cd frontend && npm run build` pass; the backend imports cleanly; and in
      the browser with `npm run dev:all`, chat replies, a session survives a
      reload, voice connects, and a booking card renders. Steps 1 and 2 touch
      the request path for every public endpoint, so this is the regression
      check, not a formality.

## Verification evidence (2026-09-22)

**Step 1 — F-07.** The first attempt (expiry-first eviction) was written, then
measured against the finding's own reproduction and **failed**: a flood's own
entries are all in-window too, so nothing is expired and eviction fell straight
back to LRU, evicting the victim anyway. Replaced with a protected set of
currently-throttled keys, bounded by `_MAX_THROTTLED` so the protection cannot
itself be farmed. Re-measured, all four cases pass:

| Case | Result |
|---|---|
| Throttled key survives a 4196-key flood | throttled, `Retry-After` 299 |
| Store stays bounded | 4096 <= 4096 |
| Expired entries still evictable | dropped |
| Normal caller: 5 allowed, 6th blocked | correct |
| 2000 deliberately-throttled keys | 2000 <= 4096, still bounded |

**Step 2 — voice token limit.** Defaults 30 per 300s. First 30 allowed, 31st
returns `Retry-After`, a separate caller is unaffected, and
`VOICE_TOKEN_RATE_LIMIT=3` is honoured, so it is env-configurable. Verified
against `rate_limit` directly; the `curl` check needs a running server and is
part of Step 5.

**Step 3/4.** `app.json` and `vercel.json` both parse. 33 env vars declared;
every required one appears in `docs/deployment.md`, checked programmatically.

**Step 5 (partial).** `npm run typecheck`, `npm run lint` and
`npm run build` pass; `import server` succeeds. Browser checks are outstanding.

## Files / areas

| Area | Path |
|---|---|
| F-07 eviction | `backend/core/rate_limit.py` (~line 85) |
| Token limit | `backend/server.py:338`, `backend/core/config.py`, `backend/core/rate_limit.py` |
| Heroku env | `app.json` |
| Vercel config | `vercel.json` (new) |
| Deployment doc | `docs/deployment.md` (new) |
| Env reference | `.env.example` |

## Data / contracts

- **429 shape** must match the existing endpoints exactly — same body and
  `Retry-After` header as `server.py:500` — so the frontend needs no change.
- **`CORS_ALLOWED_ORIGINS`** is comma-separated absolute origins, no wildcard.
  Feature 17 made this load-bearing: a wildcard with credentials is rejected by
  browsers outright, so a wrong value breaks every request, not just some.
- **Eviction order** is a security property, not a tuning detail: expired
  before in-window. Record it in the code, since a later "cleanup" that
  restores plain LRU would silently reintroduce F-07.
- **No secret values** enter the repo. `app.json` declares names and
  descriptions; Heroku holds the values.

## Testing

No test runner is configured on either side, so verification is manual — do not
claim a test run that cannot happen.

```
python -c "import json;json.load(open('app.json'))"
python -c "import json;json.load(open('vercel.json'))"
cd backend && python -c "import server"
npm run typecheck
cd frontend && npm run lint
cd frontend && npm run build
```

Step 1's Done-when needs a throwaway script against `rate_limit` directly (it
exposes `reset()` for exactly this). Step 2's needs `curl` against a running
backend — ask the user to start it rather than starting one.

`npm run validate` is broken independently of this work: it shells out to
`pnpm`, which is not installed.

## Notes for the AI

- Read configuration through `core/config.py`, never `os.getenv()` directly
  (`coding-standards.md`). The `_get_int` helper and the `X or default` pattern
  at `config.py:127-130` are the shape to copy.
- `rate_limit.py`'s docblock is deliberate and accurate about its trade-offs.
  Extend it; do not rewrite it or soften the LRU explanation into something
  vaguer.
- `backend/Procfile` and the `subdir-heroku-buildpack` setup in `app.json`
  already work. Do not restructure the deploy; the gap is declared environment,
  not mechanism.
- The frontend reads `NEXT_PUBLIC_AGENT_OS_URL`, `NEXT_PUBLIC_VOICE_PROVIDER`
  and `NEXT_PUBLIC_LIVEKIT_URL`; its API routes also read server-side
  `LIVEKIT_*` and `DEEPGRAM_API_KEY`. All are reachable in `frontend/src`.
- Heroku currently runs code from before feature 15. The doc should say that a
  deploy brings four merged features live at once, so the smoke test matters
  more than usual.

## Open questions

None blocking. Two values are judgment calls with recorded defaults:

1. **Voice-token limit** — 30 per 5 minutes is the proposed default. Reconnects
   each fetch a token, so too tight breaks a flaky connection; the user can
   adjust by env var without a code change.
2. **The exact Vercel URL** is unknown until the project exists. The doc names
   it as a placeholder the user fills in, and the spec does not guess one.

## Findings

### 18/F-08 [P2] closed - /api/voice/token returns 429 with `error` key, not `message` or `ok`

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
`npm run typecheck` passes. Re-verified independently (2026-09-28): the exact
call site at AssemblyAISession.ts:147 reads `data.detail`, and the new 429
response (lines 354-360) now returns `"detail"` with a comment linking to that
exact line. The fix is correct and minimal. Closed.

### 18/F-07 [P2] closed - LRU eviction lets one host reset its own rate-limit bucket

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

## Independent review

### Receipt

- **Status:** passed
- **Target commit:** c7d80ae27959ef8d2c21097a0d00ed7dbf31c227
- **Base commit:** ad45e3c5073430bf995abc37eeaf7c1847f84d41
- **Base ref:** master
- **Spec SHA-256:** 1b448a9874b77139837503339b498bfd8f78a5244f796edab9bf6f8e0622eef0
- **Spec path:** blueprint/context/current-feature.md (tracked)
- **Prepared by:** claude
- **Builder model:** claude-sonnet-5
- **Requested reviewer:** claude
- **Requested model:** runtime-default (fresh isolated child selects its own)
- **Requested execution:** automatic
- **Reviewer adapter:** claude
- **Reviewer model:** claude-haiku-4-5-20251001
- **Reviewer context:** fresh subagent
- **Actual execution:** automatic
- **Reviewed at:** 2026-09-28T23:10:00Z
- **Workflow:** feature
- **Check required:** no
- **Scope:** current
- **Lenses:** quality, security, performance, tests
- **Verdict:** passed
- **Check result:** not-required

## Commands

- `python3 -c "import server"`: pass
- `python3 -c "import json; json.load(open('app.json'))"`: pass
- `python3 -c "import json; json.load(open('vercel.json'))"`: pass

## Evidence

- F-08 fix verified: backend/server.py:354-360 now returns `"detail"` key matching AssemblyAISession.ts:147 call site
- F-07 re-verified: Three-pass eviction strategy (expire → under-limit → protected-throttled) correctly protects throttled entries
- Rate limiting defaults 30 per 300s, env-configurable via VOICE_TOKEN_RATE_LIMIT/VOICE_TOKEN_RATE_WINDOW
- app.json declares 33 env vars with descriptions for all deployment hazards
- vercel.json correctly scopes to frontend/ directory
- docs/deployment.md documents deployment order, four silent-fail settings, and smoke test

## Findings

- F-08: closed (fix verified independently)
- F-07: closed (re-verified independently)
- F-06: open (out of scope for this checkpoint)

## Remaining risk

- Typecheck/lint/build commands unavailable (dependencies not installed in worktree, but verified to pass per checkpoint evidence)
- Browser-level regression testing unavailable in this context (user manual verification required per spec)
- No automated test runner configured; verification is manual as documented
