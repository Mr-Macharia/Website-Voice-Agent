#!/usr/bin/env python
"""Build the knowledge base about the site owner.

A CLI, deliberately never run at server startup — a hosted site must not block
boot on a web crawl or a GitHub round trip.

    uv run python scripts/ingest.py --source all
    uv run python scripts/ingest.py --source markdown
    uv run python scripts/ingest.py --source github --force
    uv run python scripts/ingest.py --reindex          # rebuild from scratch
    uv run python scripts/ingest.py --source local --replace-changed

Idempotency is Agno's, not ours: add_content() hashes each item and
skip_if_exists=True means unchanged content costs zero embedding calls. Re-run
freely while writing content.

But neither skip_if_exists nor --force removes chunks a file no longer
contains, so an edited file keeps answering from its old text. --replace-changed
fixes that for local files (markdown + documents): it hashes each file, deletes
the old vectors of any file whose hash changed, re-inserts it, and deletes the
vectors of files that were removed. It is what the Heroku release phase runs,
so it never fails a deploy over an outage — it logs and exits 0.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import config, db, knowledge  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ingest")

# Quiet the HTTP stacks that crawling and GitHub pull in.
for _noisy in ("httpx", "httpcore", "urllib3", "h2", "hpack", "hyperframe", "bs4"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

GITHUB_API = "https://api.github.com"


def _chunking():
    """Chunk to fit the embedding model's context, with overlap.

    Agno's reader default (5000 chars, no overlap) exceeds bge-base-en-v1.5's
    512-token window (~2000 chars), so most of every chunk would be silently
    truncated before embedding and never retrievable.
    """
    from agno.knowledge.chunking.recursive import RecursiveChunking

    return RecursiveChunking(chunk_size=config.CHUNK_SIZE, overlap=config.CHUNK_OVERLAP)


def _load_flags(force: bool) -> dict:
    """skip_if_exists and upsert are mutually exclusive in Agno's API."""
    return {"skip_if_exists": False, "upsert": True} if force else {"skip_if_exists": True}


# --- Markdown -------------------------------------------------------------
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Bold labels the project template ships with; alone they carry no answer.
_PLACEHOLDER_LABELS = ("**What it is:**", "**Why I built it:**", "**How it works:**",
                       "**Stack:**", "**Status:**", "**Link:**")


def _is_unfilled_template(text: str) -> bool:
    """True if a content file is still scaffolding.

    Indexing an empty template is worse than indexing nothing: the agent
    retrieves a heading like "## What is he working on right now?" with no
    answer beneath it, and may present the question itself as a fact.

    Comments are stripped as blocks, not per line — the guidance inside a
    multi-line <!-- --> would otherwise read as real prose.
    """
    body = _HTML_COMMENT_RE.sub("", text)

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("#", ">", "|", "---")):
            continue
        # Angle brackets mark unreplaced slots like "## <Role> — <Company>".
        if "<" in line and ">" in line:
            continue
        stripped = line
        for label in _PLACEHOLDER_LABELS:
            stripped = stripped.replace(label, "")
        if not stripped.strip():
            continue
        # Anything left is real prose the owner wrote.
        return False
    return True


def ingest_markdown(kb, force: bool) -> int:
    files = sorted(config.CONTENT_DIR.glob("*.md"))
    if not files:
        logger.warning("No markdown found in %s", config.CONTENT_DIR)
        return 0

    count = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        if _is_unfilled_template(text):
            logger.info("  skip %-16s (template not filled in yet)", path.name)
            continue

        from agno.knowledge.reader.markdown_reader import MarkdownReader

        kb.add_content(
            name=path.stem,
            path=str(path),
            reader=MarkdownReader(chunking_strategy=_chunking()),
            metadata={"source": path.stem, "source_type": "markdown"},
            **_load_flags(force),
        )
        logger.info("  ok   %s", path.name)
        count += 1
    return count


# --- GitHub ---------------------------------------------------------------
def ingest_github(kb, force: bool) -> int:
    import httpx

    user = config.GITHUB_USERNAME
    if not user:
        logger.warning("GITHUB_USERNAME not set — skipping GitHub")
        return 0

    headers = {"Accept": "application/vnd.github+json"}
    count = 0

    try:
        with httpx.Client(timeout=30.0, headers=headers) as client:
            resp = client.get(
                f"{GITHUB_API}/users/{user}/repos",
                params={"sort": "updated", "per_page": 100, "type": "owner"},
            )
            if resp.status_code == 403:
                logger.error(
                    "GitHub rate-limited (60/hr unauthenticated). Wait, or set "
                    "GITHUB_TOKEN and re-run."
                )
                return 0
            resp.raise_for_status()
            repos = resp.json()

            for repo in repos:
                if repo.get("fork") or repo.get("archived"):
                    continue

                name = repo["name"]
                parts = [
                    f"# {name}",
                    repo.get("description") or "",
                    f"Language: {repo.get('language') or 'unspecified'}",
                    f"Topics: {', '.join(repo.get('topics') or []) or 'none'}",
                    f"Stars: {repo.get('stargazers_count', 0)}",
                    f"Updated: {(repo.get('updated_at') or '')[:10]}",
                    f"URL: {repo.get('html_url')}",
                ]

                # README adds real substance, but a full one can be thousands of
                # words and chunk into a dozen entries. With ~30 repos that
                # buries the curated bio and FAQ — the content that actually
                # answers "who is he". Cap it so each repo contributes roughly
                # one or two chunks.
                try:
                    readme = client.get(
                        f"{GITHUB_API}/repos/{user}/{name}/readme",
                        headers={**headers, "Accept": "application/vnd.github.raw"},
                    )
                    if readme.status_code == 200:
                        excerpt = readme.text[:config.GITHUB_README_CHARS]
                        if len(readme.text) > config.GITHUB_README_CHARS:
                            excerpt += "\n\n[README truncated]"
                        parts.append("\n" + excerpt)
                except Exception as e:
                    logger.debug("no README for %s: %s", name, e)

                from agno.knowledge.reader.text_reader import TextReader

                kb.add_content(
                    name=f"github-{name}",
                    text_content="\n\n".join(p for p in parts if p),
                    reader=TextReader(chunking_strategy=_chunking()),
                    metadata={
                        "source": f"github/{name}",
                        "source_type": "github",
                        "source_url": repo.get("html_url"),
                    },
                    **_load_flags(force),
                )
                logger.info("  ok   github/%s", name)
                count += 1
    except Exception as e:
        logger.error("GitHub ingestion failed: %s", e)

    return count


# --- Website --------------------------------------------------------------
def ingest_website(kb, force: bool) -> int:
    if not config.SITE_URL:
        logger.warning("SITE_URL not set — skipping website")
        return 0

    try:
        from agno.knowledge.reader.website_reader import WebsiteReader
    except ImportError:
        logger.error("beautifulsoup4 not installed — run: uv add beautifulsoup4")
        return 0

    try:
        kb.add_content(
            name="website",
            url=config.SITE_URL,
            reader=WebsiteReader(max_depth=2, max_links=25, chunking_strategy=_chunking()),
            metadata={
                "source": "website",
                "source_type": "website",
                "source_url": config.SITE_URL,
            },
            **_load_flags(force),
        )
        logger.info("  ok   %s", config.SITE_URL)
        return 1
    except Exception as e:
        logger.error("Website ingestion failed: %s", e)
        return 0


# --- Documents (PDF / DOCX / TXT) ----------------------------------------
def ingest_documents(kb, force: bool) -> int:
    doc_dir = config.DOCUMENTS_DIR
    if not doc_dir.exists():
        return 0

    files = [p for p in sorted(doc_dir.iterdir()) if p.suffix.lower() in
             {".pdf", ".docx", ".txt", ".md"}]
    if not files:
        logger.info("  no documents in %s", doc_dir)
        return 0

    count = 0
    for path in files:
        try:
            kb.add_content(
                name=path.stem,
                path=str(path),
                metadata={"source": path.name, "source_type": "document"},
                **_load_flags(force),
            )
            logger.info("  ok   %s", path.name)
            count += 1
        except ImportError as e:
            logger.error("  fail %s — missing reader: %s", path.name, e)
        except Exception as e:
            logger.error("  fail %s — %s", path.name, e)
    return count


SOURCES = {
    "markdown": ingest_markdown,
    "github": ingest_github,
    "website": ingest_website,
    "documents": ingest_documents,
}

# Sources that live in the repo, and so can be kept exactly in sync on deploy.
LOCAL_SOURCES = ("markdown", "documents")
_LOCAL_SOURCE_TYPES = ("markdown", "document")


# --- Replace changed local files -------------------------------------------
def _local_items() -> list[dict]:
    """Every local file that should be indexed, with how to load it."""
    from agno.knowledge.reader.markdown_reader import MarkdownReader

    items = []
    for path in sorted(config.CONTENT_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if _is_unfilled_template(text):
            continue
        items.append({
            # Prefixed so no local file can share a name with another local
            # file or with a github-*/website row: delete_by_name ignores type.
            "name": f"md:{path.stem}", "path": path,
            "reader": MarkdownReader(chunking_strategy=_chunking()),
            "metadata": {"source": path.stem, "source_type": "markdown"},
        })

    doc_dir = config.DOCUMENTS_DIR
    if doc_dir.exists():
        for path in sorted(doc_dir.iterdir()):
            if path.suffix.lower() in {".pdf", ".docx", ".txt", ".md"}:
                items.append({
                    "name": f"doc:{path.name}", "path": path, "reader": None,
                    "metadata": {"source": path.name, "source_type": "document"},
                })
    return items


def _stored_hashes(kb) -> dict[str, set]:
    """name -> the file hashes its stored vectors were built from.

    Vectors from before this mode carry no hash, so they read as changed and
    are replaced once.
    """
    from sqlalchemy import text

    vdb = kb.vector_db
    sql = text(
        f'SELECT name, meta_data->>\'file_sha256\' FROM "{vdb.schema}"."{vdb.table_name}" '
        "WHERE meta_data->>'source_type' = ANY(:types)"
    )
    stored: dict[str, set] = {}
    with vdb.db_engine.connect() as conn:
        for name, sha in conn.execute(sql, {"types": list(_LOCAL_SOURCE_TYPES)}):
            stored.setdefault(name, set()).add(sha)
    return stored


def replace_changed_local(kb) -> tuple[int, int]:
    """Sync local files into the index. Returns (replaced, removed)."""
    import hashlib

    stored = _stored_hashes(kb)
    items = _local_items()
    replaced = 0

    for item in items:
        sha = hashlib.sha256(item["path"].read_bytes()).hexdigest()
        if stored.get(item["name"]) == {sha}:
            continue
        # Delete first: an upsert alone leaves chunks the file no longer has.
        kb.remove_vectors_by_name(item["name"])
        kwargs = {"reader": item["reader"]} if item["reader"] else {}
        kb.add_content(
            name=item["name"],
            path=str(item["path"]),
            metadata={**item["metadata"], "file_sha256": sha},
            skip_if_exists=False,
            upsert=True,
            **kwargs,
        )
        logger.info("  replaced %s", item["path"].name)
        replaced += 1

    removed = 0
    for name in sorted(set(stored) - {i["name"] for i in items}):
        kb.remove_vectors_by_name(name)
        logger.info("  removed  %s (file no longer exists)", name)
        removed += 1

    return replaced, removed


def _run_replace_changed(args) -> int:
    """The release-phase path. A deploy must not fail because DeepInfra or the
    database blinked: the previous vectors keep serving and the next deploy
    retries. Only a bug (an exception escaping this function) exits non-zero.
    """
    if args.source != "local" or args.force or args.reindex:
        logger.error("--replace-changed needs --source local, and cannot be "
                     "combined with --force or --reindex.")
        return 2

    if not config.knowledge_available():
        logger.warning("Knowledge not configured (missing %s) — skipping ingestion.",
                       ", ".join(config.missing_for("knowledge")))
        return 0

    try:
        db.init_schema()
        kb = knowledge.get_knowledge()
        if kb is None:
            logger.warning("Knowledge base unavailable — skipping ingestion.")
            return 0
        replaced, removed = replace_changed_local(kb)
        if replaced:
            db.create_vector_indexes()
    except Exception as e:  # outage, not a bug: keep the old index serving
        logger.error("Ingestion skipped, old index still serving: %s", e)
        return 0

    logger.info("\nLocal content in sync: replaced %d, removed %d.", replaced, removed)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--source", default="all", choices=[*SOURCES, "local", "all"],
        help="Which source to ingest (default: all; local = markdown + documents)",
    )
    parser.add_argument(
        "--replace-changed", action="store_true",
        help="Local sources only: replace edited files' vectors and drop deleted "
        "files'. Never exits non-zero on an outage (used by the Heroku release phase).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-embed content even if unchanged (upsert instead of skip)",
    )
    parser.add_argument(
        "--reindex", action="store_true",
        help="Drop the vector table and rebuild. Required after changing EMBED_MODEL.",
    )
    args = parser.parse_args()

    if args.replace_changed:
        return _run_replace_changed(args)

    if not config.knowledge_available():
        logger.error(
            "Knowledge is not configured — missing %s.\n"
            "See Phase 0: create the database and set these in .env.",
            ", ".join(config.missing_for("knowledge")),
        )
        return 1

    logger.info(
        "Embedding with %s (%s dims) via %s",
        config.EMBED_MODEL, config.EMBED_DIMENSIONS, config.DEEPINFRA_BASE_URL,
    )

    db.init_schema()
    kb = knowledge.get_knowledge()
    if kb is None:
        logger.error("Could not build the knowledge base — see errors above.")
        return 1

    if args.reindex:
        logger.info("Dropping existing vectors…")
        try:
            kb.vector_db.drop()
        except Exception as e:
            logger.warning("Nothing to drop (%s)", e)
        # drop() removes the table; nothing recreates it before the first
        # insert, so every batch fails with UndefinedTable. Recreate it here.
        try:
            kb.vector_db.create()
            logger.info("  table recreated")
        except Exception as e:
            logger.error("Could not recreate vector table: %s", e)
            return 1

    selected = {"all": list(SOURCES), "local": list(LOCAL_SOURCES)}.get(args.source, [args.source])
    total = 0
    for name in selected:
        logger.info("\n%s:", name)
        total += SOURCES[name](kb, force=args.force or args.reindex)

    # Agno creates the HNSW/GIN indexes only when asked. Without this the
    # table has B-tree indexes and every search is a sequential scan.
    if total:
        logger.info("\nBuilding vector indexes…")
        try:
            db.create_vector_indexes()
            logger.info("  indexes ready")
        except Exception as e:
            logger.warning("  could not build indexes: %s", e)

    logger.info("\nIngested %d item(s).", total)
    if total == 0:
        logger.warning(
            "Nothing was indexed. Fill in backend/content/*.md — the agent "
            "cannot answer questions about %s without it.", config.OWNER_NAME,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
