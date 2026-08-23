import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")
load_dotenv()

from agno.agent import Agent
from agno.models.xai import xAI
from deepgram import DeepgramClient, SpeakOptions

# 1. Define your Agno Agent with custom tools and memory
agno_agent = Agent(
    model=xAI(id="grok-4.20-0309-non-reasoning"),
    description="You are a fast, concise conversational voice assistant.",
    instructions=[
        "Keep responses brief (1-2 sentences) and natural for conversational voice.",
        "Do not output markdown, bullet points, or special characters."
    ],
    markdown=False  # Crucial for clean TTS output
)

# Initialize Deepgram Client
deepgram = DeepgramClient()

async def run_voice_turn(user_transcript: str):
    """
    Takes text from Deepgram STT, routes through Agno,
    and streams to Deepgram TTS.
    """
    print(f"\nUser: {user_transcript}")
    print("Agent (Agno): ", end="", flush=True)

    # 2. Run Agno with streaming enabled to reduce time-to-first-word
    response_stream = agno_agent.run(user_transcript, stream=True)
    
    agent_full_text = ""
    for chunk in response_stream:
        token = chunk.content
        if token:
            print(token, end="", flush=True)
            agent_full_text += token

    # 3. Stream agent response to Deepgram TTS (Aura Voice)
    options = SpeakOptions(model="aura-luna-en")
    
    # Send text to Deepgram TTS and play back
    response = deepgram.speak.v("1").save("agent_response.mp3", {"text": agent_full_text}, options)
    print("\n[Audio played back via Deepgram]")