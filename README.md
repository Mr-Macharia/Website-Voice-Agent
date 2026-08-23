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

### 2. Start Everything (One Command)

Unified runner starts **backend + LiveKit worker** together (effective live voice chat needs both):

```bash
# Backend (7777) + LiveKit worker (flux-brooke-en) — recommended
npm run dev
# or
python scripts/run.py
bash scripts/run.sh

# Backend + Worker + Frontend (7777 + LiveKit + 3000)
npm run dev:all
# or
python scripts/run.py --with-frontend
bash scripts/run.sh --with-frontend

# Individual services still work:
npm run dev:backend   # only FastAPI + Deepgram Flux WS
npm run dev:worker    # only LiveKit worker (needs backend)
npm run dev:frontend  # only Next.js UI
```

- Backend: `http://localhost:7777` — health `/api/info`, docs `/docs`, voice WS `/ws/voice`
- LiveKit worker: joins `voice-agent-room` via `LIVEKIT_URL` (fallback to Direct WS bridge if not set)
- Frontend: `http://localhost:3000` (when using `--with-frontend`)

Or manually in separate terminals:

```bash
# Terminal 1 — Backend
cd backend && uv run python server.py
# Terminal 2 — LiveKit worker
cd backend && uv run python livekit_worker.py dev
# Terminal 3 — Frontend
cd frontend && pnpm dev
```

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
