"""
LiveKit Voice Agent Worker
Connects to LiveKit Cloud / Server and orchestrates bidirectional real-time voice streaming
with Deepgram Nova-3 STT, Agno Agent intelligence & memory, and Deepgram Aura/Flux TTS.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load .env from backend and root
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")
load_dotenv()

from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    WorkerOptions,
    cli,
    room_io,
)
from livekit.plugins import deepgram, silero
from agno.agent import Agent as AgnoAgent
from agno.models.xai import xAI
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb

logger = logging.getLogger("voice-agent-worker")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Setup SQLite Database for Agno Session Persistence
# ---------------------------------------------------------------------------
DB_PATH = str(BACKEND_DIR / "agno.db")

db = SqliteDb(
    db_file=DB_PATH,
    session_table="agent_sessions",
    memory_table="user_memories",
)

xai_key = os.getenv("XAI_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

if xai_key:
    llm = xAI(id="grok-4.20-0309-non-reasoning", api_key=xai_key)
else:
    llm = OpenAIChat(id="gpt-4o-mini", api_key=openai_key)

agno_agent = AgnoAgent(
    id="voice-agent",
    name="Realtime Voice Assistant",
    model=llm,
    description="Fast, concise conversational voice assistant.",
    instructions=[
        "You are a real-time conversational voice assistant.",
        "Keep responses brief (1-2 sentences), direct, and conversational.",
        "Never use markdown formatting, bullet points, asterisks, or code blocks in spoken responses.",
        "Be friendly, natural, and helpful."
    ],
    markdown=False,
    db=db,
    add_history_to_context=True,
    num_history_runs=4,
)

async def entrypoint(ctx: JobContext):
    logger.info(f"Agent joining room: {ctx.room.name}")
    await ctx.connect()

    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_key:
        logger.warning("DEEPGRAM_API_KEY is not set. Deepgram STT/TTS requires an API key.")

    # Initialize Voice Pipeline Session
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", api_key=deepgram_key),
        vad=silero.VAD.load(),
        tts=deepgram.TTS(model="aura-luna-en", api_key=deepgram_key),
    )

    agent_instructions = (
        "You are a helpful and fast voice assistant. "
        "Keep all responses short (1-2 sentences), conversational, and friendly."
    )

    await session.start(
        room=ctx.room,
        agent=Agent(instructions=agent_instructions),
    )
    logger.info(f"Agent session started successfully in room: {ctx.room.name}")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
