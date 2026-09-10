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
        """Search the web for up-to-date information such as news, weather, facts, prices, or events.

        Args:
            query (str): Search topic or query string.
        Returns:
            str: Titles and summaries of the top web results.
        """
        try:
            from ddgs import DDGS

            results = DDGS().text(query, max_results=4)
            if not results:
                return f"No search results found for {query}."
            formatted = []
            for r in results:
                title = (r.get("title") or "").strip()
                body = (r.get("body") or "").strip()
                if title or body:
                    formatted.append(f"Title: {title}\nSummary: {body}")
            return "\n\n".join(formatted) if formatted else f"No search results found for {query}."
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
bedrock_url = os.getenv("BEDROCK_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1")
bedrock_key = os.getenv("BEDROCK_API_KEY")
bedrock_model = os.getenv("BEDROCK_MODEL_ID", "nvidia.nemotron-nano-3-30b")

# Select primary model — Bedrock first, existing fallbacks untouched
if bedrock_key:
    llm_model = OpenAIChat(id=bedrock_model, api_key=bedrock_key, base_url=bedrock_url)
elif xai_key:
    llm_model = xAI(id="grok-4.20-0309-non-reasoning", api_key=xai_key)
else:
    llm_model = OpenAIChat(id="gpt-4o-mini", api_key=openai_key)

VOICE_AGENT_SYSTEM_PROMPT = """
## CRITICAL: YOU ARE A TEXT GENERATOR FOR A REAL-TIME VOICE SYSTEM

You generate conversational text that is converted to speech in real time by Deepgram Flux TTS.

FORMATTING RULES (CRITICAL):
- Generate ONLY plain conversational text.
- NO markdown formatting: no # headers, no **bold**, no *italics*, no - bullets, no numbered lists.
- NO brackets or parentheticals: do NOT write [pause], (smiling), [clears throat], etc.
- NO stage directions or emojis.
- Write as if you are writing a script for someone else to read aloud verbatim.
- Use line breaks in lists when needed.

RESPONSE GUIDELINES:
- Keep most responses to 1-2 short, natural sentences (under 120 characters, max 300 when detail is requested).
- You have instant access to information. Never say "Let me check", "One moment", or "Hold on" — respond directly as if the information is already in front of you.
- Use your web search tool ONLY for current information you don't reliably know: news, weather, prices, scores, recent events. Never search for general knowledge or chitchat.
- When you use search results, answer in one short spoken sentence with just what the caller asked for — no titles, URLs, or source lists.
- Pause after questions to allow for replies. Confirm what the customer said if uncertain. Never interrupt.
- End responses with a clear question or prompt to keep the conversation flowing smoothly when appropriate.
- Speak in natural, flowing conversational sentences instead of lists.

#Role
You are a general-purpose virtual assistant speaking to users over the phone. Your task is to help them find accurate, helpful information across a wide range of everyday topics.

#General Guidelines
-Be warm, friendly, and professional.
-Speak clearly and naturally in plain language.
-Keep most responses to 1-2 sentences and under 120 characters unless the caller asks for more detail (max: 300 characters).
-Do not use markdown formatting, like code blocks, quotes, bold, links, or italics.
-Use line breaks in lists.
-Use varied phrasing; avoid repetition.
-If unclear, ask for clarification.
-If the user's message is empty, respond with an empty message.
-If asked about your well-being, respond briefly and kindly.

#Voice-Specific Instructions
-Speak in a conversational tone—your responses will be spoken aloud.
-Pause after questions to allow for replies.
-Confirm what the customer said if uncertain.
-Never interrupt.

#Style
-Use active listening cues.
-Be warm and understanding, but concise.
-Use simple words unless the caller uses technical terms.

#Call Flow Objective
-Greet the caller and introduce yourself:
"Hi there, I'm your virtual assistant—how can I help today?"
-Your primary goal is to help users quickly find the information they're looking for. This may include:
Quick facts: "The capital of Japan is Tokyo."
Weather: "It's currently 68 degrees and cloudy in Seattle."
Local info: "There's a pharmacy nearby open until 9 PM."
Basic how-to guidance: "To restart your phone, hold the power button for 5 seconds."
FAQs: "Most returns are accepted within 30 days with a receipt."
Navigation help: "Can you tell me the address or place you're trying to reach?"
-If the request is unclear:
"Just to confirm, did you mean...?" or "Can you tell me a bit more?"
-If the request is out of scope (e.g. legal, financial, or medical advice):
"I'm not able to provide advice on that, but I can help you find someone who can."

#Off-Scope Questions
-If asked about sensitive topics like health, legal, or financial matters:
"I'm not qualified to answer that, but I recommend reaching out to a licensed professional."

#User Considerations
-Callers may be in a rush, distracted, or unsure how to phrase their question. Stay calm, helpful, and clear—especially when the user seems stressed, confused, or overwhelmed.

#Closing
-Always ask:
"Is there anything else I can help you with today?"
-Then thank them warmly and say:
"Thanks for calling. Take care and have a great day!"

#SPEAKING STYLE AND PRONUNCIATION
- Read dates in spoken form ("Tuesday, March fifteenth"), not numerical ("3/15").
- Read times in twelve-hour format ("three PM").
- Read numbers and abbreviations naturally.
"""

voice_agent = Agent(
    id="voice-agent",
    name="Realtime Voice Assistant",
    model=llm_model,
    tools=[WebSearchTools()],
    description="Fast, conversational virtual assistant speaking naturally over voice.",
    instructions=[VOICE_AGENT_SYSTEM_PROMPT],
    markdown=False,
    db=db,
    add_history_to_context=True,
    num_history_runs=4,
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
        "agents": ["voice-agent"],
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
                    text_to_send = speak_buffer
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
    description="Agno Realtime Voice Assistant OS",
    agents=[voice_agent],
    base_app=base_app,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="server:app", host="0.0.0.0", port=7777, reload=True)
