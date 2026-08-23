# 🎙️ Voice Agent — Real-Time Conversational AI

A full-stack real-time voice assistant powered by **FastAPI**, **Agno AgentOS**, **Deepgram (Nova-3 STT & Flux TTS)**, **LiveKit WebRTC**, and **Next.js 15**.

---

## 📁 Project Architecture & Directory Structure

```
voice-agent/
├── backend/                         # Python backend service & voice pipeline
│   ├── scripts/                     # Standalone CLI test scripts
│   │   ├── voice.py                 # Single-turn voice test script
│   │   └── main.py                  # CLI demonstration script
│   ├── voice_mcp/                   # Voice Agent MCP Server (FastMCP)
│   │   └── voice_agent_server.py    # MCP tools interface
│   ├── server.py                    # Main FastAPI + Agno AgentOS server (port 7777)
│   ├── livekit_worker.py            # LiveKit real-time WebRTC worker
│   ├── agno.db                      # SQLite session & memory database
│   ├── pyproject.toml               # Python dependencies (uv / pip)
│   ├── uv.lock                      # Locked Python dependencies
│   ├── .python-version              # Python version pin (3.13)
│   ├── .env.example                 # Backend environment variable template
│   ├── .env                         # Local backend secrets (git-ignored)
│   └── README.md                    # Backend documentation & quickstart
│
├── frontend/                        # Next.js 15 UI with LiveKit & Audio Visualizers
│   ├── src/
│   │   ├── app/                     # App router pages & Next.js API routes
│   │   ├── components/
│   │   │   ├── voice/               # LiveKitVoiceModal, VoiceVisualizer, ControlBar
│   │   │   ├── chat/                # Agent chat interface, message rendering
│   │   │   └── ui/                  # Radix UI primitives & styled components
│   │   ├── hooks/                   # Custom streaming and session hooks
│   │   ├── lib/                     # Audio streaming & endpoint utilities
│   │   ├── types/                   # TypeScript interfaces
│   │   └── store.ts                 # Zustand client store (default port 7777)
│   ├── package.json                 # Node dependencies & npm scripts
│   ├── tsconfig.json                # TypeScript configuration
│   ├── tailwind.config.ts           # Tailwind CSS configuration
│   ├── next.config.ts               # Next.js configuration
│   ├── .env.example                 # Frontend environment variable template
│   ├── .env.local                   # Local frontend secrets (git-ignored)
│   └── README.md                    # Frontend documentation & quickstart
│
├── .gitignore                       # Unified git ignore for Python, Node, & secrets
├── opencode.json                    # MCP tools configuration
└── README.md                        # Project root documentation
```

---

## ⚡ Quick Start

### 1. Configure Environment Variables

1. **Backend Configuration**:
   ```bash
   cp backend/.env.example backend/.env
   ```
   Provide your `DEEPGRAM_API_KEY`, `XAI_API_KEY` (or `OPENAI_API_KEY`), and optionally `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.

2. **Frontend Configuration**:
   ```bash
   cp frontend/.env.example frontend/.env.local
   ```

---

### 2. Start the Backend

In a new terminal:

```bash
cd backend

# Using uv (recommended)
uv run python server.py

# Or using standard python
python server.py
```

- Server starts at: `http://localhost:7777`
- Health check: `http://localhost:7777/api/info`
- Interactive API Docs: `http://localhost:7777/docs`

---

### 3. Start the Frontend

In another terminal:

```bash
cd frontend

# Install dependencies (pnpm or npm)
pnpm install

# Start Next.js development server
pnpm dev
```

- Web UI starts at: `http://localhost:3000`

---

## 🚀 Key Features

| Component | Technology | Description |
|---|---|---|
| **Speech-to-Text (STT)** | Deepgram Nova-3 | Ultra-low latency voice transcription with automatic audio format detection (`WAV`, `WebM`, `OGG`, `FLAC`). |
| **Agent Reasoning** | Agno AgentOS | Conversational memory, multi-turn session persistence with SQLite, tool orchestration (`WebSearchTools`). |
| **Text-to-Speech (TTS)** | Deepgram Flux TTS | Streaming audio output (`flux-brooke-en`) delivering conversational speech synthesis in real time. |
| **WebRTC Voice** | LiveKit Cloud / Server | Bidirectional low-latency audio transport for browser and mobile clients. |
| **Interactive UI** | Next.js 15 & Framer Motion | Glassmorphic visualizer, push-to-talk, live transcript stream, fallback voice bridges, and session history. |

---

## 🛠️ Standalone Testing & Utilities

- **Test Single Voice Turn via CLI**:
  ```bash
  cd backend && uv run python scripts/voice.py
  ```
- **Run LiveKit Voice Agent Worker**:
  ```bash
  cd backend && uv run python livekit_worker.py dev
  ```
- **Run Voice Agent MCP Server**:
  ```bash
  cd backend && uv run python voice_mcp/voice_agent_server.py
  ```
