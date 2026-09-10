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

    # 3. Generate Deepgram TTS.
    # Flux models require the v2 speak endpoint (v1 returns
    # V2_MODEL_ON_V1_SPEAK_ENDPOINT); Aura models use SDK v1.
    TTS_MODEL = os.getenv("TTS_MODEL", "flux-brooke-en")
    out_file = BACKEND_DIR / "agent_response.mp3"
    if TTS_MODEL.lower().startswith("flux"):
        import httpx

        with httpx.Client(timeout=30.0) as client:
            res = client.post(
                f"https://api.deepgram.com/v2/speak?model={TTS_MODEL}&encoding=mp3",
                headers={
                    "Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}",
                    "Content-Type": "application/json",
                },
                json={"text": agent_full_text},
            )
            res.raise_for_status()
            out_file.write_bytes(res.content)
    else:
        audio_stream = deepgram.speak.v1.audio.generate(
            text=agent_full_text,
            model=TTS_MODEL
        )

        # Save audio response to file
        with open(out_file, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)
            
    print(f"\n[Audio saved to {out_file}]")

if __name__ == "__main__":
    asyncio.run(run_voice_turn("Hello! Tell me a quick 1-sentence fact."))
