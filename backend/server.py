import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure backend directory is on sys.path and load .env files
BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load .env from backend and root (override so .env values win over empty preset vars)
load_dotenv(BACKEND_DIR / ".env", override=True)
load_dotenv(WORKSPACE_DIR / ".env", override=True)
load_dotenv(override=True)

import asyncio
import json
import uuid
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Request
import httpx
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
import websockets

from agno.agent import Agent
from agno.models.xai import xAI
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from livekit import api

# Shared core — persona, knowledge and tools live here so the voice agent, this
# text agent and the MCP server all use one implementation.
from core import config as core_config
from core import db as core_db
from core import guardrails
from core import knowledge as core_knowledge
from core import persona
from core import rate_limit
from core import ui_payload
from core.tools import leads as core_leads
from core.adapters.agno import SiteTools
from core.adapters import assemblyai as voice_tools
from core.tools import gmail as _gmail
from voice import llm_proxy, session_config

# ---------------------------------------------------------------------------
# Database & Memory Persistence — PostgreSQL
# ---------------------------------------------------------------------------
# Sessions, memory, metrics, knowledge metadata and leads all live in Postgres.
# Built lazily so the API still boots (and /api/info still answers) when the
# database is unreachable — important for a hosted deployment.
db = None
if core_config.DATABASE_URL:
    try:
        core_db.init_schema()
        db = core_db.get_agno_db()
        print(f"[startup] Postgres connected: sessions, memory and leads persisted")
    except Exception as e:
        print(f"[startup] WARNING: Postgres unavailable ({e}). Running without persistence.")
else:
    print("[startup] WARNING: DATABASE_URL not set. Running without persistence.")

# ---------------------------------------------------------------------------
# Agent Definitions
# ---------------------------------------------------------------------------
# Provider order, matching voice/llm_proxy.py's _providers(). Both paths pick a
# model for the same job — tool calling with conversation history — so they must
# agree, and until now they were inverted: the proxy ranked Bedrock's
# deepseek.v3.2 LAST ("its replies will be worse than silence") while this file
# ranked it FIRST for both agents.
#
# That was not theoretical. Probed directly against both endpoints:
#
#     deepseek.v3.2   emits the tool call, then leaks the raw control token
#                     "<｜DSML｜function_calls" into visible content
#     deepseek-flash  emits the tool call cleanly, no leaked tokens
#
# Visitors saw that token in the chat transcript. Bedrock stays configured as
# the last resort so the site still answers if the others are down.
#
# On deepseek-flash and reasoning_content: llm_proxy._apply_provider_quirks
# echoes an empty reasoning_content because DeepSeek once rejected follow-up
# turns that omitted it. Agno's OpenAIChat._format_message sends only role,
# content, name, tool_call_id and tool_calls, so it cannot echo that field —
# but a live probe confirms the API now accepts the follow-up either way, so no
# subclass is needed here. If DeepSeek reinstates the requirement, the symptom
# is a 400 on the turn after any tool call, and the fix is to override
# _format_message the way the proxy patches the body.
# Agno maps the system role to "developer" (OpenAI's newer name for it) for
# every OpenAIChat model. DeepSeek's API rejects that variant outright:
#
#     422 messages[0].role: unknown variant `developer`, expected one of
#     `system`, `user`, `assistant`, `tool`, `latest_reminder`
#
# Every request fails, so this map is not optional. It only names the roles
# Agno already sends, mapping system back to the standard spelling.
_DEEPSEEK_ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}

if core_config.DEEPSEEK_API_KEY:
    llm_model = OpenAIChat(
        id=core_config.DEEPSEEK_MODEL_ID or "deepseek-flash",
        api_key=core_config.DEEPSEEK_API_KEY,
        base_url=core_config.DEEPSEEK_BASE_URL.rstrip("/"),
        role_map=_DEEPSEEK_ROLE_MAP,
    )
elif core_config.XAI_API_KEY:
    llm_model = xAI(
        id=core_config.XAI_MODEL_ID or "grok-4.6",
        api_key=core_config.XAI_API_KEY,
    )
elif core_config.OPENAI_API_KEY:
    llm_model = OpenAIChat(id="gpt-4o-mini", api_key=core_config.OPENAI_API_KEY)
else:
    llm_model = OpenAIChat(
        id=core_config.BEDROCK_MODEL_ID or "deepseek.v3.2",
        api_key=core_config.BEDROCK_API_KEY,
        base_url=core_config.BEDROCK_BASE_URL.rstrip("/"),
    )

print(f"[startup] text/voice model: {getattr(llm_model, 'id', '?')}")

def _clean_agent_output(run_output) -> None:
    """Strip leaked model control tokens from a finished reply.

    guardrails.clean_output was already wired into all three other channels —
    the Deepgram bridge (stream_agno_to_deepgram), the LiveKit worker, and the
    AssemblyAI proxy's _ReplyCleaner — but never the AgentOS text path, so the
    website chat was the one surface with no filter at all. Visitors saw
    "<｜DSML｜function_calls" in the transcript.

    Agno runs post_hooks after the content deltas have streamed, so this cannot
    unsend a token mid-stream. It does fix the RunCompleted payload, which the
    frontend uses to replace the message wholesale, plus the copied transcript
    and the persisted session. With deepseek-flash primary the token is not
    emitted at all; this is the guard for the Bedrock last resort, which does
    emit it.

    Never raises: a cleaning failure must not take down a reply.
    """
    try:
        content = getattr(run_output, "content", None)
        if isinstance(content, str) and content:
            cleaned = guardrails.clean_output(content)
            if cleaned != content:
                run_output.content = cleaned
    except Exception as e:
        print(f"[guardrails] WARNING: could not clean agent output ({e})")


# Prompts now come from core/persona.py — one identity, layered per channel.
# The old inline prompt described a "general-purpose virtual assistant speaking
# over the phone", which is wrong for a site about one person.
VOICE_AGENT_SYSTEM_PROMPT = persona.for_voice()
TEXT_AGENT_SYSTEM_PROMPT = persona.for_text()

_site_tools = SiteTools()
_knowledge = core_knowledge.get_knowledge()

# Gmail via Composio, scoped by GMAIL_SCOPE (default: drafts only). Composio
# returns plain callables, which Agno accepts alongside a Toolkit.
_agent_tools = [_site_tools, *_gmail.get_tools()]

# Voice agent — drives the /ws/voice bridge, so it gets the spoken formatting
# rules (no markdown, short sentences, spoken dates).
voice_agent = Agent(
    id="voice-agent",
    # Same name as text_agent on purpose: one assistant, two channels. The id
    # is what distinguishes them, and persona.py's shared identity says "You
    # are Clyde" — a second display name would put the split-identity problem
    # that module exists to prevent back into the agent picker.
    name="Clyde",
    model=llm_model,
    tools=_agent_tools,
    description=f"Clyde on the voice channel, for {core_config.OWNER_NAME}'s website.",
    instructions=[VOICE_AGENT_SYSTEM_PROMPT],
    post_hooks=[_clean_agent_output],
    markdown=False,
    db=db,
    knowledge=_knowledge,
    search_knowledge=bool(_knowledge),
    add_history_to_context=True,
    num_history_runs=4,
    enable_session_summaries=False,
    add_datetime_to_context=True,
)

# Text agent — what the website chat talks to. Same identity and tools, but
# written rather than spoken, and knowledge is attached directly so Agno emits
# extra_data.references, which the frontend already renders as citations.
text_agent = Agent(
    id="site-agent",
    name="Clyde",
    model=llm_model,
    tools=_agent_tools,
    description=f"Clyde answers questions about {core_config.OWNER_NAME} and books meetings.",
    instructions=[TEXT_AGENT_SYSTEM_PROMPT],
    post_hooks=[_clean_agent_output],
    markdown=True,
    db=db,
    knowledge=_knowledge,
    search_knowledge=bool(_knowledge),
    add_history_to_context=True,
    num_history_runs=6,
    enable_session_summaries=False,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Base FastAPI Application & Middleware
# ---------------------------------------------------------------------------
base_app = FastAPI(
    title="Agno Voice AgentOS",
    description="Agno AgentOS server with LiveKit & Deepgram Realtime Voice Streaming",
    version="1.0.0"
)

base_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://voice-agent.livekit.cloud")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "secret01234567890123456789012345678901")

# ---------------------------------------------------------------------------
# Info & Status Endpoints
# ---------------------------------------------------------------------------
@base_app.get("/api/info")
async def info_check():
    return {
        "status": "ok",
        "service": "agno-agent-os",
        "agents": ["site-agent", "voice-agent"],
        "livekit_url": LIVEKIT_URL,
        "deepgram_enabled": bool(DEEPGRAM_API_KEY),
        # Features degrade independently; this says which are actually live.
        "features": {
            "persistence": db is not None,
            "knowledge": _knowledge is not None,
            "booking": core_config.booking_available(),
            "leads": core_config.leads_available(),
            "lead_notification": core_config.lead_notification_available(),
            "gmail": core_config.gmail_available(),
            "gmail_scope": core_config.GMAIL_SCOPE if core_config.gmail_available() else None,
        },
    }

# ---------------------------------------------------------------------------
# Voice — AssemblyAI Voice Agent API
#
# The browser holds the WebSocket to AssemblyAI directly; the backend serves
# three things it can't do itself: a token (the API key must never reach the
# client), the session config (the persona lives in Python), and the tool calls
# (they need Postgres, pgvector and Composio).
# ---------------------------------------------------------------------------
ASSEMBLYAI_AGENTS_URL = "https://agents.assemblyai.com/v1"


@base_app.get("/api/voice/token")
async def voice_token():
    """Mint a single-use token and return it with the session config.

    Tokens are single-use and short-lived, so the client fetches a fresh one
    for every connection — including reconnects.
    """
    if not core_config.ASSEMBLYAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Voice isn't configured. ASSEMBLYAI_API_KEY is missing.",
        )

    # The agent must be stored, not configured inline: the API rejects a custom
    # llm on session.update, and the managed model it would otherwise fall back
    # to knows nothing about the owner. Run scripts/provision_agent.py.
    if not core_config.ASSEMBLYAI_AGENT_ID:
        raise HTTPException(
            status_code=503,
            detail=(
                "Voice isn't configured. ASSEMBLYAI_AGENT_ID is missing — run "
                "scripts/provision_agent.py to create the stored agent."
            ),
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ASSEMBLYAI_AGENTS_URL}/token",
                params={
                    "expires_in_seconds": 300,
                    "max_session_duration_seconds": 3600,
                },
                # This product wants a Bearer prefix; AssemblyAI's other APIs
                # take the raw key. Mixing them up gives a 401.
                headers={"Authorization": f"Bearer {core_config.ASSEMBLYAI_API_KEY}"},
            )
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail="Couldn't reach the voice service. Check your connection and try again.",
        ) from e

    if resp.status_code == 401:
        raise HTTPException(
            status_code=502,
            detail="The AssemblyAI API key was rejected. Check ASSEMBLYAI_API_KEY.",
        )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail="Couldn't start a voice session right now. Please try again.",
        )

    token = resp.json().get("token")
    if not token:
        raise HTTPException(status_code=502, detail="Voice service returned no token.")

    return {"token": token, "session": session_config.build_session()}


class LeadFormRequest(BaseModel):
    """A lead typed into the chat form rather than dictated to the agent.

    Lengths are capped at the edge. The model-driven path is bounded by what a
    conversation plausibly contains; this endpoint is public and
    unauthenticated like /api/voice/tool, so an open text field is an open text
    field. Pydantic rejects anything longer before it reaches Postgres. The
    frontend enforces the same limits in Zod so the two cannot drift.
    """

    name: str = Field("", max_length=200)
    email: str = Field("", max_length=320)  # RFC 5321 maximum
    company: str = Field("", max_length=200)
    message: str = Field("", max_length=4000)
    session_id: Optional[str] = Field(None, max_length=200)


@base_app.post("/api/leads")
async def submit_lead(req: LeadFormRequest, request: Request):
    """Save a lead submitted through the chat form.

    Returns {ok, message} rather than a bare string. The form branches on the
    outcome to choose between a confirmation and a retry, and parsing prose to
    discover whether a write succeeded is how silent data loss happens.

    Validation is repeated here rather than trusted from the client: the
    endpoint is reachable without the form.
    """
    # Public and unauthenticated: every accepted request writes a row and
    # emails the owner, so the count has to be capped before any work happens.
    retry_after = rate_limit.check(
        request, rate_limit.LEADS_LIMIT, rate_limit.LEADS_WINDOW
    )
    if retry_after is not None:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={
                "ok": False,
                "message": "That's a few too many submissions — give it a minute and try again.",
            },
        )

    name = req.name.strip()
    email = req.email.strip()

    # Same floor as capture_lead: something to identify them by.
    if not (name or email):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": "Add your name or your email."},
        )
    if email and not core_leads._valid_email(email):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": "That email doesn't look right."},
        )

    result = await core_leads.capture_lead(
        name=name,
        email=email,
        company=req.company.strip(),
        intent="chat form",
        message=req.message.strip(),
        session_id=req.session_id,
        # Distinct from the model-driven source="text": these were typed by the
        # visitor, not transcribed by the model, so they stay attributable.
        source="text-form",
    )

    payload = ui_payload.extract(result) or {}
    saved = payload.get("type") == "lead_saved"
    return {
        "ok": saved,
        "lead_id": payload.get("lead_id"),
        # On failure capture_lead's own sentence is the useful message; it
        # already explains what went wrong in plain English.
        "message": (
            "Thanks — your details are with Gichogu and he'll be in touch."
            if saved
            else ui_payload.strip_payload(result)
        ),
    }


class VoiceToolRequest(BaseModel):
    name: str
    arguments: dict = {}


@base_app.post("/api/voice/tool")
async def voice_tool(req: VoiceToolRequest, request: Request):
    """Run a tool the agent asked for and return the result.

    The browser relays tool.call here because the tools need the database, the
    knowledge base and the Composio session. Failures come back as readable
    text rather than errors — the agent reads the result aloud and recovers,
    where a 500 would leave the visitor in silence.
    """
    # Same exposure as /api/leads. The ceiling is high enough that a real
    # conversation never reaches it, and the failure stays speakable so the
    # agent recovers out loud rather than going silent.
    if rate_limit.check(
        request, rate_limit.VOICE_TOOL_LIMIT, rate_limit.VOICE_TOOL_WINDOW
    ) is not None:
        return {
            "result": "That tool is being called too quickly. Tell the visitor "
            "to try again in a moment and carry on."
        }

    # `ui` carries a structured payload when the tool has one to draw (the
    # booking card). `result` is unchanged: it is what the agent speaks, and
    # the marker is always stripped from it.
    result, ui = await voice_tools.dispatch(req.name, req.arguments)
    return {"result": result, "ui": ui}


@base_app.post("/api/llm/chat/completions")
async def voice_llm_proxy(request: Request):
    """OpenAI-compatible endpoint that AssemblyAI calls for every reply.

    Public by necessity — AssemblyAI calls it server-to-server — so it is
    guarded by a shared secret sent as the llm[].api_key.
    """
    if not llm_proxy.authorized(request.headers.get("authorization")):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from e

    return StreamingResponse(
        llm_proxy.stream_completion(payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# LiveKit Token Generation Endpoints
# ---------------------------------------------------------------------------
class TokenRequest(BaseModel):
    room: Optional[str] = "voice-agent-room"
    identity: Optional[str] = None
    name: Optional[str] = None

@base_app.post("/api/livekit/token")
@base_app.get("/api/livekit/token")
async def generate_livekit_token(
    room: str = Query("voice-agent-room"),
    identity: Optional[str] = Query(None),
    name: Optional[str] = Query(None)
):
    try:
        user_identity = identity or f"user-{uuid.uuid4().hex[:8]}"
        user_name = name or user_identity

        api_key = os.getenv("LIVEKIT_API_KEY", LIVEKIT_API_KEY)
        api_secret = os.getenv("LIVEKIT_API_SECRET", LIVEKIT_API_SECRET)
        lk_url = os.getenv("LIVEKIT_URL", LIVEKIT_URL)

        token = api.AccessToken(api_key=api_key, api_secret=api_secret) \
            .with_identity(user_identity) \
            .with_name(user_name) \
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True)) \
            .to_jwt()

        return {
            "token": token,
            "url": lk_url,
            "room": room,
            "identity": user_identity,
            "name": user_name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create LiveKit token: {str(e)}")

# ---------------------------------------------------------------------------
# Deepgram Flux-General Speech-to-Text (STT) Endpoint — 48k linear16 primary
# ---------------------------------------------------------------------------
# Helper to check if a Deepgram websockets connection is open (handles websockets 13+ vs older)
def _is_dg_open(ws) -> bool:
    if ws is None:
        return False
    try:
        if hasattr(ws, "state"):
            # websockets 13+ uses State.OPEN
            try:
                return ws.state == websockets.protocol.State.OPEN
            except Exception:
                # Some forks expose .state as int/str
                return str(getattr(ws, "state", "")) == "State.OPEN" or getattr(ws, "open", False)
        if hasattr(ws, "open"):
            return bool(ws.open)
        if hasattr(ws, "closed"):
            return not bool(ws.closed)
    except Exception:
        return False
    return True


async def transcribe_audio_bytes(audio_bytes: bytes, content_type: str = "audio/wav") -> str:
    """Helper to transcribe raw audio bytes using Deepgram Nova-3 (flux-general-en 400s on this account)."""
    if not DEEPGRAM_API_KEY:
        raise ValueError("DEEPGRAM_API_KEY is not configured")
    
    # Auto-detect audio format from header magic bytes
    if audio_bytes.startswith(b"RIFF"):
        clean_content_type = "audio/wav"
    elif audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        clean_content_type = "audio/webm"
    elif audio_bytes.startswith(b"OggS"):
        clean_content_type = "audio/ogg"
    elif audio_bytes.startswith(b"fLaC"):
        clean_content_type = "audio/flac"
    else:
        clean_content_type = content_type.split(";")[0].strip() or "audio/wav"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        dg_res = await client.post(
            "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language=en-US",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": clean_content_type
            },
            content=audio_bytes
        )
        
        if dg_res.status_code != 200:
            print(f"Deepgram STT error ({clean_content_type}): {dg_res.status_code} {dg_res.text}")
            return ""
        
        res_data = dg_res.json()
        try:
            transcript = res_data["results"]["channels"][0]["alternatives"][0]["transcript"]
            return transcript.strip()
        except (KeyError, IndexError):
            return ""

@base_app.post("/api/stt")
async def speech_to_text(request: Request):
    try:
        audio_data = await request.body()
        if not audio_data:
            raise HTTPException(status_code=400, detail="Empty audio payload")
        
        content_type = request.headers.get("content-type", "audio/webm")
        transcript = await transcribe_audio_bytes(audio_data, content_type)
        print(f"[STT API] Transcribed ({len(audio_data)} bytes): \"{transcript}\"")
        return {"transcript": transcript}
    except Exception as e:
        print(f"STT API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Realtime Deepgram Voice WebSocket Bridge (Single WebSocket Audio + Text)
# Agno think (no Deepgram think) — Deepgram is pure STT/TTS, AgentOS is the LLM.
# Borrowed pattern from Deepgram FastAPI example: persistent DG TTS WS + coalesced Speak + jitter-aware relay.
# ---------------------------------------------------------------------------
VOICE_CLIENTS_ACTIVE = 0

@base_app.websocket("/ws/voice")
async def voice_websocket(client_ws: WebSocket):
    await client_ws.accept()
    global VOICE_CLIENTS_ACTIVE
    VOICE_CLIENTS_ACTIVE += 1
    print(f"Voice WebSocket client connected (active: {VOICE_CLIENTS_ACTIVE})")

    dg_url = "wss://api.deepgram.com/v2/speak?model=flux-brooke-en&encoding=linear16&sample_rate=24000"
    dg_headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

    dg_ws = None
    if DEEPGRAM_API_KEY:
        try:
            dg_ws = await websockets.connect(dg_url, additional_headers=dg_headers)
            welcome_msg = await dg_ws.recv()
            print(f"[WS Voice] Connected persistent Deepgram Flux TTS: {welcome_msg}")
        except Exception as e:
            print(f"[WS Voice] Failed to pre-connect Deepgram Flux TTS: {e}")
            dg_ws = None

    # Turn task handling with interrupt concurrency — allows barge-in while TTS is streaming
    turn_task: Optional[asyncio.Task] = None
    last_agent_text = ""  # full text of this connection's most recent reply (echo detection)

    async def handle_turn(user_message: str, session_id: Optional[str]):
        # Ensure Deepgram TTS WebSocket is connected (robust helper)
        nonlocal dg_ws, last_agent_text
        reply_parts: list = []
        if not _is_dg_open(dg_ws):
            try:
                dg_ws = await websockets.connect(dg_url, additional_headers=dg_headers)
                welcome = await dg_ws.recv()  # Read initial Connected event
                print(f"[WS Voice] Reconnected Deepgram Flux TTS: {welcome}")
            except Exception as e:
                print(f"[WS Voice] Reconnect Deepgram TTS failed: {e}")
                await client_ws.send_json({"type": "error", "message": f"TTS connect failed: {e}"})
                await client_ws.send_json({"type": "turn_complete"})
                return
        try:
            # Coalesced Speak streaming: reduces glitch from per-token Speak flood, keeps jitter low.
            async def stream_agno_to_deepgram():
                speak_buffer = ""
                prev_ends_with_space = True
                last_send = asyncio.get_event_loop().time()

                async def _flush_speak(force: bool = False):
                    nonlocal speak_buffer, prev_ends_with_space, last_send
                    if not speak_buffer:
                        return
                    if not force and len(speak_buffer) < 24:
                        if speak_buffer.strip() and speak_buffer.strip()[-1] not in ".!?":
                            return
                    # Strip any URL the agent invented rather than got from a
                    # tool. Applied at flush, where text is already coalesced,
                    # so a URL split across tokens is still matched.
                    text_to_send = guardrails.clean_output(speak_buffer)
                    if not prev_ends_with_space and text_to_send and not text_to_send[0].isspace() and text_to_send[0] not in ".,!?;:')\"":
                        text_to_send = " " + text_to_send
                    prev_ends_with_space = text_to_send.endswith((" ", "\n", "\t")) if text_to_send else prev_ends_with_space
                    try:
                        await dg_ws.send(json.dumps({"type": "Speak", "text": text_to_send}))
                    except asyncio.CancelledError:
                        raise
                    except Exception as se:
                        print(f"[WS Voice] Speak send failed: {se}")
                    speak_buffer = ""
                    last_send = asyncio.get_event_loop().time()

                try:
                    async for chunk in voice_agent.arun(user_message, session_id=session_id, stream=True):
                        content = getattr(chunk, "content", None)
                        if content:
                            await client_ws.send_json({"type": "agent_text", "text": content})
                            reply_parts.append(content)
                            speak_buffer += content
                            now = asyncio.get_event_loop().time()
                            should_flush = (
                                len(speak_buffer) >= 80
                                or speak_buffer.strip().endswith((".", "!", "?", ":", ";"))
                                or (len(speak_buffer) >= 24 and (now - last_send) > 0.06 and " " in speak_buffer)
                            )
                            if should_flush:
                                await _flush_speak(force=False)
                    if speak_buffer:
                        await _flush_speak(force=True)
                    # Only Flush if not cancelled
                    try:
                        await dg_ws.send(json.dumps({"type": "Flush"}))
                    except asyncio.CancelledError:
                        raise
                    except Exception as fe:
                        print(f"[WS Voice] Flush failed: {fe}")
                except asyncio.CancelledError:
                    print("[WS Voice] stream_agno cancelled by interrupt")
                    try:
                        await dg_ws.send(json.dumps({"type": "Interrupt"}))
                    except Exception:
                        pass
                    raise
                except Exception as e:
                    print(f"Error streaming Agno to Deepgram: {e}")
                    try:
                        await client_ws.send_json({"type": "error", "message": str(e)})
                    except Exception:
                        pass

            async def stream_deepgram_to_client():
                try:
                    while True:
                        try:
                            msg = await asyncio.wait_for(dg_ws.recv(), timeout=10.0)
                        except asyncio.TimeoutError:
                            print("[WS Voice] TTS recv timeout — ending turn to avoid stuck thinking")
                            try:
                                await client_ws.send_json({"type": "turn_complete"})
                            except Exception:
                                pass
                            break
                        if isinstance(msg, bytes):
                            if len(msg) < 960:
                                continue
                            await client_ws.send_bytes(msg)
                        elif isinstance(msg, str):
                            parsed = json.loads(msg)
                            event_type = parsed.get("type")
                            if event_type == "Flushed":
                                try:
                                    deadline = asyncio.get_event_loop().time() + 1.5
                                    while True:
                                        remaining = deadline - asyncio.get_event_loop().time()
                                        if remaining <= 0:
                                            break
                                        try:
                                            trailing = await asyncio.wait_for(dg_ws.recv(), timeout=remaining)
                                        except asyncio.TimeoutError:
                                            break
                                        if isinstance(trailing, bytes):
                                            if len(trailing) < 960:
                                                continue
                                            await client_ws.send_bytes(trailing)
                                        elif isinstance(trailing, str):
                                            try:
                                                t_parsed = json.loads(trailing)
                                            except Exception:
                                                continue
                                            t_type = t_parsed.get("type")
                                            if t_type == "SpeechMetadata":
                                                break
                                            elif t_type == "Error":
                                                print(f"[Deepgram TTS Error Event] {t_parsed}")
                                                await client_ws.send_json({"type": "error", "message": t_parsed.get("description", str(t_parsed))})
                                                break
                                except asyncio.CancelledError:
                                    raise
                                except Exception as de:
                                    print(f"[WS Voice] Flushed drain error: {de}")
                                await client_ws.send_json({"type": "turn_complete"})
                                break
                            elif event_type == "SpeechMetadata":
                                await client_ws.send_json({"type": "turn_complete"})
                                break
                            elif event_type == "SpeechInterrupted":
                                print(f"[Deepgram TTS Interrupted] {parsed}")
                                await client_ws.send_json({"type": "turn_complete"})
                                break
                            elif event_type == "Error":
                                print(f"[Deepgram TTS Error Event] {parsed}")
                                await client_ws.send_json({"type": "error", "message": parsed.get("description", str(parsed))})
                                await client_ws.send_json({"type": "turn_complete"})
                                break
                            elif event_type == "Warning":
                                print(f"[Deepgram TTS Warning] {parsed}")
                except asyncio.CancelledError:
                    print("[WS Voice] stream_deepgram cancelled by interrupt")
                    raise
                except Exception as e:
                    print(f"Error streaming Deepgram to client: {e}")
                    try:
                        await client_ws.send_json({"type": "turn_complete"})
                    except Exception:
                        pass

            try:
                await asyncio.wait_for(asyncio.gather(stream_agno_to_deepgram(), stream_deepgram_to_client()), timeout=60.0)
                last_agent_text = "".join(reply_parts)
            except asyncio.TimeoutError:
                print("[WS Voice] Turn timeout (60s) — forcing turn_complete")
                try:
                    await client_ws.send_json({"type": "error", "message": "Response timed out, please try again"})
                    await client_ws.send_json({"type": "turn_complete"})
                except Exception:
                    pass
        except asyncio.CancelledError:
            print("[WS Voice] Turn cancelled")
            try:
                await client_ws.send_json({"type": "turn_complete"})
            except Exception:
                pass
            raise
        except Exception as e:
            print(f"[WS Voice] Turn processing error: {e}")
            try:
                await client_ws.send_json({"type": "error", "message": f"Turn error: {str(e)}"})
                await client_ws.send_json({"type": "turn_complete"})
            except Exception:
                pass

    try:
        recv_task = asyncio.create_task(client_ws.receive())
        while True:
            # Wait for either next client message or current turn completion
            wait_tasks = [recv_task]
            if turn_task and not turn_task.done():
                wait_tasks.append(turn_task)
            done, _ = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

            if recv_task in done:
                try:
                    message = recv_task.result()
                except WebSocketDisconnect:
                    print("Voice WebSocket client disconnected (recv)")
                    if turn_task and not turn_task.done():
                        turn_task.cancel()
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            pass
                    break
                except Exception as e:
                    msg = str(e).lower()
                    if "disconnect" in msg and ("receive" in msg or isinstance(e, RuntimeError)):
                        print("Voice WebSocket client disconnected (recv)")
                        if turn_task and not turn_task.done():
                            turn_task.cancel()
                            try:
                                await turn_task
                            except asyncio.CancelledError:
                                pass
                        break
                    print(f"Voice WS recv error: {e}")
                    recv_task = asyncio.create_task(client_ws.receive())
                    continue
                if message.get("type") == "websocket.disconnect" or ("code" in message and "text" not in message and "bytes" not in message):
                    print("Voice WebSocket client disconnected (recv)")
                    if turn_task and not turn_task.done():
                        turn_task.cancel()
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            pass
                    break
                # Schedule next recv immediately
                recv_task = asyncio.create_task(client_ws.receive())

                user_message = ""
                session_id = None
                is_interrupt = False
                from_voice = False

                if "bytes" in message and message["bytes"]:
                    raw_bytes = message["bytes"]
                    try:
                        user_message = await transcribe_audio_bytes(raw_bytes, "audio/wav")
                    except Exception as e:
                        print(f"[STT] transcribe failed, recovering turn: {e}")
                        user_message = ""
                    if not user_message:
                        await client_ws.send_json({"type": "no_speech"})
                        await client_ws.send_json({"type": "turn_complete"})
                        continue
                    await client_ws.send_json({"type": "user_transcript", "text": user_message})
                    from_voice = True
                elif "text" in message and message["text"]:
                    raw_text = message["text"]
                    try:
                        data = json.loads(raw_text)
                        msg_type = data.get("type", "text")
                        session_id = data.get("session_id", None)
                        if msg_type == "audio" and "audio" in data:
                            import base64
                            mime = data.get("mime_type", "audio/webm")
                            try:
                                audio_bytes = base64.b64decode(data["audio"])
                                user_message = await transcribe_audio_bytes(audio_bytes, mime)
                            except Exception as e:
                                print(f"[STT] transcribe failed, recovering turn: {e}")
                                user_message = ""
                            if not user_message:
                                await client_ws.send_json({"type": "no_speech"})
                                await client_ws.send_json({"type": "turn_complete"})
                                continue
                            await client_ws.send_json({"type": "user_transcript", "text": user_message})
                            from_voice = True
                        elif msg_type in ("ping", "keepalive", "keepAlive"):
                            await client_ws.send_json({"type": "pong"})
                            continue
                        elif msg_type in ("interrupt", "Interrupt", "barge-in", "barge_in", "stop"):
                            is_interrupt = True
                        else:
                            user_message = data.get("text", raw_text)
                    except Exception:
                        # Fallback: treat raw_text as user message
                        try:
                            # Check if it's still an interrupt JSON that failed parse? already handled
                            user_message = raw_text
                        except Exception:
                            user_message = raw_text

                if is_interrupt:
                    print("[WS Voice] Interrupt received — cancelling current turn")
                    if turn_task and not turn_task.done():
                        turn_task.cancel()
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            pass
                        turn_task = None
                    # Also signal Deepgram to stop current synthesis
                    if _is_dg_open(dg_ws):
                        try:
                            await dg_ws.send(json.dumps({"type": "Interrupt"}))
                        except Exception as ie:
                            print(f"[WS Voice] Interrupt send failed: {ie}")
                    await client_ws.send_json({"type": "interrupted"})
                    # Also ensure we send turn_complete so frontend can reset, if not already sent by cancelled turn
                    # The cancelled turn's handler already sent turn_complete; this is extra safety
                    continue

                if not user_message or not user_message.strip():
                    continue

                if from_voice and last_agent_text:
                    norm_msg = " ".join(user_message.lower().split())
                    norm_reply = " ".join(last_agent_text.lower().split())
                    if len(norm_msg) >= 8 and (norm_msg in norm_reply or norm_reply in norm_msg):
                        print(f"[WS Voice] Dropping self-echo turn: \"{user_message}\"")
                        await client_ws.send_json({"type": "no_speech"})
                        await client_ws.send_json({"type": "turn_complete"})
                        continue

                print(f"\nUser [Voice Turn]: {user_message}")

                if not DEEPGRAM_API_KEY:
                    reply = f"Deepgram API key not configured. Echo: {user_message}"
                    await client_ws.send_json({"type": "agent_text", "text": reply})
                    await client_ws.send_json({"type": "turn_complete"})
                    continue

                # If previous turn still running (should not happen without interrupt), cancel it
                if turn_task and not turn_task.done():
                    print("[WS Voice] New turn while previous running — cancelling previous")
                    turn_task.cancel()
                    try:
                        await turn_task
                    except asyncio.CancelledError:
                        pass
                    turn_task = None
                    if _is_dg_open(dg_ws):
                        try:
                            await dg_ws.send(json.dumps({"type": "Interrupt"}))
                        except Exception:
                            pass
                turn_task = asyncio.create_task(handle_turn(user_message, session_id))

            if turn_task and turn_task in done:
                try:
                    await turn_task
                except asyncio.CancelledError:
                    print("[WS Voice] Turn task cancelled (done)")
                except Exception as e:
                    print(f"[WS Voice] Turn task error: {e}")
                turn_task = None

    except WebSocketDisconnect:
        print("Voice WebSocket client disconnected")
    except Exception as e:
        print(f"Voice WebSocket error: {e}")
    finally:
        VOICE_CLIENTS_ACTIVE = max(0, VOICE_CLIENTS_ACTIVE - 1)
        print(f"Voice WebSocket client disconnected (active: {VOICE_CLIENTS_ACTIVE})")
        if 'recv_task' in locals() and recv_task and not recv_task.done():
            recv_task.cancel()
            try:
                await recv_task
            except asyncio.CancelledError:
                pass
        if turn_task and not turn_task.done():
            turn_task.cancel()
            try:
                await turn_task
            except asyncio.CancelledError:
                pass
        try:
            if _is_dg_open(dg_ws):
                await dg_ws.close()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Deepgram Native Voice Agent WebSocket Bridge (wss://agent.deepgram.com)
# ---------------------------------------------------------------------------
@base_app.websocket("/ws/deepgram-agent")
async def deepgram_agent_websocket(client_ws: WebSocket):
    await client_ws.accept()
    print("Deepgram Direct Agent WebSocket client connected")

    if not DEEPGRAM_API_KEY:
        await client_ws.send_json({"type": "error", "message": "DEEPGRAM_API_KEY is not configured"})
        await client_ws.close()
        return

    dg_agent_url = "wss://agent.deepgram.com/v1/agent/converse"
    dg_headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

    try:
        async with websockets.connect(dg_agent_url, additional_headers=dg_headers) as dg_ws:
            welcome = await dg_ws.recv()
            print(f"[Deepgram Agent] Welcome: {welcome}")

            # Settings without think — pure listen/speak transport, think handled by Agno / client
            # Aligned to user's approved Settings: 48k in, flux-general-en listen, flux-brooke-en speak
            settings = {
                "type": "Settings",
                "audio": {
                    "input": {
                        "encoding": "linear16",
                        "sample_rate": 48000
                    },
                    "output": {
                        "encoding": "linear16",
                        "sample_rate": 24000,
                        "container": "none"
                    }
                },
                "agent": {
                    "listen": {
                        "provider": {
                            "type": "deepgram",
                            "model": "flux-general-en"
                        }
                    },
                    "speak": {
                        "provider": {
                            "type": "deepgram",
                            "version": "v2",
                            "model": "flux-brooke-en"
                        }
                    }
                },
                "greeting": "Hello! How may I help you?"
            }

            await dg_ws.send(json.dumps(settings))
            conf_resp = await dg_ws.recv()
            print(f"[Deepgram Agent] Settings response: {conf_resp}")
            if isinstance(conf_resp, str):
                await client_ws.send_text(conf_resp)

            # KeepAlive task: Deepgram agent expects KeepAlive every ~5s when idle
            async def keepalive_loop():
                try:
                    while True:
                        await asyncio.sleep(5)
                        if _is_dg_open(dg_ws):
                            try:
                                await dg_ws.send(json.dumps({"type": "KeepAlive"}))
                            except Exception:
                                break
                        else:
                            break
                except asyncio.CancelledError:
                    pass

            async def forward_client_to_deepgram():
                try:
                    while True:
                        msg = await client_ws.receive()
                        if "bytes" in msg and msg["bytes"]:
                            await dg_ws.send(msg["bytes"])
                        elif "text" in msg and msg["text"]:
                            # Forward JSON controls (Interrupt, KeepAlive proxied) verbatim
                            await dg_ws.send(msg["text"])
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    print(f"Error client->deepgram: {e}")

            async def forward_deepgram_to_client():
                try:
                    async for msg in dg_ws:
                        if isinstance(msg, bytes):
                            await client_ws.send_bytes(msg)
                        elif isinstance(msg, str):
                            await client_ws.send_text(msg)
                except Exception as e:
                    print(f"Error deepgram->client: {e}")

            ka_task = asyncio.create_task(keepalive_loop())
            try:
                await asyncio.gather(
                    forward_client_to_deepgram(),
                    forward_deepgram_to_client()
                )
            finally:
                ka_task.cancel()
                try:
                    await ka_task
                except asyncio.CancelledError:
                    pass

    except WebSocketDisconnect:
        print("Deepgram Direct Agent client disconnected")
    except Exception as e:
        print(f"Deepgram Direct Agent error: {e}")

# ---------------------------------------------------------------------------
# Initialize Agno AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    description=f"{core_config.OWNER_NAME} — personal site agent",
    # text_agent first: the frontend auto-selects the first agent when no
    # ?agent= is in the URL, and the website chat should land on it.
    agents=[text_agent, voice_agent],
    # Registering knowledge mounts /knowledge/* REST endpoints for inspecting
    # and managing indexed content.
    knowledge=[_knowledge] if _knowledge else None,
    base_app=base_app,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="server:app", host="0.0.0.0", port=7777, reload=True)
