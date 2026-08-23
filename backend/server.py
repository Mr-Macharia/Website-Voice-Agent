import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure backend directory is on sys.path and load .env files
BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load .env from backend and root
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")
load_dotenv()

import asyncio
import json
import uuid
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Request
import httpx
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
import websockets

from agno.agent import Agent
from agno.models.xai import xAI
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools import Toolkit
from livekit import api

class WebSearchTools(Toolkit):
    def __init__(self):
        super().__init__(name="web_search_tools")
        self.register(self.search_web)

    def search_web(self, query: str) -> str:
        """Search the web for up-to-date information, facts, or definitions.

        Args:
            query (str): Search topic or query string.
        Returns:
            str: Summaries and search results.
        """
        import urllib.request, urllib.parse, json
        try:
            url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json&utf8=1"
            req = urllib.request.Request(url, headers={"User-Agent": "AgnoAgentOS/1.0"})
            with urllib.request.urlopen(req, timeout=6) as response:
                data = json.loads(response.read().decode())
                results = data.get("query", {}).get("search", [])
                if not results:
                    return f"No direct search results found for {query}."
                formatted = []
                for r in results[:4]:
                    snippet = r.get("snippet", "").replace('<span class="searchmatch">', "").replace("</span>", "")
                    formatted.append(f"Title: {r.get('title')}\nSummary: {snippet}")
                return "\n\n".join(formatted)
        except Exception as e:
            return f"Search service temporarily offline: {e}"

# ---------------------------------------------------------------------------
# Database & Memory Persistence
# ---------------------------------------------------------------------------
DB_PATH = str(BACKEND_DIR / "agno.db")

db = SqliteDb(
    db_file=DB_PATH,
    session_table="agent_sessions",
    eval_table="eval_runs",
    memory_table="user_memories",
    metrics_table="metrics",
)

# ---------------------------------------------------------------------------
# Agent Definitions
# ---------------------------------------------------------------------------
xai_key = os.getenv("XAI_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

# Select primary model
if xai_key:
    llm_model = xAI(id="grok-4.20-0309-non-reasoning", api_key=xai_key)
    research_model = xAI(id="grok-4.20-0309-non-reasoning", api_key=xai_key)
else:
    llm_model = OpenAIChat(id="gpt-4o-mini", api_key=openai_key)
    research_model = OpenAIChat(id="gpt-4o", api_key=openai_key)

VOICE_AGENT_SYSTEM_PROMPT = """
## CRITICAL: YOU ARE A TEXT GENERATOR FOR A REAL-TIME VOICE SYSTEM

You generate conversational text that is converted to speech in real time by Deepgram Flux TTS.

FORMATTING RULES (CRITICAL):
- Generate ONLY plain conversational text.
- NO markdown formatting: no # headers, no **bold**, no *italics*, no - bullets, no numbered lists.
- NO brackets or parentheticals: do NOT write [pause], (smiling), [clears throat], etc.
- NO stage directions or emojis.
- Write as if you are writing a script for someone else to read aloud verbatim.

RESPONSE GUIDELINES:
- Keep most responses to 1-2 short, natural sentences (typically under 120 characters, max 300 characters when detail is requested).
- You have instant access to information. Never say "Let me check", "One moment", or "Hold on" — respond directly as if the information is already in front of you.
- End responses with a clear question or prompt to keep the conversation flowing smoothly.
- Speak in natural, flowing conversational sentences instead of lists.

## 1. ROLE AND IDENTITY
You are Brooke, an AI virtual assistant speaking with users over a real-time voice call. You help callers quickly find accurate, practical information across a wide range of everyday topics. A successful call ends with the user getting their answer clearly and concisely, or being guided to the right next step.

## 2. PERSONALITY AND TONE
Warm, friendly, confident, and professional. Match the caller's pace. Never rushed, never robotic, never overly verbose.

## 3. ENVIRONMENT AND CHANNEL
This is a live voice stream over a web and mobile connection. Audio quality may vary and background noise may occur. If a request is unclear, politely ask the caller to confirm or repeat rather than guessing.

## 4. ABOUT YOUR CALLERS
Callers are looking for quick, direct answers to everyday questions, guidance, and assistance. Speak in simple, accessible language.

## 5. SCOPE
You help with quick facts, everyday science, technology, common knowledge, and general assistance.
If asked about formal medical, legal, or financial advice, respond with: "I am not qualified to provide advice on that, but I recommend reaching out to a licensed professional."

## 6. CONVERSATIONAL APPROACH
- Greet the user warmly if they greet you.
- If the request is unclear, gently clarify: "Just to confirm, did you mean...?"
- If the user asks how you are doing, reply briefly and kindly.
- When wrapping up, ask: "Is there anything else I can help you with today?"
- Close with: "Thanks for speaking with me. Have a wonderful day!"

## 7. SPEAKING STYLE AND PRONUNCIATION
- Read dates in spoken form ("Tuesday, March fifteenth"), not numerical ("3/15").
- Read times in twelve-hour format ("three PM").
- Read numbers and abbreviations naturally.
"""

voice_agent = Agent(
    id="voice-agent",
    name="Realtime Voice Assistant",
    model=llm_model,
    description="Fast, conversational virtual assistant speaking naturally over voice.",
    instructions=[VOICE_AGENT_SYSTEM_PROMPT],
    markdown=False,
    db=db,
    add_history_to_context=True,
    num_history_runs=4,
    enable_session_summaries=False,
    add_datetime_to_context=True,
)

research_agent = Agent(
    id="research-agent",
    name="Knowledge & Research Agent",
    model=research_model,
    tools=[WebSearchTools()],
    description="Knowledge and web research agent with search capabilities.",
    instructions=[
        "Search the web to provide accurate, up-to-date information.",
        "Structure responses clearly with headings and source references."
    ],
    markdown=True,
    db=db,
    add_history_to_context=True,
    num_history_runs=5,
    enable_session_summaries=True,
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
        "agents": ["voice-agent", "research-agent"],
        "livekit_url": LIVEKIT_URL,
        "deepgram_enabled": bool(DEEPGRAM_API_KEY)
    }

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
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)) \
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
# Deepgram Nova-3 Speech-to-Text (STT) Endpoint
# ---------------------------------------------------------------------------
async def transcribe_audio_bytes(audio_bytes: bytes, content_type: str = "audio/wav") -> str:
    """Helper to transcribe raw audio bytes using Deepgram Nova-3."""
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
            "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true",
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
# ---------------------------------------------------------------------------
@base_app.websocket("/ws/voice")
async def voice_websocket(client_ws: WebSocket):
    await client_ws.accept()
    print("Voice WebSocket client connected")

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

    try:
        while True:
            message = await client_ws.receive()
            user_message = ""
            session_id = None

            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                user_message = await transcribe_audio_bytes(raw_bytes, "audio/wav")
                if not user_message:
                    await client_ws.send_json({"type": "no_speech"})
                    await client_ws.send_json({"type": "turn_complete"})
                    continue
                await client_ws.send_json({"type": "user_transcript", "text": user_message})

            elif "text" in message and message["text"]:
                raw_text = message["text"]
                try:
                    data = json.loads(raw_text)
                    msg_type = data.get("type", "text")
                    session_id = data.get("session_id", None)

                    if msg_type == "audio" and "audio" in data:
                        import base64
                        mime = data.get("mime_type", "audio/webm")
                        audio_bytes = base64.b64decode(data["audio"])
                        user_message = await transcribe_audio_bytes(audio_bytes, mime)
                        if not user_message:
                            await client_ws.send_json({"type": "no_speech"})
                            await client_ws.send_json({"type": "turn_complete"})
                            continue
                        await client_ws.send_json({"type": "user_transcript", "text": user_message})
                    elif msg_type == "ping":
                        await client_ws.send_json({"type": "pong"})
                        continue
                    else:
                        user_message = data.get("text", raw_text)
                except Exception:
                    user_message = raw_text

            if not user_message or not user_message.strip():
                continue

            print(f"\nUser [Voice Turn]: {user_message}")

            if not DEEPGRAM_API_KEY:
                reply = f"Deepgram API key not configured. Echo: {user_message}"
                await client_ws.send_json({"type": "agent_text", "text": reply})
                await client_ws.send_json({"type": "turn_complete"})
                continue

            # Ensure Deepgram TTS WebSocket is connected
            is_open = dg_ws is not None and getattr(dg_ws, "state", None) == websockets.protocol.State.OPEN
            if not is_open:
                try:
                    dg_ws = await websockets.connect(dg_url, additional_headers=dg_headers)
                    await dg_ws.recv() # Read initial Connected event
                except Exception as e:
                    print(f"[WS Voice] Reconnect Deepgram TTS failed: {e}")
                    await client_ws.send_json({"type": "error", "message": f"TTS connect failed: {e}"})
                    await client_ws.send_json({"type": "turn_complete"})
                    continue

            try:
                async def stream_agno_to_deepgram():
                    try:
                        async for chunk in voice_agent.arun(user_message, session_id=session_id, stream=True):
                            content = getattr(chunk, "content", None)
                            if content:
                                await dg_ws.send(json.dumps({
                                    "type": "Speak",
                                    "text": content
                                }))
                                await client_ws.send_json({
                                    "type": "agent_text",
                                    "text": content
                                })
                        
                        await dg_ws.send(json.dumps({"type": "Flush"}))
                    except Exception as e:
                        print(f"Error streaming Agno to Deepgram: {e}")
                        await client_ws.send_json({"type": "error", "message": str(e)})

                async def stream_deepgram_to_client():
                    try:
                        while True:
                            msg = await dg_ws.recv()
                            if isinstance(msg, bytes):
                                await client_ws.send_bytes(msg)
                            elif isinstance(msg, str):
                                parsed = json.loads(msg)
                                event_type = parsed.get("type")
                                if event_type == "SpeechMetadata":
                                    await client_ws.send_json({"type": "turn_complete"})
                                    break
                                elif event_type == "Error":
                                    print(f"[Deepgram TTS Error Event] {parsed}")
                                    await client_ws.send_json({"type": "turn_complete"})
                                    break
                    except Exception as e:
                        print(f"Error streaming Deepgram to client: {e}")

                await asyncio.gather(
                    stream_agno_to_deepgram(),
                    stream_deepgram_to_client()
                )
            except Exception as e:
                print(f"[WS Voice] Turn processing error: {e}")
                await client_ws.send_json({"type": "error", "message": f"Turn error: {str(e)}"})
                await client_ws.send_json({"type": "turn_complete"})

    except WebSocketDisconnect:
        print("Voice WebSocket client disconnected")
    except Exception as e:
        print(f"Voice WebSocket error: {e}")
    finally:
        if dg_ws is not None and getattr(dg_ws, "state", None) == websockets.protocol.State.OPEN:
            try:
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
                            "model": "nova-3"
                        }
                    },
                    "think": {
                        "provider": {
                            "type": "open_ai",
                            "model": "gpt-4o-mini"
                        },
                        "prompt": "You are a helpful, fast, natural conversational voice assistant. Keep answers concise (1-2 sentences) and suitable for direct speech output."
                    },
                    "speak": {
                        "provider": {
                            "type": "deepgram",
                            "version": "v2",
                            "model": "flux-brooke-en"
                        }
                    }
                }
            }

            await dg_ws.send(json.dumps(settings))
            conf_resp = await dg_ws.recv()
            print(f"[Deepgram Agent] Settings response: {conf_resp}")
            if isinstance(conf_resp, str):
                await client_ws.send_text(conf_resp)

            async def forward_client_to_deepgram():
                try:
                    while True:
                        msg = await client_ws.receive()
                        if "bytes" in msg and msg["bytes"]:
                            await dg_ws.send(msg["bytes"])
                        elif "text" in msg and msg["text"]:
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

            await asyncio.gather(
                forward_client_to_deepgram(),
                forward_deepgram_to_client()
            )

    except WebSocketDisconnect:
        print("Deepgram Direct Agent client disconnected")
    except Exception as e:
        print(f"Deepgram Direct Agent error: {e}")

# ---------------------------------------------------------------------------
# Initialize Agno AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    description="Agno Realtime Voice Assistant OS",
    agents=[voice_agent, research_agent],
    base_app=base_app,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="server:app", host="0.0.0.0", port=7777, reload=True)
