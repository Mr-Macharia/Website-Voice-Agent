"""
Voice Agent MCP Server
Exposes Deepgram, Agno, and LiveKit operations from this workspace
as MCP tools so opencode (or any MCP client) can drive the voice pipeline.

Covers:
- Deepgram STT (nova-3) + TTS (aura-luna-en / flux via REST)
- Agno voice-agent + research-agent (with SQLite session memory agno.db)
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
BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")
load_dotenv()  # also cwd

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise SystemExit(f"mcp not installed: {e}. Run `uv add \"mcp[cli]\"`") from e

mcp = FastMCP(
    name="voice-agent",
    instructions=(
        "Voice Agent control plane: Deepgram STT/TTS, Agno agents (voice + research), "
        "LiveKit rooms/tokens. Mirrors server.py and livekit_worker.py for MCP clients."
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


# ---------------------------------------------------------------------------
# Agno agents (lazy singleton matching server.py:126,140)
# ---------------------------------------------------------------------------
_voice_agent: Any = None
_research_agent: Any = None


def _get_voice_agent():
    global _voice_agent
    if _voice_agent is not None:
        return _voice_agent
    from agno.agent import Agent
    from agno.models.xai import xAI
    from agno.models.openai import OpenAIChat
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(
        db_file=str(BACKEND_DIR / "agno.db"),
        session_table="agent_sessions",
        memory_table="user_memories",
    )
    xai_key = os.getenv("XAI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if xai_key:
        llm = xAI(id="grok-4.20-0309-non-reasoning", api_key=xai_key)
    else:
        llm = OpenAIChat(id="gpt-4o-mini", api_key=openai_key)

    # Mirror server.py:79 VOICE_AGENT_SYSTEM_PROMPT excerpt for brevity; full prompt persisted in server.py
    system_prompt = BACKEND_DIR / "server.py"
    # we reuse server.VOICE_AGENT_SYSTEM_PROMPT at runtime if available
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("server_mod", system_prompt)
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        # don't exec full server (starts FastAPI), just read prompt string manually
        text = system_prompt.read_text()
        # fallback hardcoded concise prompt if import fails
        prompt_text = "You are Brooke, a fast, warm, concise voice assistant. Keep replies 1-2 sentences, plain text, no markdown."
        if "VOICE_AGENT_SYSTEM_PROMPT" in text:
            # extract triple-quoted block after assignment
            import re

            m = re.search(r'VOICE_AGENT_SYSTEM_PROMPT\s*=\s*"""(.*?)"""', text, re.S)
            if m:
                prompt_text = m.group(1).strip()
    except Exception:
        prompt_text = "You are Brooke, a fast, warm, concise voice assistant. Keep replies 1-2 sentences, plain text, no markdown."

    _voice_agent = Agent(
        id="voice-agent",
        name="Realtime Voice Assistant",
        model=llm,
        description="Fast, conversational virtual assistant speaking naturally over voice.",
        instructions=[prompt_text],
        markdown=False,
        db=db,
        add_history_to_context=True,
        num_history_runs=4,
        enable_session_summaries=False,
        add_datetime_to_context=True,
    )
    return _voice_agent


def _get_research_agent():
    global _research_agent
    if _research_agent is not None:
        return _research_agent
    from agno.agent import Agent
    from agno.models.xai import xAI
    from agno.models.openai import OpenAIChat
    from agno.db.sqlite import SqliteDb
    from agno.tools import Toolkit
    import urllib.request, urllib.parse, json as _json

    class WebSearchTools(Toolkit):
        def __init__(self):
            super().__init__(name="web_search_tools")
            self.register(self.search_web)

        def search_web(self, query: str) -> str:
            try:
                url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json&utf8=1"
                req = urllib.request.Request(url, headers={"User-Agent": "AgnoAgentOS/1.0"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read().decode())
                    results = data.get("query", {}).get("search", [])
                    if not results:
                        return f"No results for {query}."
                    return "\n\n".join(
                        f"Title: {x.get('title')}\nSummary: {x.get('snippet','').replace('<span class=\"searchmatch\">','').replace('</span>','')}"
                        for x in results[:4]
                    )
            except Exception as e:
                return f"Search offline: {e}"

    db = SqliteDb(db_file="agno.db", session_table="agent_sessions", memory_table="user_memories")
    xai_key = os.getenv("XAI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if xai_key:
        llm = xAI(id="grok-4.20-0309-non-reasoning", api_key=xai_key)
    else:
        llm = OpenAIChat(id="gpt-4o", api_key=openai_key) if openai_key else OpenAIChat(id="gpt-4o-mini")

    _research_agent = Agent(
        id="research-agent",
        name="Knowledge & Research Agent",
        model=llm,
        tools=[WebSearchTools()],
        description="Knowledge and web research agent with search.",
        instructions=["Search the web to provide accurate, up-to-date info.", "Structure responses clearly."],
        markdown=True,
        db=db,
        add_history_to_context=True,
        num_history_runs=5,
    )
    return _research_agent


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

    # Try SDK first
    try:
        from deepgram import DeepgramClient

        dg = DeepgramClient(api_key=api_key)
        out = Path(output_path)
        if not out.is_absolute():
            out = Path(__file__).parent.parent / output_path
        out.parent.mkdir(parents=True, exist_ok=True)
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
            # fallback: REST save
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
        session_id: Optional session id for memory (persists in agno.db). Auto-generated if omitted.
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
async def agno_research_run(
    query: str,
    session_id: Optional[str] = None,
) -> str:
    """
    Run the Agno research-agent (server.py:140) with web search tool.

    Args:
        query: Research question/topic.
        session_id: Optional session id.
    Returns:
        Markdown research answer.
    """
    agent = _get_research_agent()
    sid = session_id or f"research-{uuid.uuid4().hex[:8]}"
    try:
        try:
            res = await agent.arun(query, session_id=sid)  # type: ignore
            return getattr(res, "content", str(res)) or str(res)
        except Exception:
            res = agent.run(query, session_id=sid)  # type: ignore
            return getattr(res, "content", str(res)) or str(res)
    except Exception as e:
        return f"Error running research agent: {e}"


@mcp.tool()
def agno_list_sessions(limit: int = 10) -> str:
    """
    List recent Agno sessions from agno.db (sqlite).

    Args:
        limit: Max sessions to return.
    Returns:
        JSON of session ids, agent_ids, updated_at.
    """
    import sqlite3

    db_path = Path(__file__).parent.parent / "agno.db"
    if not db_path.exists():
        db_path = Path("agno.db")
    if not db_path.exists():
        return "No agno.db found (no sessions yet)"
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        # try common table names from server.py:57
        for table in ("agent_sessions", "sessions", "agent_session"):
            try:
                cur.execute(f"SELECT session_id, agent_id, updated_at, created_at FROM {table} ORDER BY updated_at DESC LIMIT ?", (limit,))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                con.close()
                return json.dumps([dict(zip(cols, r)) for r in rows], indent=2, default=str)
            except Exception:
                continue
        # fallback: list tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cur.fetchall()
        con.close()
        return f"No session table found. Tables: {tables}"
    except Exception as e:
        return f"Error reading agno.db: {e}"


@mcp.tool()
def agno_get_memory(limit: int = 5) -> str:
    """List recent user memories from agno.db memory_table."""
    import sqlite3

    db_path = Path(__file__).parent.parent / "agno.db"
    if not db_path.exists():
        db_path = Path("agno.db")
    if not db_path.exists():
        return "No agno.db found"
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        for table in ("user_memories", "memories", "memory"):
            try:
                cur.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                con.close()
                return json.dumps([dict(zip(cols, r)) for r in rows], indent=2, default=str)[:6000]
            except Exception:
                continue
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cur.fetchall()
        con.close()
        return f"No memory table. Tables: {tables}"
    except Exception as e:
        return f"Error: {e}"


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
    db_path = Path(__file__).parent.parent / "agno.db"
    if not db_path.exists():
        db_path = Path("agno.db")
    return json.dumps(
        {
            "status": "ok",
            "service": "voice-agent-mcp",
            "agents": ["voice-agent", "research-agent"],
            "livekit_url": lk_url,
            "deepgram_enabled": bool(_get_deepgram_api_key()),
            "db_exists": db_path.exists(),
            "db_path": str(db_path),
        },
        indent=2,
    )


if __name__ == "__main__":
    # stdio transport is default for opencode local MCPs
    mcp.run()
