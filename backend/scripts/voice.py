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
from deepgram import DeepgramClient


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

# Initialize Deepgram Client (reads DEEPGRAM_API_KEY from environment)
deepgram = DeepgramClient(api_key=os.getenv("DEEPGRAM_API_KEY"))

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

    # 3. Generate Deepgram TTS (Aura Voice) using SDK v7
    audio_stream = deepgram.speak.v1.audio.generate(
        text=agent_full_text,
        model="aura-luna-en"
    )
    
    # Save audio response to file
    out_file = BACKEND_DIR / "agent_response.mp3"
    with open(out_file, "wb") as f:
        for chunk in audio_stream:
            f.write(chunk)
            
    print(f"\n[Audio saved to {out_file}]")

if __name__ == "__main__":
    asyncio.run(run_voice_turn("Hello! Tell me a quick 1-sentence fact."))
