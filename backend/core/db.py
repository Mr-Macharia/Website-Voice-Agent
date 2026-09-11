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


def get_agno_db() -> Any:
    """PostgresDb for sessions, memory, metrics and knowledge-content metadata."""
    from agno.db.postgres import PostgresDb

    return PostgresDb(
        db_engine=get_engine(),
        session_table="agent_sessions",
        memory_table="user_memories",
        metrics_table="metrics",
        eval_table="eval_runs",
        knowledge_table="agno_knowledge",
    )


def get_embedder() -> Any:
    """DeepInfra embeddings through the OpenAI-compatible client.

    dimensions MUST be passed: OpenAIEmbedder defaults to 1536 based on OpenAI
    model names, which is wrong for BGE (768) and would create a mis-sized
    pgvector column that silently corrupts retrieval.
    """
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    return OpenAIEmbedder(
        id=config.EMBED_MODEL,
        base_url=config.DEEPINFRA_BASE_URL,
        api_key=config.DEEPINFRA_API_KEY,
        dimensions=config.EMBED_DIMENSIONS,
    )


def get_vector_db(table_name: str = "knowledge_vectors") -> Any:
    """pgvector store for the knowledge base."""
    from agno.vectordb.pgvector import PgVector

    return PgVector(
        table_name=table_name,
        db_engine=get_engine(),
        embedder=get_embedder(),
    )
