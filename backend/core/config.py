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
def _normalize_db_url(url: str | None) -> str | None:
    """Force the psycopg3 driver onto a Postgres URL.

    Managed hosts (Heroku, Render, Railway) hand out `postgres://`, which
    SQLAlchemy cannot parse at all, and `postgresql://` selects psycopg2, which
    this project does not install. Both must become `postgresql+psycopg://`.

    Normalizing here rather than at the call site matters because these hosts
    rotate the credential without warning: anything that edited the stored
    value by hand would silently revert on the next rotation.
    """
    if not url:
        return url
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _normalize_db_url(_get("DATABASE_URL"))

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

# --- GitHub ingestion -----------------------------------------------------
# Cap README length. Unbounded, ~30 repos produced 231 chunks against 29 of
# curated bio/FAQ, so repo docs crowded out the content that answers questions
# about the person rather than the code.
GITHUB_README_CHARS = _get_int("GITHUB_README_CHARS", 1500)

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

# --- Composio / Gmail -----------------------------------------------------
COMPOSIO_API_KEY = _get("COMPOSIO_API_KEY")
COMPOSIO_USER_ID = _get("COMPOSIO_USER_ID", "gichogu-site-agent")
# notify (drafts only) | read (drafts + read mail) | full (everything, incl.
# irreversible deletes). See core/tools/gmail.py — this is a security control,
# not a convenience setting, because the agent is public-facing.
GMAIL_SCOPE = _get("GMAIL_SCOPE", "notify")

# --- Lead notification ----------------------------------------------------
LEAD_NOTIFY_EMAIL = _get("LEAD_NOTIFY_EMAIL")
LEAD_SMTP_HOST = _get("LEAD_SMTP_HOST", "smtp.gmail.com")
LEAD_SMTP_PORT = _get_int("LEAD_SMTP_PORT", 587)
LEAD_SMTP_USER = _get("LEAD_SMTP_USER")
LEAD_SMTP_APP_PASSWORD = _get("LEAD_SMTP_APP_PASSWORD")

# --- LLM (unchanged from existing behaviour) ------------------------------
# DeepSeek's own API (not the Bedrock-hosted deepseek.v3.2, which could not
# emit tool calls — see voice/llm_proxy.py). deepseek-flash is V4.1-Flash, a
# different generation, and does advertise tool-call support.
DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL_ID = _get("DEEPSEEK_MODEL_ID", "deepseek-flash")

XAI_API_KEY = _get("XAI_API_KEY")
# grok-4.6 is the voice default: it calls tools reliably with conversation
# history present, which deepseek.v3.2 does not (see voice/llm_proxy.py).
XAI_MODEL_ID = _get("XAI_MODEL_ID", "grok-4.6")
OPENAI_API_KEY = _get("OPENAI_API_KEY")
BEDROCK_BASE_URL = _get("BEDROCK_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1")
BEDROCK_API_KEY = _get("BEDROCK_API_KEY")
BEDROCK_MODEL_ID = _get("BEDROCK_MODEL_ID", "deepseek.v3.2")

# --- Voice (AssemblyAI Voice Agent API) -----------------------------------
# The voice path runs on AssemblyAI's Voice Agent API: one WebSocket carrying
# STT, turn detection, and TTS. It replaced LiveKit, whose metered resource was
# connection minutes rather than speech, and Deepgram TTS along with it.
#
# The browser never sees ASSEMBLYAI_API_KEY. It calls /api/voice/token, which
# mints a short-lived single-use token server-side.
ASSEMBLYAI_API_KEY = _get("ASSEMBLYAI_API_KEY")
# A stored agent, created by scripts/provision_agent.py.
#
# This is not the shape originally planned. Configuring everything inline per
# session would have avoided a provisioning step, but the API rejects a custom
# `llm` on session.update — "BYO LLM config is not allowed on session.update;
# define it on a stored agent via POST /v1/agents". Since keeping our own LLM
# is the point of the migration, the agent has to be stored.
#
# agent_id is mutually exclusive with every inline field, so the prompt, voice,
# tools and turn detection all live on the stored agent too.
ASSEMBLYAI_AGENT_ID = _get("ASSEMBLYAI_AGENT_ID")
# Voice IDs are exact strings and are rejected at session.update if wrong.
# Current catalog: alba, eve, george, jane, jean, mary, michael (US);
# anna, charles, paul, vera (UK). See core/persona.py for the tone this matches.
ASSEMBLYAI_VOICE = _get("ASSEMBLYAI_VOICE", "michael")
# near-field for headsets and laptop mics held close; far-field for rooms.
# This is what suppresses a TV or background chatter before it reaches STT.
ASSEMBLYAI_VOICE_FOCUS = _get("ASSEMBLYAI_VOICE_FOCUS", "near-field")
# min_latency | balanced | max_accuracy. Presets how long the model waits in
# silence before ending a turn; the cleanest single turn-taking knob.
ASSEMBLYAI_TRANSCRIPTION_MODE = _get("ASSEMBLYAI_TRANSCRIPTION_MODE", "balanced")
# How long the visitor must speak before they can cut the agent off, in ms
# (0-1000). The API default follows transcription_mode and is 500 on balanced,
# which tested as sluggish — you had to talk over the agent for noticeably too
# long before it stopped. 100 makes barge-in feel immediate.
#
# Raising it is the first thing to try if the agent starts interrupting itself,
# or if short back-channels ("mm-hmm", "right") cut it off.
ASSEMBLYAI_INTERRUPTION_DELAY = _get_int("ASSEMBLYAI_INTERRUPTION_DELAY", 100)

# AssemblyAI calls our LLM proxy server-to-server, so the URL must be public
# HTTPS — localhost is rejected. Local dev points at the deployed instance.
# The shared secret is passed as the llm[].api_key and checked on arrival, so
# the public endpoint isn't open to anyone who finds it.
LLM_PROXY_URL = _get("LLM_PROXY_URL")
LLM_PROXY_SECRET = _get("LLM_PROXY_SECRET")

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


def gmail_available() -> bool:
    return bool(COMPOSIO_API_KEY)


def voice_available() -> bool:
    """Voice needs the AssemblyAI key plus a reachable LLM for replies.

    The LLM proxy is what keeps the provider fallback chain alive, since
    AssemblyAI accepts only one llm entry. Without a public proxy URL the
    agent would connect and then be unable to say anything.
    """
    return bool(
        ASSEMBLYAI_API_KEY
        and ASSEMBLYAI_AGENT_ID
        and LLM_PROXY_URL
        and llm_available()
    )


def llm_available() -> bool:
    return bool(BEDROCK_API_KEY or XAI_API_KEY or OPENAI_API_KEY)


def lead_notification_available() -> bool:
    return bool(LEAD_NOTIFY_EMAIL and LEAD_SMTP_USER and LEAD_SMTP_APP_PASSWORD)


def missing_for(feature: str) -> list[str]:
    """Names of the env vars a feature needs but doesn't have. For diagnostics."""
    required = {
        "knowledge": {"DATABASE_URL": DATABASE_URL, "DEEPINFRA_API_KEY": DEEPINFRA_API_KEY},
        "booking": {"CALCOM_BOOKING_URL": CALCOM_BOOKING_URL},
        "leads": {"DATABASE_URL": DATABASE_URL},
        "gmail": {"COMPOSIO_API_KEY": COMPOSIO_API_KEY},
        "voice": {
            "ASSEMBLYAI_API_KEY": ASSEMBLYAI_API_KEY,
            "ASSEMBLYAI_AGENT_ID": ASSEMBLYAI_AGENT_ID,
            "LLM_PROXY_URL": LLM_PROXY_URL,
        },
        "lead_notification": {
            "LEAD_NOTIFY_EMAIL": LEAD_NOTIFY_EMAIL,
            "LEAD_SMTP_USER": LEAD_SMTP_USER,
            "LEAD_SMTP_APP_PASSWORD": LEAD_SMTP_APP_PASSWORD,
        },
    }[feature]
    return [name for name, value in required.items() if not value]
