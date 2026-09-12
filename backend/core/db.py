"""Database wiring: one SQLAlchemy engine shared by sessions, memory and vectors.

Everything is lazy. Importing this module must never open a connection, because
both server.py and livekit_worker.py import it at module scope and neither
should fail to boot just because Postgres is briefly unreachable.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
)
from sqlalchemy.engine import Engine

from core import config

logger = logging.getLogger("core.db")

_engine: Optional[Engine] = None
_metadata = MetaData()

# Leads captured by the agent. Deliberately flat and nullable — a visitor who
# only gives a first name and an email is still a lead worth keeping.
leads_table = Table(
    "leads",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("name", String(200)),
    Column("email", String(320)),
    Column("company", String(200)),
    Column("intent", String(200)),
    Column("message", Text),
    Column("session_id", String(200)),
    Column("source", String(20)),  # 'voice' | 'text'
    Column("booking_uid", String(200)),
)


def get_engine() -> Engine:
    """The one engine for this process. Raises if DATABASE_URL is unset."""
    global _engine
    if _engine is not None:
        return _engine

    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. See Phase 0 of the plan: create the database "
            "and add DATABASE_URL to .env."
        )

    _engine = create_engine(
        config.DATABASE_URL,
        # A hosted app's idle connections get dropped by the network; without
        # this, the first query after a quiet period fails.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )
    return _engine


def init_schema() -> None:
    """Create app-owned tables. Agno creates its own on first use."""
    _metadata.create_all(get_engine())


_agno_db: Optional[Any] = None


def get_agno_db() -> Any:
    """PostgresDb for sessions, memory, metrics and knowledge-content metadata.

    Cached: Agno derives a database id from the connection details, so building
    a second instance over the same engine makes its registry warn about
    "multiple distinct databases share id" on every agent construction. One
    instance, shared by both agents, is also simply correct.
    """
    global _agno_db
    if _agno_db is not None:
        return _agno_db

    from agno.db.postgres import PostgresDb

    _agno_db = PostgresDb(
        db_engine=get_engine(),
        session_table="agent_sessions",
        memory_table="user_memories",
        metrics_table="metrics",
        eval_table="eval_runs",
        knowledge_table="agno_knowledge",
    )
    return _agno_db


_embedder: Optional[Any] = None


def get_embedder() -> Any:
    """DeepInfra embeddings through the OpenAI-compatible client.

    Cached per process. The OpenAI client keeps a connection pool, but a fresh
    embedder gets a fresh pool — and the live logs showed a full TCP connect
    plus TLS handshake before every single retrieval, which is why the first
    measured lookup took 2.98s against a 0.43s median. One embedder means the
    keep-alive connection is actually reused.

    Two constraints pull in opposite directions:

    - OpenAIEmbedder.dimensions defaults to 1536 (an OpenAI model size). Agno
      reads it to size the pgvector column, so it must be correct for BGE (768)
      or every insert fails.
    - But Agno also SENDS dimensions whenever base_url is set, and DeepInfra
      rejects it for BGE — the model has no matryoshka representation, so the
      output size cannot be truncated. The request returns HTTP 400 and no
      embedding at all.

    So the attribute is set (for the column) while the request parameter is
    suppressed. Agno applies request_params last, so an explicit None there
    wins over the value it inserted; the OpenAI client then drops the key.

    EMBED_DIMENSIONS must therefore match the model's NATIVE size, not a size
    we are choosing — 768 for bge-base-en-v1.5, verified against the endpoint.
    """
    global _embedder
    if _embedder is not None:
        return _embedder

    from agno.knowledge.embedder.openai import OpenAIEmbedder

    _embedder = OpenAIEmbedder(
        id=config.EMBED_MODEL,
        base_url=config.DEEPINFRA_BASE_URL,
        api_key=config.DEEPINFRA_API_KEY,
        dimensions=config.EMBED_DIMENSIONS,
        request_params={"dimensions": None},
    )
    return _embedder


def get_vector_db(table_name: str = "knowledge_vectors") -> Any:
    """pgvector store for the knowledge base.

    Choices worth stating explicitly:

    - search_type=hybrid. Pure vector search is weak on the queries this site
      actually gets: proper nouns and acronyms ("Visiondrill", "JKUAT", "Agno",
      "RAG") embed poorly but match exactly on keywords. Hybrid runs both and
      fuses the scores, so "who is Visiondrill" hits the right chunk even when
      the embedding is ambiguous.
    - HNSW index over the default flat scan. At this corpus size a sequential
      scan would honestly be fine, but the index is one line, keeps voice
      latency flat as content grows, and costs nothing to add now.
    - Cosine distance, matching how BGE models are trained.
    """
    from agno.vectordb.pgvector import PgVector
    from agno.vectordb.distance import Distance
    from agno.vectordb.pgvector import HNSW
    from agno.vectordb.search import SearchType

    return PgVector(
        table_name=table_name,
        db_engine=get_engine(),
        embedder=get_embedder(),
        search_type=SearchType.hybrid,
        distance=Distance.cosine,
        # configuration={} deliberately: Agno emits `SET key = :value` with a
        # bind parameter, which Postgres rejects for SET statements, so its
        # default maintenance_work_mem entry breaks index creation outright.
        vector_index=HNSW(m=16, ef_search=20, ef_construction=200, configuration={}),
        # Weight vector vs keyword in the hybrid fusion. 0.6 leans on semantics
        # while leaving keyword matching enough influence to win on exact names.
        vector_score_weight=0.6,
    )


def create_vector_indexes(table_name: str = "knowledge_vectors", schema: str = "ai") -> None:
    """Create the HNSW and GIN indexes for hybrid search.

    Agno's PgVector.optimize() cannot do this against Postgres: it emits
    `SET maintenance_work_mem = :value` and `WITH (m = :m, ...)`, binding
    parameters into statements where Postgres does not accept them, so both
    index creations fail. The SQL here is the same thing Agno intends, written
    so it actually executes.

    Idempotent — safe to run after every ingestion.
    """
    from sqlalchemy import text

    full = f"{schema}.{table_name}"
    statements = [
        "SET maintenance_work_mem = '512MB'",
        f'CREATE INDEX IF NOT EXISTS {table_name}_hnsw_index '
        f"ON {full} USING hnsw (embedding vector_cosine_ops) "
        f"WITH (m = 16, ef_construction = 200)",
        f'CREATE INDEX IF NOT EXISTS {table_name}_content_gin_index '
        f"ON {full} USING gin (to_tsvector('english', content))",
    ]

    with get_engine().begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
