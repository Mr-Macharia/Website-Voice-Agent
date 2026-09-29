# Findings

> **Generated file.** The findings ledger: review findings raised by `/audit`
> against the work in progress, each with a durable ID, severity (P0-P3), and
> status. `/implement` marks repaired findings `fixed`, a later `/audit` pass
> moves them to `closed`, and `/complete` refuses to merge while any P0 or P1
> finding is `open` or `fixed`, then archives resolved findings with the work
> and resets this file.

### F-09 [P3] unverified - LiveKitVoiceModal inlines a Next.js API route fetch, not through src/api

**File:** frontend/src/components/voice/LiveKitVoiceModal.tsx:1641
**Found:** 2026-09-28 by /audit (scope: current; lens: quality)
**Why it matters:** Encountered while auditing F-06's fix, outside its scope.
`fetch(`/api/livekit/token?room=${roomName}`)`, with a fallback to
`${selectedEndpoint}/api/livekit/token`, is not the AgentOS backend pattern
`coding-standards.md`'s `src/api/` rule targets (that rule is about calls to
the Python backend; this primary call is to a same-server Next.js route).
Unverified rather than open: it is inside the LiveKit fallback path, which is
out of scope for both F-06 and this pass, and it is not certain the standard
was intended to cover Next.js API routes as well as the Python backend.
**Suggested fix:** If `src/api/` is meant to cover this class of call too,
extend `APIRoutes` or add a sibling convention for local routes; otherwise
mark it explicitly out of scope in `coding-standards.md`.
**Resolution:**

### F-11 [P2] fixed - The localhost fallback pattern F-06 removed still exists in two voice call sites

**File:** frontend/src/components/voice/AssemblyAIVoiceModal.tsx:137, frontend/src/components/voice/LiveKitVoiceModal.tsx:732
**Found:** 2026-09-29 by /audit (scope: full; lens: quality)
**Why it matters:** F-06 removed `${selectedEndpoint || 'http://localhost:7777'}` from `Messages.tsx`, establishing during that fix that
`selectedEndpoint` is a required string in the store, synchronously
initialized from `NEXT_PUBLIC_AGENT_OS_URL` (localhost only as a *build-time*
fallback), and deliberately excluded from `localStorage` persistence after
the app already hit and fixed a stale-cached-localhost bug once. The same
`|| 'http://localhost:7777'` construction is duplicated at two more call
sites -- both on the primary voice-connection path, higher-traffic than the
lead form F-06 touched. The duplicate fallback can only ever be wrong: if
`selectedEndpoint`'s non-empty contract ever changes, these two call sites
silently reintroduce exactly the bug F-06 closed, in a place nobody would
think to check because the "real" fallback lives in `store.ts`.
**Suggested fix:** Read `selectedEndpoint` directly in both call sites, the
way `Messages.tsx` now does, since the store guarantees it is always a
non-empty string.
**Resolution:**

### F-12 [P3] unverified - The voice-token fetch is browser-initiated but excluded from visitor-cookie scoping

**File:** frontend/src/lib/voice/AssemblyAISession.ts:142, backend/server.py:260
**Found:** 2026-09-29 by /audit (scope: full; lens: security)
**Why it matters:** `_NO_COOKIE_PATHS`'s comment states the exclusion is for
"server-to-server callers... AssemblyAI calls the LLM proxy with no browser
and no cookie." That rationale clearly covers `/api/llm/` and
`/api/voice/tool` (called by AssemblyAI itself via `AssemblyAISession`'s
client-side relay of a `tool.call` event). But the initial
`GET /api/voice/token` fetch at `AssemblyAISession.ts:142` runs directly in
the browser before any AssemblyAI session exists -- it is the request that
*starts* the session, not a callback from it. It has no `credentials:
'include'` and is excluded from cookie scoping, unlike every other
browser-initiated backend call in the app since feature 17. Unverified rather
than open because the exclusion may be intentional for an unstated reason
(voice sessions may not need visitor-cookie attribution the way chat/leads
do), and confirming that requires a product decision, not just code reading.
**Suggested fix:** Either confirm voice sessions are deliberately excluded
from visitor scoping and extend the code comment to say so explicitly, or
remove `/api/voice/token` from `_NO_COOKIE_PATHS` and add `credentials:
'include'` to its fetch, matching every other browser-initiated call.
**Resolution:**

### F-15 [P3] open - `livekit-server-sdk` is now an unused frontend dependency

**File:** frontend/package.json:30
**Found:** 2026-09-29 by /audit independent (scope: current; lens: quality)
**Why it matters:** The deleted `api/livekit/token/route.ts` was the only
importer of `livekit-server-sdk`; no file under `frontend/src` imports it now.
It keeps a server-side signing SDK in the Vercel bundle's dependency set and
invites someone to reintroduce frontend token minting.
**Suggested fix:** Remove `livekit-server-sdk` from `frontend/package.json` and
refresh the lockfile.
**Resolution:**

### F-17 [P3] open - Release phase removes document vectors whose files are not in the deployed slug

**File:** backend/scripts/ingest.py:360
**Found:** 2026-09-30 by /audit independent (scope: current; lens: quality)
**Why it matters:** `content/documents/` is empty and untracked, so it does not
exist on Heroku. Any document vectors previously loaded into production from a
developer machine (`--source documents`) are treated as "removed files" and
deleted on the next deploy. Intended sync semantics, but not stated in
`docs/deployment.md`, which only says deleted files lose their vectors.
**Suggested fix:** Document that the repo is the source of truth for markdown
and document vectors (documents must be committed), or scope removal to
markdown only when the documents dir is absent.
**Resolution:**

### F-18 [P3] open - Catch-all exit 0 hides programming errors and a delete-then-failed-insert gap

**File:** backend/scripts/ingest.py:393
**Found:** 2026-09-30 by /audit independent (scope: current; lens: quality)
**Why it matters:** `except Exception` returns 0 for every error, including
bugs (bad SQL, AttributeError), contradicting the docstring's "only a bug exits
non-zero"; a broken sync would ship green on every deploy with only a log line.
If an insert fails after `remove_vectors_by_name`, that file serves no vectors
until the next deploy (self-heals because its name disappears from `stored`).
`delete_by_name`'s False return is ignored.
**Suggested fix:** Catch only connection/HTTP error types for exit 0, let other
exceptions fail the release, and check the delete result before inserting.
**Resolution:**

### F-19 [P3] open - Manual markdown/documents ingest still uses unprefixed names

**File:** backend/scripts/ingest.py:122
**Found:** 2026-09-29 by /audit independent (scope: current; lens: quality)
**Why it matters:** `ingest_markdown` and `ingest_documents` (used by
`--source markdown|documents|all` and `--reindex`, all still in the module
docstring) name rows `path.stem`, while the release phase uses `md:`/`doc:`.
Running a documented manual ingest against production adds a second copy of
every curated chunk alongside the `md:*` rows, doubling them in retrieval until
the next deploy deletes the unprefixed rows and (after `--reindex`) re-embeds
everything. No data loss; duplicate answers and embedding churn.
**Suggested fix:** Reuse `_local_items()` names in `ingest_markdown` /
`ingest_documents` (or route them through `replace_changed_local`).
**Resolution:**

### F-20 [P3] open - Removed or replaced vectors leave stale rows in the Agno contents table

**File:** backend/scripts/ingest.py:365
**Found:** 2026-09-29 by /audit independent (scope: current; lens: quality)
**Why it matters:** `remove_vectors_by_name` deletes only vectors. The
knowledge `contents_db` keeps its rows, so locally 64 contents entries include
the legacy `bio`/`experience`/`faq`/`projects`/`skills` rows (some duplicated)
next to the `md:*` rows, and every removed file will leave a ghost entry in the
AgentOS knowledge view. Retrieval is unaffected.
**Suggested fix:** Also remove the matching contents rows (Agno's content
removal API by id/name) when a local item is replaced or removed.
**Resolution:**
