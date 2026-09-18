"""
Voice Agent MCP Server
Exposes Deepgram, Agno, and LiveKit operations from this workspace
as MCP tools so opencode (or any MCP client) can drive the voice pipeline.

Covers:
- Deepgram STT (nova-3) + TTS (aura-luna-en / flux via REST)
- Agno site agent: RAG over the owner's knowledge base, web search, Cal.com booking
  and lead capture (PostgreSQL session memory)
- LiveKit token generation + room management (livekit-api)
- Health/status mirroring server.py:/api/info

Run via: uv run python mcp/voice_agent_server.py  (stdio transport)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

# Load .env from backend and workspace root
# override=True so values from this file win over empty env vars preset by MCP clients
BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env", override=True)
load_dotenv(WORKSPACE_DIR / ".env", override=True)
load_dotenv(override=True)  # also cwd

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise SystemExit(f"mcp not installed: {e}. Run `uv add \"mcp[cli]\"`") from e

mcp = FastMCP(
    name="voice-agent",
    instructions=(
        "Voice Agent control plane: Deepgram STT/TTS, the Agno site agent (RAG over "
        "the owner's knowledge base, web search, Cal.com booking, lead capture), and "
        "LiveKit rooms/tokens. Shares core/ with server.py and livekit_worker.py."
    ),
)

# ---------------------------------------------------------------------------
# Helpers: lazy clients to avoid import cost at startup
# ---------------------------------------------------------------------------

def _get_deepgram_api_key() -> Optional[str]:
    return os.getenv("DEEPGRAM_API_KEY")


def _get_livekit_creds() -> tuple[str, str, str]:
    return (
        os.getenv("LIVEKIT_URL", "wss://voice-agent.livekit.cloud"),
        os.getenv("LIVEKIT_API_KEY", "devkey"),
        os.getenv("LIVEKIT_API_SECRET", "secret01234567890123456789012345678901"),
    )


_voice_agent: Any = None


def _get_voice_agent():
    """The same agent server.py serves, built from the shared core module.

    This used to re-declare its own WebSearchTools and Agent inline, and scrape
    server.py with a regex to recover the system prompt — which broke silently
    the moment that prompt stopped being a triple-quoted literal. Now it imports
    the one definition, so it can never drift again.
    """
    global _voice_agent
    if _voice_agent is not None:
        return _voice_agent

    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.models.xai import xAI

    from core import config as core_config
    from core import db as core_db
    from core import knowledge as core_knowledge
    from core import persona
    from core.adapters.agno import SiteTools

    if core_config.BEDROCK_API_KEY:
        llm = OpenAIChat(
            id=core_config.BEDROCK_MODEL_ID,
            api_key=core_config.BEDROCK_API_KEY,
            base_url=core_config.BEDROCK_BASE_URL,
        )
    elif core_config.XAI_API_KEY:
        llm = xAI(id="grok-4.20-0309-non-reasoning", api_key=core_config.XAI_API_KEY)
    else:
        llm = OpenAIChat(id="gpt-4o-mini", api_key=core_config.OPENAI_API_KEY)

    db = None
    if core_config.DATABASE_URL:
        try:
            db = core_db.get_agno_db()
        except Exception:
            db = None

    knowledge = core_knowledge.get_knowledge()

    _voice_agent = Agent(
        id="voice-agent",
        name="Clyde",
        model=llm,
        tools=[SiteTools()],
        description=f"Clyde on the voice channel, for {core_config.OWNER_NAME}'s website.",
        instructions=[persona.for_voice()],
        markdown=False,
        db=db,
        knowledge=knowledge,
        search_knowledge=bool(knowledge),
        add_history_to_context=True,
        num_history_runs=4,
        enable_session_summaries=False,
        add_datetime_to_context=True,
    )
    return _voice_agent


# ---------------------------------------------------------------------------
# Tools: Deepgram
# ---------------------------------------------------------------------------

@mcp.tool()
async def deepgram_transcribe(
    audio_base64: str,
    mime_type: str = "audio/wav",
    model: str = "nova-3",
) -> str:
    """
    Transcribe audio via Deepgram Nova-3 (mirrors server.py:235 transcribe_audio_bytes).

    Args:
        audio_base64: Base64-encoded audio bytes.
        mime_type: MIME type hint (audio/wav, audio/webm, audio/ogg, audio/flac). Magic bytes auto-detected.
        model: Deepgram model (nova-3 default, also nova-2, whisper).
    Returns:
        Transcript string (empty if no speech).
    """
    import httpx

    api_key = _get_deepgram_api_key()
    if not api_key:
        return "Error: DEEPGRAM_API_KEY not configured"

    try:
        audio_bytes = base64.b64decode(audio_base64)
    except Exception as e:
        return f"Error: invalid base64: {e}"

    # Magic-byte sniff like server.py:241
    if audio_bytes.startswith(b"RIFF"):
        ct = "audio/wav"
    elif audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        ct = "audio/webm"
    elif audio_bytes.startswith(b"OggS"):
        ct = "audio/ogg"
    elif audio_bytes.startswith(b"fLaC"):
        ct = "audio/flac"
    else:
        ct = mime_type.split(";")[0].strip() or "audio/wav"

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            f"https://api.deepgram.com/v1/listen?model={model}&smart_format=true",
            headers={"Authorization": f"Token {api_key}", "Content-Type": ct},
            content=audio_bytes,
        )
        if res.status_code != 200:
            return f"Deepgram STT error {res.status_code}: {res.text[:500]}"
        data = res.json()
        try:
            return data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        except (KeyError, IndexError):
            return ""


@mcp.tool()
async def deepgram_transcribe_file(
    file_path: str,
    model: str = "nova-3",
) -> str:
    """
    Transcribe an audio file from disk via Deepgram.

    Args:
        file_path: Path to audio file (wav, mp3, webm, ogg, flac) relative to workspace or absolute.
        model: Deepgram model.
    """
    p = Path(file_path)
    if not p.is_absolute():
        p = Path.cwd() / p
        # also try workspace root
        alt = Path(__file__).parent.parent / file_path
        if alt.exists():
            p = alt
    if not p.exists():
        return f"Error: file not found: {p}"
    b64 = base64.b64encode(p.read_bytes()).decode()
    # guess mime
    ext = p.suffix.lower()
    mime = {" .wav": "audio/wav", ".mp3": "audio/mpeg", ".webm": "audio/webm", ".ogg": "audio/ogg", ".flac": "audio/flac"}.get(ext, "audio/wav")
    return await deepgram_transcribe(b64, mime, model)


@mcp.tool()
async def deepgram_speak(
    text: str,
    model: str = "flux-brooke-en",
    output_path: str = "agent_response.mp3",
) -> str:
    """
    Synthesize speech via Deepgram TTS (mirrors voice.py:44 speak.v1.audio.generate).
    Unified voice: flux-brooke-en (Flux v2) — streaming. Aura models use v1.

    Args:
        text: Plain text to synthesize (keep under 2000 chars; voice-optimized, no markdown).
        model: TTS model (flux-brooke-en default, also aura-asteria-en, aura-luna-en, flux variants).
        output_path: Where to save audio (default agent_response.mp3 at workspace root).
    Returns:
        Saved file path or error. Also returns base64 preview when file < 1MB.
    """
    api_key = _get_deepgram_api_key()
    if not api_key:
        return "Error: DEEPGRAM_API_KEY not configured"
    if not text or not text.strip():
        return "Error: empty text"

    out = Path(output_path)
    if not out.is_absolute():
        out = Path(__file__).parent.parent / output_path
    out.parent.mkdir(parents=True, exist_ok=True)

    is_flux = model.lower().startswith("flux")

    # Flux models require the v2 speak endpoint (v1 returns
    # V2_MODEL_ON_V1_SPEAK_ENDPOINT). Aura models use v1.
    if is_flux:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"https://api.deepgram.com/v2/speak?model={model}&encoding=mp3",
                    headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
                    json={"text": text},
                )
                if res.status_code != 200:
                    return f"Deepgram TTS error {res.status_code}: {res.text[:500]}"
                out.write_bytes(res.content)
                return f"Saved {len(res.content)} bytes to {out} (model={model})"
        except Exception as e:
            return f"Error: {e}"

    # Try SDK first (Aura / v1 models)
    try:
        from deepgram import DeepgramClient

        dg = DeepgramClient(api_key=api_key)
        # SDK v7: deepgram.speak.v1.audio.generate streaming
        try:
            # new streaming API
            stream = dg.speak.v1.audio.generate(text=text, model=model)  # type: ignore
            with open(out, "wb") as f:
                for chunk in stream:
                    f.write(chunk)
            size = out.stat().st_size
            return f"Saved {size} bytes to {out} (model={model})"
        except Exception:
            # fallback: REST save (v1 endpoint for non-Flux models)
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"https://api.deepgram.com/v1/speak?model={model}",
                    headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
                    json={"text": text},
                )
                if res.status_code != 200:
                    return f"Deepgram TTS error {res.status_code}: {res.text[:500]}"
                out.write_bytes(res.content)
                return f"Saved {len(res.content)} bytes to {out} (model={model})"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def deepgram_list_models() -> str:
    """List available Deepgram STT/TTS models (proxies dg models list)."""
    api_key = _get_deepgram_api_key()
    if not api_key:
        return "Error: DEEPGRAM_API_KEY not configured"
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(
            "https://api.deepgram.com/v1/models",
            headers={"Authorization": f"Token {api_key}"},
        )
        if res.status_code != 200:
            return f"Error {res.status_code}: {res.text[:800]}"
        data = res.json()
        # summarize
        models = data.get("models") or data
        if isinstance(models, dict):
            models = models.get("stt") or models.get("tts") or models
        return json.dumps(data, indent=2)[:8000]


# ---------------------------------------------------------------------------
# Tools: Agno
# ---------------------------------------------------------------------------

@mcp.tool()
async def agno_voice_run(
    message: str,
    session_id: Optional[str] = None,
    stream: bool = False,
) -> str:
    """
    Run the Agno voice-agent (server.py:126 Brooke) against a user message.

    Args:
        message: User transcript/text to respond to.
        session_id: Optional session id for memory (persists in Postgres). Auto-generated if omitted.
        stream: If true, uses streaming internally but returns concatenated text (MCP is request/response).
    Returns:
        Agent response text (plain, voice-ready, no markdown).
    """
    agent = _get_voice_agent()
    sid = session_id or f"mcp-{uuid.uuid4().hex[:8]}"
    try:
        if stream:
            full = ""
            # try async streaming arun
            try:
                async for chunk in agent.arun(message, session_id=sid, stream=True):  # type: ignore
                    c = getattr(chunk, "content", None)
                    if c:
                        full += c
                return full if full else "(no content)"
            except Exception:
                # fallback sync stream
                for chunk in agent.run(message, session_id=sid, stream=True):  # type: ignore
                    c = getattr(chunk, "content", None)
                    if c:
                        full += c
                return full if full else "(no content)"
        else:
            # non-streaming: prefer arun
            try:
                res = await agent.arun(message, session_id=sid)  # type: ignore
                return getattr(res, "content", str(res)) or str(res)
            except Exception:
                res = agent.run(message, session_id=sid)  # type: ignore
                return getattr(res, "content", str(res)) or str(res)
    except Exception as e:
        return f"Error running voice agent: {e}"


@mcp.tool()
def agno_list_sessions(limit: int = 10) -> str:
    """
    List recent Agno sessions from PostgreSQL.

    Args:
        limit: Max sessions to return.
    Returns:
        JSON of session ids, agent_ids, updated_at.
    """
    from sqlalchemy import text

    from core import config as core_config
    from core import db as core_db

    if not core_config.DATABASE_URL:
        return "DATABASE_URL is not set — no session store configured."
    try:
        with core_db.get_engine().connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT session_id, agent_id, updated_at, created_at "
                    "FROM agent_sessions ORDER BY updated_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return json.dumps([dict(r._mapping) for r in rows], indent=2, default=str)
    except Exception as e:
        return f"Error reading sessions: {e}"


@mcp.tool()
def agno_get_memory(limit: int = 5) -> str:
    """List recent user memories from PostgreSQL."""
    from sqlalchemy import text

    from core import config as core_config
    from core import db as core_db

    if not core_config.DATABASE_URL:
        return "DATABASE_URL is not set — no memory store configured."
    try:
        with core_db.get_engine().connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM user_memories ORDER BY updated_at DESC LIMIT :limit"),
                {"limit": limit},
            )
            return json.dumps([dict(r._mapping) for r in rows], indent=2, default=str)[:6000]
    except Exception as e:
        return f"Error reading memories: {e}"


# ---------------------------------------------------------------------------
# Tools: LiveKit
# ---------------------------------------------------------------------------

@mcp.tool()
def livekit_create_token(
    room: str = "voice-agent-room",
    identity: Optional[str] = None,
    name: Optional[str] = None,
    ttl_seconds: int = 3600,
) -> str:
    """
    Generate a LiveKit AccessToken (mirrors server.py:206 generate_livekit_token).

    Args:
        room: Room name to grant join.
        identity: Participant identity (auto-generated if omitted).
        name: Display name (defaults to identity).
        ttl_seconds: Token TTL (currently not enforced by SDK; for future use).
    Returns:
        JSON with token, url, room, identity.
    """
    try:
        from livekit import api
    except ImportError as e:
        return f"Error: livekit-api not installed: {e}"

    lk_url, lk_key, lk_secret = _get_livekit_creds()
    ident = identity or f"user-{uuid.uuid4().hex[:8]}"
    disp = name or ident
    try:
        token = (
            api.AccessToken(api_key=lk_key, api_secret=lk_secret)
            .with_identity(ident)
            .with_name(disp)
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True))
            .to_jwt()
        )
        return json.dumps({"token": token, "url": lk_url, "room": room, "identity": ident, "name": disp}, indent=2)
    except Exception as e:
        return f"Error generating token: {e}"


@mcp.tool()
async def livekit_list_rooms() -> str:
    """
    List LiveKit rooms via LiveKit API (requires LIVEKIT_URL/KEY/SECRET).
    Falls back to informative error if not configured.
    """
    lk_url, lk_key, lk_secret = _get_livekit_creds()
    # livekit-api provides api.LiveKitAPI for room service; try it
    try:
        from livekit.api import LiveKitAPI

        # LiveKitAPI is async context manager in newer versions
        async with LiveKitAPI(url=lk_url, api_key=lk_key, api_secret=lk_secret) as lk:  # type: ignore
            # method name varies: list_rooms or listRooms
            for meth in ("list_rooms", "listRooms", "room_service"):
                if hasattr(lk, meth):
                    fn = getattr(lk, meth)
                    try:
                        res = await fn() if asyncio.iscoroutinefunction(fn) else fn()
                        return json.dumps(str(res), indent=2)[:6000]
                    except Exception:
                        continue
            # try room attribute
            if hasattr(lk, "room"):
                try:
                    res = await lk.room.list_rooms()  # type: ignore
                    return json.dumps(str(res), indent=2)[:6000]
                except Exception as e:
                    return f"LiveKit room list via .room failed: {e}"
            return f"LiveKitAPI connected to {lk_url} but no list_rooms method found. SDK version mismatch."
    except Exception as e:
        return f"Error listing rooms ({lk_url}): {e}. Ensure LIVEKIT_URL/KEY/SECRET are set and livekit-api is installed."


@mcp.tool()
def health_check() -> str:
    """
    Health/status mirroring server.py:184 /api/info.
    Returns agents, LiveKit URL, Deepgram status, DB existence.
    """
    lk_url, _, _ = _get_livekit_creds()

    from core import config as core_config
    from core import db as core_db

    db_ok = False
    db_error = None
    if core_config.DATABASE_URL:
        try:
            from sqlalchemy import text

            with core_db.get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception as e:
            db_error = str(e)

    return json.dumps(
        {
            "status": "ok",
            "service": "voice-agent-mcp",
            "agents": ["voice-agent"],
            "livekit_url": lk_url,
            "deepgram_enabled": bool(_get_deepgram_api_key()),
            "database_configured": bool(core_config.DATABASE_URL),
            "database_reachable": db_ok,
            "database_error": db_error,
            "knowledge_enabled": core_config.knowledge_available(),
            "booking_enabled": core_config.booking_available(),
        },
        indent=2,
    )


if __name__ == "__main__":
    # stdio transport is default for opencode local MCPs
    mcp.run()
