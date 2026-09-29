# Deployment

Two services, deployed separately:

| Service | Host | Runs |
|---|---|---|
| `frontend/` | Vercel | Next.js chat UI |
| `backend/` | Heroku | FastAPI + Agno AgentOS (`backend/Procfile`) |

Heroku builds only `backend/` via the `subdir-heroku-buildpack` and
`PROJECT_PATH=backend` in `app.json`. The repo root holds a `package.json` for
the frontend, which Heroku would otherwise detect instead.

## Four settings that fail quietly

These are worth checking twice, because a wrong value does not look like a
config error:

| Setting | Where | Wrong value looks like |
|---|---|---|
| `NEXT_PUBLIC_AGENT_OS_URL` | Vercel | Frontend calls `localhost:7777`. **Inlined at build time** — setting it afterwards changes nothing until you rebuild. |
| `CORS_ALLOWED_ORIGINS` | Heroku | Every browser request fails CORS. Needs the exact Vercel origin; a wildcard breaks credentials entirely. |
| `VISITOR_COOKIE_SECURE` | Heroku | Left `false` and the session cookie travels without `Secure` over HTTPS. Sessions still appear to work. |
| `LLM_PROXY_URL` | Heroku | Voice connects, then silently fails. AssemblyAI calls it server-to-server, so it can never be localhost. |

## Backend (Heroku)

Every variable is declared in `app.json` with a description. Required:

- `ASSEMBLYAI_API_KEY` — Voice Agent API. Never reaches the browser.
- `ASSEMBLYAI_AGENT_ID` — the stored agent, from `scripts/provision_agent.py`.
- `LLM_PROXY_URL` — this app's public `/api/llm` URL.
- `LLM_PROXY_SECRET` — shared secret guarding that public proxy.
- `CORS_ALLOWED_ORIGINS` — the Vercel origin(s).
- `VISITOR_COOKIE_SECURE` — `true`.
- `DATABASE_URL` — Postgres with pgvector; without it sessions do not persist.

Optional, with working defaults: the cookie name/expiry, all four rate-limit
pairs, `SITE_URL`, the alternate model providers, the lead-notification SMTP
settings, and the LiveKit variables (`LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`; only used when the frontend runs
`NEXT_PUBLIC_VOICE_PROVIDER=livekit`). LiveKit tokens are minted here, behind
the rate limiter, so these belong on Heroku only.

## Frontend (Vercel)

Project settings (there is no `vercel.json`; the dashboard is the config):

- **Root Directory:** `frontend`.
- **Install Command:** override to `npm install`. `frontend/` also holds a
  `pnpm-lock.yaml`, and without the override Vercel may pick pnpm.
- **Build Command / Output Directory:** leave on the Next.js defaults.

Environment variables. `NEXT_PUBLIC_*` values are baked in at build time, so
redeploy after changing them:

- `NEXT_PUBLIC_AGENT_OS_URL` — the Heroku app URL, no trailing slash. The only
  required variable.
- `NEXT_PUBLIC_VOICE_PROVIDER` — omit for AssemblyAI (the default).
- Set no secrets here (`LIVEKIT_*`, `DEEPGRAM_API_KEY`, and so on). The
  frontend calls the backend for everything and holds no keys.

## Order

1. Deploy the backend and note its URL.
2. Set `LLM_PROXY_URL` on Heroku to that URL + `/api/llm`.
3. Create the Vercel project and set `NEXT_PUBLIC_AGENT_OS_URL` **before** the
   first build.
4. Deploy the frontend and note its URL.
5. Set `CORS_ALLOWED_ORIGINS` on Heroku to that URL. The backend restarts; no
   frontend rebuild is needed for this one.

Changing `NEXT_PUBLIC_AGENT_OS_URL` later requires a **rebuild**, not a
restart.

## Smoke test

The currently deployed backend predates features 15-18, so the first deploy
brings several merged changes live at once. Check all of it:

1. **Chat** — send a message, get a reply.
2. **Sessions** — the conversation appears in the sidebar, survives a reload,
   and a different private window sees none of it.
3. **Voice** — the modal connects and the agent speaks.
4. **Booking** — ask to book; the card renders a calendar, and in voice the
   modal card shows it while the mirrored chat card stays link-only.
5. **Console** — no CORS errors.

If step 2 shows other visitors' sessions, `VISITOR_COOKIE_SECURE` or
`CORS_ALLOWED_ORIGINS` is wrong. If step 3 connects but the agent never
answers, check `LLM_PROXY_URL`.

## Not set up

No CI. `frontend/.github/workflows/validate.yml` runs the frontend's own
lint/format/typecheck only. Run `/ci` to define a project-wide Verify command
and matching GitHub check.
