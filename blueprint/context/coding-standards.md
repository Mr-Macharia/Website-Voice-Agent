# Coding Standards

> Rewritten by `/adopt` to match the real stack: a Python/FastAPI/Agno backend
> plus a separate Next.js frontend, not the Next.js+Prisma default.

## Project Structure

Two independently runnable services in one repo:

- `backend/` - Python 3.13, `uv`-managed. FastAPI + Agno AgentOS serves the text
  agent and HTTP API (`server.py`); a separate LiveKit worker process serves the
  real-time voice agent (`livekit_worker.py`); a FastMCP server exposes the same
  tools to external MCP clients (`voice_mcp/`).
- `frontend/` - Next.js 15 App Router, pnpm-managed, the chat + voice UI.
- `backend/core/` is the shared implementation both the text agent, voice
  agent, and MCP server import from: `persona.py` (one identity, channel-specific
  formatting), `config.py` (every setting, feature-flag helpers), `knowledge.py`
  (RAG), `db.py` (Postgres), `guardrails.py`, and `tools/` (framework-agnostic
  async functions, wrapped per-framework by `core/adapters/`).
- `backend/content/` holds the curated markdown (`bio.md`, `experience.md`,
  `faq.md`, `projects.md`, `skills.md`) that `scripts/ingest.py` chunks and
  embeds into the knowledge base. This content is the grounding source; the
  agent must not improvise facts the retrieval doesn't return.

## Python (backend)

- Python 3.13, dependencies and env managed with `uv` (`backend/pyproject.toml`,
  `backend/uv.lock`) — use `uv run`, not a bare `python`/`pip`.
- `from __future__ import annotations` at the top of modules that use modern
  type hints (existing convention in `core/`).
- Tools in `core/tools/` are plain `async def` functions returning a string,
  with no `agno` or `livekit` imports — adapters in `core/adapters/` wrap them
  per framework. New tools should follow this pattern so voice, text, and MCP
  all get them for free.
- Every tool must be non-raising on the hot path: catch and return a speakable
  English failure string rather than letting an exception surface mid-conversation
  (see `core/tools/search.py`'s header comment for the convention).
- Every feature that depends on an optional external service (Postgres, Composio,
  Cal.com, SMTP) must degrade independently rather than crash the whole agent —
  follow the `*_available()` pattern in `core/config.py` and check it before
  wiring a feature in, not after.
- Read configuration from `core/config.py`, never `os.getenv()` directly in
  application code — it is the one place settings and their defaults live.
- Security-sensitive scopes (`GMAIL_SCOPE`, which tools are exposed to a
  public-facing agent) are deliberate allowlists, not conveniences. Widening one
  is a security decision and should be called out explicitly in review, not
  bundled into an unrelated change.

## TypeScript / Frontend

- Next.js 15 App Router, functional components, hooks for state and side
  effects.
- Strict TypeScript; avoid `any`.
- Tailwind CSS for styling; Radix UI primitives under `src/components/ui/`.
- Feature areas are organized by domain, not by type:
  `src/components/chat/`, `src/components/voice/` — follow this grouping for
  new UI rather than a flat `components/` folder.
- API calls to the backend go through `src/api/` (`os.ts`, `routes.ts`); don't
  inline fetch calls to backend endpoints elsewhere.

## Naming

- Python: `snake_case` for functions/variables, `PascalCase` for classes,
  `SCREAMING_SNAKE_CASE` for module-level constants (matches `core/config.py`).
- TypeScript: `PascalCase` components, `camelCase` functions/variables,
  `SCREAMING_SNAKE_CASE` constants.

## Error Handling

- Backend: never let a single missing integration take down the whole agent;
  return the degraded/disabled state and log a clear warning instead (see
  `server.py`'s startup DB connection handling).
- User-facing tool failures return a plain-English string the agent can speak
  or display, not a stack trace or raw exception message.

## Testing

No unit test runner is configured on either side (backend or frontend) as of
adoption. `backend/scripts/voice.py` is a manual single-turn CLI script for
exercising the voice pipeline by hand (`npm run test:voice`), not an automated
test — don't treat it as gating coverage.

Testing is opt-in at the project level. Adding a real runner (pytest for the
backend, Vitest for the frontend) is a deliberate step via `/tests`, which also
updates the Commands section of `AGENTS.md` — that command's presence is the
one signal that turns on the test gate for logic-bearing steps. Until then,
verify logic-bearing changes by running the affected script/endpoint directly
and by typechecking (`npm run typecheck` on the frontend).

**The opt-in switch is one signal: a `test` command in the Commands section of
`AGENTS.md`.** Declare one and tests become a gate for logic-bearing steps;
leave it out and the loop verifies logic with the evidence it already uses (run
it, a screenshot, the build).

## Browser Verification

For UI and integration behavior, prefer real evidence over reading the code and
assuming it works.

- Browser automation is separately opt-in through `/browser-tests`.
- Without a declared `Browser tests` command, verify chat/voice UI changes with
  the dev server, a screenshot, or manual exercise of the flow (especially
  anything touching the LiveKit voice modal or the streaming chat UI) rather
  than reading the component and assuming it renders correctly.

## Code Quality

- No commented-out code unless specified.
- No unused imports or variables.
- Keep functions focused; the existing codebase favors small, single-purpose
  async functions over large ones.

## Comments

Write code that explains itself; comment only what the code cannot say.
Over-commenting is a common AI tell, so resist it.

- Comment the **why**, not the **what**. Delete any comment that restates the code.
- No banner/header blocks, section dividers, or step-by-step narration of obvious
  code, with one accepted exception already in this codebase: short `# ---
  Section ---` dividers inside `core/config.py` and `server.py` grouping related
  settings/routes. Match that existing style there; don't introduce new banner
  comments elsewhere.
- A comment earns its place only when it captures something the code can't: a
  non-obvious decision, a gotcha or workaround, why a value is what it is
  (the codebase already does this well — e.g. the embedding-dimension and
  chunk-size comments in `core/config.py`), or a link to a spec or issue.
- Prefer self-documenting names and small functions over explanatory comments.
- When in doubt, leave the comment out.

## Writing

- No em dashes (U+2014) in generated content: docs, comments, commit messages,
  READMEs, specs. They read as AI-generated.
- Use a hyphen for `term - description` separators; rephrase prose with commas,
  parentheses, or a colon. Avoid en dashes and the ellipsis character too.
