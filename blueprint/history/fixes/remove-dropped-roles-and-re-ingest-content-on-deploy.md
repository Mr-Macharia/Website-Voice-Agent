# Fix: Remove dropped roles and re-ingest content on deploy

**Type:** Fix
**Status:** verified
**Branch:** fix/remove-dropped-roles-and-re-ingest-content-on-deploy

## The problem

**Content.** The owner no longer wants these on the site or in the agent's
answers:
- The roles at TechHut, Women Enterprise Fund and Drip Industries.
- Any mention of lessons, workshops or workshop facilitation.

Those edits are already made, uncommitted, in `backend/content/`
(`experience.md`, `faq.md`, `skills.md`). A search for
`workshop|lesson|techhut|women enterprise|drip` across `backend/content` now
finds nothing.

**The knowledge base won't follow the content.** The agent answers from
vectors in Heroku Postgres (`ai.knowledge_vectors`), not from the files.
`scripts/ingest.py` is manual and never runs on deploy. Even when it is run,
the default mode (`skip_if_exists`) adds a changed file's new chunks next to
the old ones. `--force` upserts, which also leaves removed sections in place.
Either way, the deleted roles stay retrievable. Only `--reindex`, which drops
everything, clears them.

## The fix

1. **Replace changed files.** Add a `--replace-changed` mode to `ingest.py`
   for the `markdown` and `documents` sources. For each file whose content
   hash is not already stored, first call
   `kb.remove_vectors_by_name(<name>)`, then insert it fresh. Unchanged files
   still cost no embedding calls.
2. **Remove deleted files.** In the same mode, delete vectors for any
   `source_type: markdown` or `document` entry whose file no longer exists.
3. **Run it on every deploy.** Add a Heroku release phase:
   `release: python scripts/ingest.py --source local --replace-changed`.
   - `local` is a new source alias for `markdown` plus `documents`.
   - GitHub and website ingestion stay manual. They are slow and
     rate-limited, and a failure there shouldn't hold up a deploy.
4. **Never block a deploy.** The release command exits 0 and logs an error
   when embedding or the database is unavailable. The previous vectors keep
   serving, and the next deploy retries. It exits non-zero only on a code
   error such as an import failure.
5. **Docs.** `docs/deployment.md` explains that content changes go live, and
   re-ingest, on each deploy. The `ingest.py` docstring documents the new
   mode.

Checked against the installed Agno: `PgVector` exposes `delete_by_name`,
`delete_by_metadata` and `content_hash_exists`, and `Knowledge` exposes
`remove_vectors_by_name` and `remove_vectors_by_metadata`.

**Must not break:**
- The existing `ingest.py` flags (`--source`, `--force`, `--reindex`).
- The hybrid search indexes, which are rebuilt only when something was
  inserted.

**Out of scope:**
- Making the tools async (the next fix).
- Automatic GitHub or website re-ingestion.
- Changing chunking or retrieval settings.

## Build steps

- [x] **1. Add replace-changed ingestion.** Implement fix items 1, 2 and 4, and
  the `local` alias, in `backend/scripts/ingest.py`.
  **Done when:** against the **local** database, run the mode twice.
  - The first run replaces the changed files, and the log names each
    replaced or removed file.
  - The second run replaces nothing.
  - A direct query of the vectors table finds no chunk containing
    `TechHut`, `Women Enterprise`, `Drip Industries` or `workshop`.
- [x] **2. Wire the release phase and docs.** Add `release:` to
  `backend/Procfile`. Update `docs/deployment.md` and the script docstring.
  **Done when:**
  - The Procfile has both a `web` and a `release` line.
  - `python -c "import ast; ast.parse(...)"` on `ingest.py` passes.
  - The docs describe the behavior.

- [x] **3. Repair F-16 (review finding).** Key local items as `md:<stem>` and
  `doc:<filename>` in `--replace-changed`, so no two local files share a
  vector name, and none can match a `github-*` or `website` row. The removal
  pass cleans up the old unprefixed names on the next sync.
  **Done when:** a local run removes the old names and inserts the prefixed
  ones. A second run replaces and removes nothing. No `name` in the table
  collides across source types. The removed-roles query still returns 0.

## Verify

- **Locally:** step 1's double run and query. The agent, asked "Did he work
  at TechHut?" or "Does he run workshops?", no longer claims either.
- **After the user pushes to Heroku:**
  - The release log shows the ingest summary (for example, "replaced 3,
    removed 0").
  - The same two questions on the live site get the corrected answers.
- The content edits ship in this fix's commit.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":4554,"specSha256":"5e1d1db019a877d726b1c431dfdbf00fa3310ab9465e19516bfc1f31e90d6222","branch":"refs/heads/fix/remove-dropped-roles-and-re-ingest-content-on-deploy","head":"33b82eddccae12bd7f629120d1a7d6f81cac6140","baseRef":"refs/heads/master","baseCommit":"28efd50adf75237e3001e85283d914757fddf9b6","sourceTree":"2305f38e5ed6409e2e0b2abc25cb10c7e7553ddd","absentOptional":[]} -->

## Findings

### remove-dropped-roles-and-re-ingest-content-on-deploy/F-16 [P2] closed - Same-name local files delete each other's vectors on every deploy

**File:** backend/scripts/ingest.py:338
**Found:** 2026-09-30 by /audit independent (scope: current; lens: quality, security)
**Why it matters:** Items are keyed by `path.stem`, so `content/faq.md` and
`content/documents/faq.pdf` (or `notes.md` + `notes.txt` in documents) share the
name `faq`. `stored` is read once, holds both hashes, never equals `{sha}`, so
each item calls `remove_vectors_by_name("faq")`: the second deletes the vectors
the first just inserted. The release phase then silently drops one curated file
from the production index on every deploy and re-embeds both each time. Also,
`remove_vectors_by_name` deletes by name regardless of `source_type`, so a
`content/website.md` would delete the crawled `website` rows. No colliding files
exist today (documents dir is empty), so this is latent.
**Suggested fix:** Key local items by a unique name (e.g. `doc-<filename>` for
documents), refuse or warn on duplicate names before deleting, and delete by
name plus `source_type` rather than name alone.
**Resolution:** Closed 2026-09-29 by independent review at 33b82ed. `_local_items`
now names items `md:<stem>` (stems unique within `content/`) and
`doc:<filename>` (filenames unique within `documents/`); the colon prefixes
cannot collide with each other or with `github-*`/`website`. Local run of
`--source local --replace-changed` showed one hash per `md:*` name and a
no-op resync (replaced 0, removed 0). Residual latent case only: a legacy
unprefixed document row whose stem equals `website` or `github-*` would take
crawl rows with it on its one-time removal; none exist locally.

## Independent review

**Status:** passed
**Target commit:** 33b82eddccae12bd7f629120d1a7d6f81cac6140
**Base commit:** 28efd50adf75237e3001e85283d914757fddf9b6
**Base ref:** master
**Spec hash:** 5e1d1db019a877d726b1c431dfdbf00fa3310ab9465e19516bfc1f31e90d6222
**Prepared by:** claude
**Builder model:** claude-opus-5-5
**Requested reviewer:** claude
**Requested model:** claude-opus-5-5
**Requested execution:** automatic
**Requested at:** 2026-09-29T23:37:02Z
**Workflow:** regular
**Check required:** no
**Reviewer adapter:** claude
**Reviewer model:** claude-opus-5-5
**Reviewer context:** fresh subagent
**Actual execution:** automatic
**Reviewed at:** 2026-09-29T23:38:15Z
**Scope:** current
**Lenses:** quality, security, performance, tests
**Verdict:** passed
**Check result:** not-required

## Commands

- `git rev-parse HEAD` / `git merge-base master HEAD`: pass (match target/base)
- `sha256sum blueprint/context/current-feature.md`: pass (matches Spec hash)
- `git status --porcelain`: pass (only review.md differs)
- `uv run python scripts/ingest.py --source local --replace-changed` (local DB): pass, exit 0, "replaced 0, removed 0"
- Read-only queries of local `ai.knowledge_vectors` and Agno contents table: pass

## Evidence

- Full 28efd50..33b82ed diff reviewed: ingest.py replace mode, Procfile release line, content removals, docs/deployment.md.
- Deletion scope in release: only names with source_type markdown/document not in `_local_items()`; github/website rows untouched; each `md:*` name holds exactly one file hash locally.
- F-16 re-verified and closed (unique `md:`/`doc:` names).

## Findings

- F-16 closed; F-19 [P3] open, F-20 [P3] open (new); F-17, F-18 [P3] remain open.

## Remaining risk

- No automated test runner exists; replace/remove logic has no unit tests.
- Production vector table not inspected: first deploy will delete all legacy unprefixed markdown/document rows and re-embed (intended); legacy document rows named like a github/website row would take those rows too (none locally).
- Changed-file and removed-file paths not exercised end to end locally (local DB was already in sync; left unchanged).
