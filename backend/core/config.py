"""Central configuration for the personal-site agent.

Every module reads settings from here rather than calling os.getenv() directly,
so there is one place to see what the app needs and one place to change it.

Env loading order matches the existing convention in server.py and
livekit_worker.py: backend/.env, then the repo root .env, then the real
environment. Root .env wins over backend/.env; a real environment variable set
by the host always wins over both, which is what a live deployment needs.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env", override=True)
load_dotenv(WORKSPACE_DIR / ".env", override=True)
load_dotenv(override=True)


def _get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is not None:
        value = value.strip()
    return value or None


def _get_int(name: str, default: int | None = None) -> int | None:
    raw = _get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


# --- Owner identity -------------------------------------------------------
OWNER_NAME = _get("OWNER_NAME", "Gichogu Macharia")
GITHUB_USERNAME = _get("GITHUB_USERNAME", "Mr-Macharia")
SITE_URL = _get("SITE_URL", "https://gichogumacharia.tech")

# --- Database -------------------------------------------------------------
DATABASE_URL = _get("DATABASE_URL")

# --- Embeddings (DeepInfra, OpenAI-compatible) ----------------------------
DEEPINFRA_API_KEY = _get("DEEPINFRA_API_KEY")
DEEPINFRA_BASE_URL = _get("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")
EMBED_MODEL = _get("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
# MUST match the model. OpenAIEmbedder otherwise defaults to 1536 (an OpenAI
# model size), which silently creates a mis-sized pgvector column.
EMBED_DIMENSIONS = _get_int("EMBED_DIMENSIONS", 768)

# --- Chunking -------------------------------------------------------------
# bge-base-en-v1.5 has a 512-token context (~2000 chars). Agno's default chunk
# is 5000 chars with zero overlap, so most of every chunk would be silently
# truncated before embedding and never retrievable. 1200 leaves headroom;
# overlap keeps a fact that straddles a boundary findable from both sides.
CHUNK_SIZE = _get_int("CHUNK_SIZE", 1200)
CHUNK_OVERLAP = _get_int("CHUNK_OVERLAP", 150)

# --- Retrieval ------------------------------------------------------------
# Deliberately small: every retrieved chunk is prompt tokens, and on the voice
# path retrieval happens before the first audio frame.
KNOWLEDGE_TOP_K = _get_int("KNOWLEDGE_TOP_K", 4)

# --- Cal.com --------------------------------------------------------------
# The public booking page. The agent hands this over rather than reading
# availability through the API — see core/tools/booking.py for why.
CALCOM_BOOKING_URL = _get(
    "CALCOM_BOOKING_URL", "https://cal.com/macharia/ai-and-automation-consultation"
)

# --- Lead notification ----------------------------------------------------
LEAD_NOTIFY_EMAIL = _get("LEAD_NOTIFY_EMAIL")
LEAD_SMTP_HOST = _get("LEAD_SMTP_HOST", "smtp.gmail.com")
LEAD_SMTP_PORT = _get_int("LEAD_SMTP_PORT", 587)
LEAD_SMTP_USER = _get("LEAD_SMTP_USER")
LEAD_SMTP_APP_PASSWORD = _get("LEAD_SMTP_APP_PASSWORD")

# --- LLM (unchanged from existing behaviour) ------------------------------
XAI_API_KEY = _get("XAI_API_KEY")
OPENAI_API_KEY = _get("OPENAI_API_KEY")
BEDROCK_BASE_URL = _get("BEDROCK_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1")
BEDROCK_API_KEY = _get("BEDROCK_API_KEY")
BEDROCK_MODEL_ID = _get("BEDROCK_MODEL_ID", "deepseek.v3.2")

# --- Content --------------------------------------------------------------
CONTENT_DIR = BACKEND_DIR / "content"
DOCUMENTS_DIR = CONTENT_DIR / "documents"


# --- Feature availability -------------------------------------------------
# Each feature degrades independently. A missing Cal.com key must not stop the
# agent answering questions, and a missing database must not break voice chat.
def knowledge_available() -> bool:
    return bool(DATABASE_URL and DEEPINFRA_API_KEY)


def booking_available() -> bool:
    return bool(CALCOM_BOOKING_URL)


def leads_available() -> bool:
    return bool(DATABASE_URL)


def lead_notification_available() -> bool:
    return bool(LEAD_NOTIFY_EMAIL and LEAD_SMTP_USER and LEAD_SMTP_APP_PASSWORD)


def missing_for(feature: str) -> list[str]:
    """Names of the env vars a feature needs but doesn't have. For diagnostics."""
    required = {
        "knowledge": {"DATABASE_URL": DATABASE_URL, "DEEPINFRA_API_KEY": DEEPINFRA_API_KEY},
        "booking": {"CALCOM_BOOKING_URL": CALCOM_BOOKING_URL},
        "leads": {"DATABASE_URL": DATABASE_URL},
        "lead_notification": {
            "LEAD_NOTIFY_EMAIL": LEAD_NOTIFY_EMAIL,
            "LEAD_SMTP_USER": LEAD_SMTP_USER,
            "LEAD_SMTP_APP_PASSWORD": LEAD_SMTP_APP_PASSWORD,
        },
    }[feature]
    return [name for name, value in required.items() if not value]
