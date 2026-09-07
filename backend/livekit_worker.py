"""
LiveKit Voice Agent Worker — Real-time WebRTC with Deepgram Flux TTS
Uses LiveKit Agents 1.x AgentServer pattern with STT/LLM/TTS/VAD.
Unified voice: flux-brooke-en (Deepgram Flux v2)
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env", override=True)
load_dotenv(WORKSPACE_DIR / ".env", override=True)
load_dotenv(override=True)

from livekit.agents import AgentServer, AgentSession, Agent, inference, room_io
from livekit.plugins import deepgram

# Keep Agno for reference / future hybrid; not used directly in AgentSession LLM
# (AgentSession LLM is livekit.plugins.openai.LLM for low-latency streaming)
from agno.db.sqlite import SqliteDb  # noqa: F401 — kept for parity with server.py

logger = logging.getLogger("voice-agent-worker")
logging.basicConfig(level=logging.INFO)

DB_PATH = str(BACKEND_DIR / "agno.db")
db = SqliteDb(
    db_file=DB_PATH,
    session_table="agent_sessions",
    memory_table="user_memories",
)

# ---------------------------------------------------------------------------
# LLM selection — mirrors server.py but for LiveKit pipeline
# LiveKit plugins.openai.LLM is OpenAI-compatible, so xAI works via base_url
# ---------------------------------------------------------------------------
def _create_llm():
    bedrock_url = os.getenv("BEDROCK_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1")
    bedrock_key = os.getenv("BEDROCK_API_KEY")
    bedrock_model = os.getenv("BEDROCK_MODEL_ID", "nvidia.nemotron-nano-3-30b")
    xai_key = os.getenv("XAI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if bedrock_key:
        from livekit.plugins import openai as lk_openai

        logger.info("Using Amazon Bedrock LLM for LiveKit session via OpenAI-compatible endpoint")
        return lk_openai.LLM(model=bedrock_model, api_key=bedrock_key, base_url=bedrock_url)

    # Prefer OpenAI plugin if OPENAI_API_KEY set
    if openai_key:
        from livekit.plugins import openai as lk_openai

        logger.info("Using OpenAI LLM (gpt-4o-mini) for LiveKit session")
        return lk_openai.LLM(model="gpt-4o-mini", api_key=openai_key)

    if xai_key:
        from livekit.plugins import openai as lk_openai

        # xAI is OpenAI-compatible; model id matches server.py (grok-4.20)
        logger.info("Using xAI Grok LLM for LiveKit session via OpenAI-compatible endpoint")
        return lk_openai.LLM(
            model="grok-4.20-0309-non-reasoning",
            api_key=xai_key,
            base_url="https://api.x.ai/v1",
        )

    # Fallback to LiveKit Inference (requires LiveKit Cloud project)
    logger.warning("No XAI_API_KEY or OPENAI_API_KEY — falling back to LiveKit Inference LLM")
    return inference.LLM(model="openai/gpt-4o-mini")


VOICE_AGENT_INSTRUCTIONS = (
    "You are Brooke, a warm, friendly, concise real-time voice assistant speaking over LiveKit WebRTC. "
    "You are a general-purpose assistant helping callers with quick facts and everyday guidance. "
    "Keep every response to 1-2 short natural sentences (under 120 chars, max 300 when detail requested). "
    "Never use markdown, bullet points, asterisks, or code blocks. No stage directions or emojis. "
    "Speak as plain conversational text for TTS. Match the caller's pace. "
    "Never interrupt — pause after questions, confirm if uncertain, and ask for clarification if needed. "
    "Greet as 'Hi there, I'm your virtual assistant—how can I help today?' when prompted. "
    "For health/legal/financial: 'I'm not qualified to answer that, but I recommend reaching out to a licensed professional.' "
    "Always close by asking 'Is there anything else I can help you with today?' then 'Thanks for calling. Take care and have a great day!'"
)

server = AgentServer()


@server.rtc_session(agent_name="voice-agent")
async def entrypoint(ctx):
    logger.info(f"Agent joining room: {ctx.room.name}")

    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_key:
        logger.warning("DEEPGRAM_API_KEY is not set. Deepgram STT/TTS requires an API key.")

    llm = _create_llm()

    # Deepgram STT/TTS — aligned to Settings: flux-general-en 48k in, flux-brooke-en 24k out
    # flux-general-en is Flux conversational STT (low-latency, confident endpointing)
    # Interim + vad_events retained for turn detection; endpointing_ms 950 for confident speech (Never interrupt)
    stt = deepgram.STT(
        model="flux-general-en",
        language="en-US",
        interim_results=True,
        punctuate=True,
        endpointing_ms=950,
        vad_events=True,
        smart_format=True,
        encoding="linear16",
        sample_rate=48000,
    )
    # Flux TTS v2 — streaming linear16/24000 (matches server.py ws/voice)
    tts = deepgram.TTSv2(
        model="flux-brooke-en",
        encoding="linear16",
        sample_rate=24000,
    )

    # STT endpointing owns turn boundaries — Deepgram final transcripts commit turns.
    # Timing preserves prior VAD semantics: min 1.0s / max 3.5s, interruptions disabled.
    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        turn_handling={
            "turn_detection": "stt",
            "endpointing": {"min_delay": 1.0, "max_delay": 3.5},
            "interruption": {"enabled": False},
        },
    )

    # RoomOptions with noise cancellation if available
    room_options = None
    try:
        from livekit.plugins import noise_cancellation

        room_options = room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVC(),
            ),
        )
    except Exception:
        # noise_cancellation plugin optional / not installed in some envs
        pass

    await session.start(
        room=ctx.room,
        agent=Agent(instructions=VOICE_AGENT_INSTRUCTIONS),
        room_options=room_options,
    )

    # Greet the user — triggers first TTS
    await session.generate_reply(
        instructions="Greet the user warmly as Brooke and offer your assistance."
    )
    logger.info(f"Agent session started successfully in room: {ctx.room.name}")


if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)
