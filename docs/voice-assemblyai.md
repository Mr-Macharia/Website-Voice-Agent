# Voice: AssemblyAI Voice Agent API

How the voice path works, why it replaced LiveKit, and what to reach for when
it misbehaves.

## Why the change

The voice agent ran on LiveKit for WebRTC transport with Deepgram for STT and
TTS. LiveKit's metered resource is *connection minutes* — the transport itself,
not speech — and testing exhausted the free tier.

Moving to AssemblyAI's Voice Agent API removes LiveKit and Deepgram from the
voice path together: one WebSocket from the browser carries microphone audio
up, and transcripts plus synthesized speech down.

The LLM did **not** move. AssemblyAI calls our own endpoint for every reply.

## Shape

```
browser ──── WebSocket ────► agents.assemblyai.com
   │                              │  STT · turn detection · TTS
   │                              │
   │  GET /api/voice/token        ├──► POST /api/llm/chat/completions
   │  POST /api/voice/tool ◄──────┘        (our proxy → Bedrock/OpenAI/xAI)
   ▼
 backend
```

The browser holds the WebSocket. The backend serves three things the browser
cannot: a **token** (the API key must never reach the client), the **session
config** (the persona lives in Python), and **tool calls** (they need Postgres,
pgvector and Composio).

## What the server decides, and we no longer do

Turn-taking, barge-in and noise handling are server side, and they are semantic
rather than threshold-based:

- **End of turn** is judged from what was actually said, not from silence
  alone, and paces itself to each speaker.
- **Barge-in** distinguishes a back-channel ("uh-huh") from a real
  interruption ("wait, stop").
- **`voice_focus`** isolates the visitor's voice from background chatter, a
  television, or room echo *before* transcription.

This replaced a Silero VAD, tuned endpointing thresholds, an adaptive-RMS
browser VAD, and two SDK monkey-patches. Don't reintroduce them.

## Configuration

Everything is set **inline per session** — there is no stored agent and no
`agent_id`. `GET /api/voice/token` returns `{ token, session }`, and the
browser forwards the session object verbatim. `core/persona.py` stays the
single source of truth, and changing the persona is an ordinary deploy.

Built in `backend/voice/session_config.py`.

### Turn detection is deliberately almost unconfigured

Only `interrupt_response` is set. Setting `min_silence` or `max_silence` turns
off adaptive pacing and entity-aware waiting **for the whole session** — the
behaviour that makes the agent wait for a complete email address instead of
cutting in halfway through. Reach for `transcription_mode` first, and those two
knobs essentially never.

## The LLM proxy

`POST /api/llm/chat/completions` — `backend/voice/llm_proxy.py`.

AssemblyAI accepts exactly **one** `llm` entry, so without a proxy the provider
fallback chain would disappear. The proxy is where it survives: AssemblyAI sees
one stable URL, and we choose what sits behind it (Bedrock → OpenAI → xAI, the
order carried over from the LiveKit worker).

It also carries `guardrails.clean_output`. That used to run before TTS; now
that AssemblyAI speaks the model's tokens directly, the proxy is the only place
it can still act.

**It must be public HTTPS.** AssemblyAI calls it server-to-server and rejects
localhost, so local development points `LLM_PROXY_URL` at the deployed
instance. `LLM_PROXY_SECRET` is sent as the `llm[].api_key` and checked on
arrival, so the open endpoint isn't open to whoever finds it.

## Audio

PCM16 mono **24 kHz**, base64 **inside JSON events** — not raw binary frames.
(AssemblyAI's separate streaming STT product differs on both counts.)

Two things that are easy to get wrong and fail silently:

- **Field asymmetry.** Input audio travels in `audio`; reply audio arrives in
  **`data`**. Reading `audio` on the way back returns nothing, quietly.
- **Playback scheduling.** Chunks arrive faster than they play, so each is
  scheduled on a running `nextPlayTime` cursor. Playing on arrival overlaps
  them; `setTimeout` scheduling drifts from the hardware clock and gives pops.

## Full duplex

The microphone keeps streaming while the agent speaks, on every device, so the
visitor can interrupt at any moment. Browser echo cancellation
(`echoCancellation: true`) is what stops the agent hearing itself.

`noiseSuppression` is **off** by design: the server denoises already, and a
second layer costs more accuracy than the noise did. Tune `voice_focus`
instead.

**If the agent ever interrupts itself on a phone** — audio breaking right after
the first reply — that is its own speaker leaking past echo cancellation into
the mic. Raise `interruption_delay` server-side first. Muting the mic during
replies (half-duplex) works but costs barge-in, so it is a last resort.

## Tool calls

Declared as client-side function tools and relayed through the browser to
`POST /api/voice/tool`, because the logic needs the database, knowledge base
and Composio session. Schemas live in `backend/core/adapters/assemblyai.py`.

Two rules carried from the LiveKit adapter:

- Only advertise tools that are actually configured. A tool that can only fail
  wastes a turn and teaches the model to apologise.
- An optional tool must never take down the session — a single bad Gmail tool
  once killed an entire voice session rather than just itself.

Results are queued and sent only when the agent is idle (`reply.done`). On an
interruption, pending results are **discarded**: they answer a question nobody
is waiting for any more.

Tool failures come back as readable text telling the agent what to say next,
never as exceptions — a raised error mid-conversation leaves the visitor
listening to silence.

## Files

| Path | Role |
|---|---|
| `backend/voice/session_config.py` | the inline session config |
| `backend/voice/llm_proxy.py` | provider fallback + guardrails |
| `backend/core/adapters/assemblyai.py` | tool schemas and dispatch |
| `backend/server.py` | `/api/voice/token`, `/api/voice/tool`, `/api/llm/chat/completions` |
| `frontend/src/lib/voice/AssemblyAISession.ts` | WebSocket, audio, turn/interrupt handling |
| `frontend/src/components/voice/AssemblyAIVoiceModal.tsx` | the UI |
| `frontend/public/worklets/pcm-processor.js` | mic capture → 24 kHz PCM16 |

`NEXT_PUBLIC_VOICE_PROVIDER=livekit` still falls back to the old path during
the migration. Once AssemblyAI is proven, that branch and the LiveKit
dependencies come out.

## Deploying to Heroku

The proxy must be live before voice works anywhere, including locally.

```
Procfile: web: cd backend && uvicorn server:app --host 0.0.0.0 --port $PORT
```

Config vars: `ASSEMBLYAI_API_KEY`, `LLM_PROXY_SECRET`, one of
`BEDROCK_API_KEY` / `OPENAI_API_KEY` / `XAI_API_KEY`, `DATABASE_URL`,
`DEEPINFRA_API_KEY`, and optionally `COMPOSIO_API_KEY`.

Then set `LLM_PROXY_URL` to `https://<app>.herokuapp.com/api/llm` — note the
path, not the bare host: AssemblyAI appends `/chat/completions`.
