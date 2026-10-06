# Voice Agent - Project Overview

<!-- blueprint:source-hash aa82a170938b6249ddf872fc012beb916c498bd3552e791cb470a39db23e8cf0 -->

> A real-time voice and text AI assistant on Gichogu Macharia's personal
> website that answers questions about him, hands visitors to his Cal.com
> booking page, and captures leads.

## Problem

Visitors to gichogumacharia.tech need an always-available, accurate way to
learn about Gichogu's background, projects, and skills, and a low-friction path
to book a consultation or leave contact details, without a generic assistant
persona that could represent anyone.

## Users

- **Recruiters and prospective clients** - want accurate answers about
  Gichogu's experience and projects, and a way to book time with him.
- **General site visitors** - browsing, asking casual questions, may or may not
  convert to a lead.

No access tiers; every visitor is anonymous and gets the same assistant.

## Features

1. **Core agent identity & persona** - one shared identity across voice and
   text channels; speaks about Gichogu in the third person, warm and
   unperformative tone, channel-specific formatting (spoken vs. markdown).
2. **Text chat agent** - Agno `site-agent` served through AgentOS; markdown
   responses with knowledge citations.
3. **Real-time voice agent** *(headline feature)* - LiveKit WebRTC worker +
   Deepgram Nova-3 STT / Flux TTS bridge for live spoken conversation.
4. **RAG knowledge base** - curated bio/experience/FAQ/projects/skills content,
   chunked and embedded, retrieved by both agents so answers are grounded, not
   improvised.
5. **Session & memory persistence** - Postgres-backed history shared by both
   agents; degrades gracefully if the database is unreachable.
6. **Cal.com booking handoff** - hands visitors the public booking link rather
   than scheduling via API, to avoid double-booking and timezone errors.
7. **Lead capture & notification** - persists leads to Postgres; best-effort
   email notification to Gichogu.
8. **Gmail drafting via Composio** - scoped allowlist (`GMAIL_SCOPE`:
   notify/read/full) so the public-facing agent can draft but not send or
   delete mail by default.
9. **Web search fallback** - answers questions outside the knowledge base via
   DuckDuckGo/ddgs.
10. **MCP server** - exposes the same core tools to external MCP clients.
11. **Frontend chat UI** - Next.js chat interface: sessions, streaming
    responses, markdown rendering, multimedia messages.
12. **Frontend voice UI** - LiveKit voice modal, control bar, and audio
    visualizer.
13. **Feature-flag status endpoint** - `/api/info` reports which optional
    integrations (persistence, knowledge, booking, leads, gmail) are actually
    configured and live, so the frontend can degrade gracefully.
14. **Interactive tool rendering** - booking card and lead-capture form
    rendered from tool results in text chat.
15. **Booking card in voice mode** - booking card in the voice transcript so a
    visitor picks a slot instead of transcribing a spoken URL.
16. **Sidebar cleanup for public deployment** - Backend endpoint, Mode, auth
    token and model-name controls removed; backend URL from build-time config.
17. **Cookie-based visitor sessions** - opaque HttpOnly visitor cookie (5-day
    expiry) groups a visitor's sessions; CORS narrowed to an exact origin
    allowlist.
18. **Production deployment prep** - Vercel frontend and Heroku backend config,
    env review, `/api/leads` rate-limit hardening (`backend/core/rate_limit.py`).
19. **Mobile-optimized UI and usage** *(in progress)* - three sub-items:
    - 19a. Tailwind CSS v4.3 upgrade *(done)*.
    - 19b. Responsive chat layout *(done)*: sidebar drawer, 44px touch targets,
      safe areas, `dvh` heights, no sideways scroll from 360px.
    - 19c. Mobile voice and audio-reactive voice UI *(next)*: AssemblyAI voice
      modal as a full-screen sheet on phones; audio starts inside the tap (iOS
      Safari); detect a dropped socket or mic after screen lock or
      backgrounding and offer reconnect or end cleanly; error state with
      retry; canvas aura visualizer driven by the real mic and reply analysers,
      with a reduced-motion fallback.

## Data model

### Session / Memory (Agno `db`, Postgres)

- Agno-managed tables for chat/voice session history and agent memory, shared
  by the `site-agent` (text) and `voice-agent` (voice) agent instances.
- Run metrics (Agno-managed).

### Knowledge (pgvector, via Agno `Knowledge`)

- Vector-embedded chunks of `backend/content/*.md` (bio, experience, FAQ,
  projects, skills) plus GitHub repo READMEs (capped at `GITHUB_README_CHARS`).
- `EMBED_MODEL` = `BAAI/bge-base-en-v1.5`, `EMBED_DIMENSIONS` = 768 (must match
  the embedder - a mismatch silently creates a wrong-sized pgvector column).
- `CHUNK_SIZE` = 1200 chars, `CHUNK_OVERLAP` = 150.
- Retrieval: top `KNOWLEDGE_TOP_K` = 4 chunks per query.

### Lead

- Captured contact details from `core/tools/leads.py`, written to Postgres as
  the source of truth. Notification email to `LEAD_NOTIFY_EMAIL` is
  best-effort only; a visitor's lead is never lost if SMTP fails.

> Lock: knowledge base embedding dimensions and chunk size are tuned to the
> current embedder and content size - changing either requires re-ingesting
> all content (`backend/scripts/ingest.py`).

## Tech stack

- **FastAPI + Agno AgentOS** - backend HTTP API and text agent (`backend/server.py`)
- **LiveKit Agents (WebRTC)** - real-time voice transport (`backend/livekit_worker.py`)
- **Deepgram** - Nova-3 STT and Flux TTS
- **LLM** - Bedrock (DeepSeek v3.2) first if configured, else xAI Grok, else
  OpenAI `gpt-4o-mini` fallback
- **Postgres + pgvector** - sessions, memory, leads, and knowledge vectors
- **DeepInfra** - embeddings (`bge-base-en-v1.5`)
- **Cal.com** - booking link handoff
- **Composio** - scoped Gmail tool access
- **DuckDuckGo / ddgs** - web search fallback
- **FastMCP** - MCP server wrapping the same core tools
- **Next.js 15 + React 18 + Tailwind + Radix UI + `@livekit/components-react`** -
  frontend chat and voice UI; Tailwind moves to v4 in feature 19
- **uv** (backend) / **pnpm** (frontend, per the plan) - package management

## Monetization

Not a direct-revenue product. Its value is generating consulting leads and
booked consultations for Gichogu.

> TODO: confirm whether this is intentionally "not in v1" or whether any future
> monetization is planned.

## UI/UX

Warm, relaxed, quietly confident tone; genuinely interested, not performative
or hype-driven (no exclamation-heavy "amazing/fantastic" language). Speaks
about Gichogu in the third person and identifies itself as his AI assistant
when asked. Voice responses: no markdown, short spoken-friendly sentences,
spoken date formats. Text responses: full markdown with knowledge citations.

- **Mobile:** must work well on mobile browsers (iOS Safari 16.4+, Android
  Chrome) at phone widths from 360px, for text chat and voice. Styling is
  Tailwind CSS v4.
- `/` - main site page hosting the chat interface and voice modal entry point
  (single-page app; no other routes identified in the frontend survey)

## Deployment

- Frontend on Vercel (`vercel.json`), backend on Heroku (`app.json`), per
  feature 18. `SITE_URL` defaults to `https://gichogumacharia.tech`.
- `/api/leads` is rate limited (`backend/core/rate_limit.py`).

> TODO: build/start commands per service, env vars, database provisioning, and
> health checks are not recorded in the plans. Run `/release` to define them.

## Open questions

- Monetization intent (see above) - confirm "not in v1" is correct.
- Deployment target and process (see above) - undocumented.
