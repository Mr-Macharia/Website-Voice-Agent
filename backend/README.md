# Voice Agent Backend

FastAPI & Agno AgentOS server powering real-time voice streaming with Deepgram (Nova-3 STT, Aura & Flux TTS), Agno intelligent agents, and LiveKit WebRTC orchestration.

## Features

- **Agno AgentOS & Agents**:
  - `voice-agent`: High-speed, concise conversational assistant designed for real-time speech synthesis, with a DuckDuckGo web search tool for current information (news, weather, prices, events).
  - SQLite persistent session & memory database (`agno.db`).
- **Deepgram Audio Pipeline**:
  - `POST /api/stt`: Multi-format speech-to-text with Deepgram Nova-3.
  - `WebSocket /ws/voice`: Bidirectional real-time voice bridge with streaming Agno LLM and Deepgram Flux TTS (`flux-brooke-en`).
  - `WebSocket /ws/deepgram-agent`: Native Deepgram Voice Agent bridge (`wss://agent.deepgram.com`).
- **LiveKit RTC Integration**:
  - `GET/POST /api/livekit/token`: Generates room join access tokens with audio publish/subscribe permissions.
  - `livekit_worker.py`: Standalone LiveKit worker for headless WebRTC room handling.

---

## Getting Started

### 1. Prerequisites

- Python `>= 3.13`
- [uv](https://docs.astral.sh/uv/) (recommended) or `pip`

### 2. Environment Setup

Create a `.env` file in `backend/` (or repository root):

```bash
cp .env.example .env
```

Fill in your API keys:
- `DEEPGRAM_API_KEY`: Deepgram Console API key
- `XAI_API_KEY` or `OPENAI_API_KEY`: LLM inference key
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`: LiveKit Cloud or self-hosted instance credentials

### 3. Install Dependencies

Using `uv`:
```bash
uv sync
```

Or using standard `pip`:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4. Running the Backend Server

Start the FastAPI + Agno AgentOS server on port `7777`:

```bash
# Using uv
uv run python server.py

# Or directly in virtualenv
python server.py
```

API Server will be available at: `http://localhost:7777`
- Health check / info: `http://localhost:7777/api/info`
- Swagger documentation: `http://localhost:7777/docs`

### 5. Running the LiveKit Worker (Optional)

To start the LiveKit Worker daemon that joins rooms and handles real-time audio:

```bash
uv run python livekit_worker.py dev
```

### 6. Standalone CLI Voice Testing

To test a single turn from the terminal without starting the server:

```bash
uv run python scripts/voice.py
```
