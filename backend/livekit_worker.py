"""
LiveKit Voice Agent Worker — Real-time WebRTC with Deepgram Flux TTS
Uses LiveKit Agents 1.x AgentServer pattern with STT/LLM/TTS/VAD.
Unified voice: flux-brooke-en (Deepgram Flux v2)
"""

import asyncio
import logging
import os
import re
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

from livekit.agents import (
    AgentServer,
    AgentSession,
    Agent,
    AgentStateChangedEvent,
    UserStateChangedEvent,
    inference,
    room_io,
)
from livekit.plugins import deepgram, silero

from core import guardrails, persona
from core.adapters import livekit as lk_tools

logger = logging.getLogger("voice-agent-worker")
logging.basicConfig(level=logging.INFO)

# Third-party logger noise is handled in core.logging_config, which is also
# re-applied inside the search tool (those libraries are imported lazily, so
# their loggers do not exist yet at startup).
from core.logging_config import quiet_noisy_loggers as _quiet_noisy_loggers  # noqa: E402

_quiet_noisy_loggers()

# ---------------------------------------------------------------------------
# Playback buffer.
#
# RoomIO hardcodes its outbound AudioSource to queue_size_ms=200 (the rtc SDK's
# own default is 1000). This patches that call site so the cushion can be tuned;
# it is left at 1000ms, which is where it has always run in practice.
#
# Two things are worth recording so this is not re-litigated:
#
# 1. The original comment justified 1000ms by claiming Flux synthesizes at
#    ~0.77x realtime. That is not what it does. Measured directly against
#    flux-brooke-en at 24kHz, it is FASTER than realtime no matter how quickly
#    text is fed:
#
#      all words at once   18.24s audio / 13.39s wall = 1.36x  (max gap 0.19s)
#      word every 50ms     17.36s audio / 11.62s wall = 1.49x  (max gap 0.24s)
#      word every 120ms    22.16s audio / 16.71s wall = 1.33x  (max gap 0.24s)
#
#    So the stated reason for widening the buffer does not hold.
#
# 2. Dropping it to 200ms was tried and changed nothing audible: the
#    "flush audio emitter due to slow audio generation" DEBUG lines appeared at
#    the same ~305ms cadence and the same count at both 200ms and 1000ms. Those
#    lines are the emitter's flush timer arming and re-arming on a streaming
#    TTS; they are not by themselves evidence of a fault, and chasing them was
#    a dead end.
#
# The value is therefore left alone at 1000ms rather than changed on a theory
# that measurement did not support. LK_AUDIO_QUEUE_MS overrides it.
# ---------------------------------------------------------------------------
def _widen_playback_buffer() -> None:
    queue_ms = int(os.getenv("LK_AUDIO_QUEUE_MS", "1000"))
    try:
        from livekit import rtc
        from livekit.agents.voice.room_io import _output as room_output

        original = rtc.AudioSource

        class BufferedAudioSource(original):  # type: ignore[misc, valid-type]
            def __init__(self, sample_rate, num_channels, queue_size_ms=queue_ms, **kwargs):
                # RoomIO passes 200 explicitly; override only that call site's
                # value, leaving anything that asks for a larger buffer alone.
                if queue_size_ms < queue_ms:
                    queue_size_ms = queue_ms
                super().__init__(sample_rate, num_channels, queue_size_ms=queue_size_ms, **kwargs)

        room_output.rtc.AudioSource = BufferedAudioSource  # type: ignore[attr-defined]
        logger.info("Playback buffer queue_size_ms=%d", queue_ms)
    except Exception as e:  # pragma: no cover - never block startup on this
        logger.warning("Could not widen playback buffer: %s", e)



_quiet_noisy_loggers()

# ---------------------------------------------------------------------------
# Adaptive interruption timeout.
#
# The adaptive interruption detector calls LiveKit's inference gateway with a
# hardcoded 700ms budget (REMOTE_INFERENCE_TIMEOUT). A single 408 timeout is
# treated as unrecoverable and permanently downgrades the session to VAD-only
# interruptions — losing backchannel detection for the rest of the call.
#
# On a link with real latency to the gateway, 700ms is not enough. The SDK
# exposes no constructor argument or env var for this (AgentActivity builds
# AdaptiveInterruptionDetector() with no arguments), so raise the module
# constant before the detector class is instantiated. Revisit if the SDK adds
# a supported knob.
# ---------------------------------------------------------------------------
def _widen_interruption_timeout() -> None:
    timeout = float(os.getenv("LK_INTERRUPTION_TIMEOUT", "2.0"))
    try:
        from livekit.agents.inference import interruption as _interruption

        _interruption.REMOTE_INFERENCE_TIMEOUT = timeout
        # The default is bound as a parameter default at class-definition time,
        # so rebind it there too.
        detector = _interruption.AdaptiveInterruptionDetector
        defaults = detector.__init__.__kwdefaults__
        if defaults and "inference_timeout" in defaults:
            defaults["inference_timeout"] = timeout
    except Exception as e:  # pragma: no cover - never block startup on this
        logger.warning("Could not widen adaptive interruption timeout: %s", e)




# No database handle here: the LiveKit pipeline drives livekit.plugins.openai.LLM
# directly and never touched the Agno session store. Session persistence for the
# text agent lives in core/db.py (Postgres).

# ---------------------------------------------------------------------------
# LLM selection — mirrors server.py but for LiveKit pipeline
# LiveKit plugins.openai.LLM is OpenAI-compatible, so xAI works via base_url
# ---------------------------------------------------------------------------
def _create_llm():
    bedrock_url = os.getenv("BEDROCK_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1")
    bedrock_key = os.getenv("BEDROCK_API_KEY")
    # nemotron-nano-3-30b could not reliably emit tool calls once the chat had
    # any conversational history: it printed 'search_web(...)' as literal text or
    # invented the answer outright (measured 0/2; temperature made no
    # difference). qwen3-next-80b scored 2/2 at comparable latency.
    bedrock_model = os.getenv("BEDROCK_MODEL_ID", "deepseek.v3.2")
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


# ---------------------------------------------------------------------------
# Tools now live in core/tools/ and are wrapped for LiveKit in
# core/adapters/livekit.py, so the voice agent, the text agent and the MCP
# server all share one implementation instead of three drifting copies.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Agent with markdown stripped before speech.
#
# Qwen still emits markdown emphasis for titles (*The Drowning Pool*) despite
# being told not to, and TTS reads those symbols aloud. Strip them in the TTS
# path so the spoken audio is clean while the transcript keeps the original
# text.
# ---------------------------------------------------------------------------
_MARKDOWN_RE = re.compile(r"(\*{1,3}|_{1,3}|`{1,3}|~{2})")


def _strip_markup(text: str) -> str:
    # Only remove emphasis/code markers, never sentence punctuation.
    return _MARKDOWN_RE.sub("", text)


# Flush on whitespace, not on sentence punctuation.
#
# This buffer exists only so a URL split across token chunks can still be
# matched by the guardrail regex. It used to hold text until `[.!?]\s`, which
# meant a whole sentence was withheld for however long the LLM took to generate
# it, then delivered to TTS in one burst. The gap between bursts was model
# latency played back as silence — speech paced by generation rather than by
# prosody, audible as a glitch mid-answer.
#
# Deepgram TTSv2 is a streaming TTS: it holds a websocket and sends each word as
# its own `Speak` frame (livekit/plugins/deepgram/tts_v2.py), synthesizing
# continuously. It wants words as soon as they exist. Because a URL never
# contains whitespace, withholding only the unterminated trailing token is
# enough to keep the guardrail whole, so that is the boundary now. Do not
# restore the sentence gate; it starves the TTS.
_TRAILING_WS_RE = re.compile(r"\s(?=\S*$)")


async def _sanitize_stream(source, transform):
    """Apply `transform` to a token stream, holding back only a partial word.

    Tokens arrive a few characters at a time, so a URL is routinely split across
    chunks and a regex over a single chunk would never match it. Everything up
    to the last whitespace is safe to emit; the unterminated tail is retained
    until more text arrives or the stream ends.
    """
    buffer = ""
    async for chunk in source:
        buffer += chunk
        # Split at the last whitespace: the tail may still be a partial URL.
        match = _TRAILING_WS_RE.search(buffer)
        if not match:
            continue
        head, buffer = buffer[: match.end()], buffer[match.end():]
        out = transform(head)
        if out:
            yield out

    if buffer:
        out = transform(buffer)
        if out:
            yield out


def _clean_for_speech(text: str) -> str:
    """Strip markdown symbols and any URL the agent was not given by a tool."""
    return guardrails.clean_output(_strip_markup(text))


class VoiceAgent(Agent):
    async def tts_node(self, text, model_settings):
        async for frame in Agent.default.tts_node(
            self, _sanitize_stream(text, _clean_for_speech), model_settings
        ):
            yield frame

    async def transcription_node(self, text, model_settings):
        # What the visitor reads in the transcript. Markdown is fine here, but
        # a fabricated link must not reach them in writing either.
        async for chunk in Agent.default.transcription_node(
            self, _sanitize_stream(text, guardrails.clean_output), model_settings
        ):
            yield chunk


VOICE_AGENT_INSTRUCTIONS = persona.for_voice()

server = AgentServer()


def prewarm(proc):
    """Load Silero VAD once per process so new jobs start fast."""
    _quiet_noisy_loggers()
    _widen_interruption_timeout()
    _widen_playback_buffer()
    proc.userdata["vad"] = silero.VAD.load(
        # Slightly longer trailing silence than default (0.55) so brief
        # mid-thought pauses don't read as end-of-turn.
        min_silence_duration=0.65,
        # Ignore very short blips (coughs, clicks) as speech starts.
        min_speech_duration=0.08,
        # Marginally conservative: fewer false triggers from background noise.
        activation_threshold=0.55,
    )

    # Open the embeddings connection now, not on the visitor's first question.
    # Without this the first retrieval pays a TCP connect plus TLS handshake —
    # measured at 2.98s against a 0.45s steady-state median, which is dead air
    # right at the start of a conversation.
    try:
        from core import config as _cfg

        if _cfg.knowledge_available():
            from core import db as _db

            _db.get_embedder().get_embedding("warmup")
            logger.info("Embeddings connection warmed")
    except Exception as e:  # never block startup on a warmup
        logger.warning("Could not warm embeddings connection: %s", e)


server.setup_fnc = prewarm


@server.rtc_session(agent_name="voice-agent")
async def entrypoint(ctx):
    _quiet_noisy_loggers()
    _widen_playback_buffer()
    logger.info(f"Agent joining room: {ctx.room.name}")

    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_key:
        logger.warning("DEEPGRAM_API_KEY is not set. Deepgram STT/TTS requires an API key.")

    llm = _create_llm()

    # Deepgram Flux STT (v2 / wss://api.deepgram.com/v2/listen).
    #
    # STTv2 is the real Flux client. The v1 `deepgram.STT` class talks to
    # /v1/listen and has no end-of-turn model, so pointing it at
    # "flux-general-en" gave us silence-timer endpointing only — the exact
    # behaviour we are trying to get away from.
    #
    # eot_threshold: confidence required before Flux declares end-of-turn.
    #   This ran at 0.8 with eot_timeout_ms=4000 — both above the SDK defaults
    #   (0.7 / 3000) — to stop mid-sentence chopping. It overshot: when speech
    #   did not clear the 0.8 bar the turn never closed, and each new burst
    #   restarted the wait. Measured from a live session: one turn spoken in
    #   four bursts over 07:50:24-07:50:51 produced a SINGLE merged transcript
    #   at 07:50:54, ~30s after the caller started; other turns logged
    #   transcript_delay of 5.88s and 2.76s against 0.003s when it worked.
    #   That is the "my words arrive late, then all at once" failure.
    #   Back to the documented defaults, which endpoint on time; the eager
    #   threshold below still guards against clipping mid-sentence.
    # eot_timeout_ms: hard ceiling before Flux closes a turn regardless.
    # LiveKit does NOT pass an encoding here — it feeds Flux PCM itself.
    # eager_eot_threshold fires an early "EagerEndOfTurn" so the LLM can start
    # generating before the turn is confirmed; eot_threshold then has to clear a
    # higher bar to actually close the turn. This is what gives low latency
    # WITHOUT chopping people off mid-sentence.
    stt = deepgram.STTv2(
        model="flux-general-en",
        sample_rate=16000,
        eager_eot_threshold=0.6,
        eot_threshold=0.7,
        eot_timeout_ms=3000,
    )

    # Flux TTS v2 — streaming linear16/24000 (matches server.py ws/voice)
    tts = deepgram.TTSv2(
        model="flux-brooke-en",
        encoding="linear16",
        sample_rate=24000,
    )

    # Turn-taking configuration.
    #
    # turn_detection="stt": Deepgram Flux emits its own end-of-utterance signal,
    #   so it owns turn boundaries. The VAD below is still used for interruption
    #   detection and to keep the agent responsive while Flux decides.
    # endpointing: added on top of Flux's endpoint signal. Kept generous so the
    #   agent doesn't jump on a caller who pauses mid-thought.
    # interruption: the caller CAN now cut the agent off. "adaptive" uses the
    #   ML detector to tell a real interruption from a backchannel ("mm-hm",
    #   "right", "okay"), which plain VAD cannot do. min_words=1 requires actual
    #   transcribed speech, so breaths and room noise never truncate a response.
    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=ctx.proc.userdata.get("vad"),
        turn_handling={
            "turn_detection": "stt",
            # Flux's EOT model decides the boundary; this delay stacks on top
            # of it, so keep it small or the agent feels sluggish.
            "endpointing": {
                "mode": "fixed",
                "min_delay": 0.2,
                "max_delay": 4.0,
            },
            "interruption": {
                "enabled": True,
                "mode": "adaptive",
                "min_duration": 0.4,
                "min_words": 1,
                # If we cut off for speech that produced no transcript, treat it
                # as a false positive and pick up where we left off.
                "resume_false_interruption": True,
                "false_interruption_timeout": 2.0,
            },
            # LLM starts on the final transcript before the turn is confirmed —
            # this part is pure win and stays on.
            #
            # preemptive_tts is OFF deliberately. It starts synthesis before the
            # LLM has produced text, which helped when the only delay was
            # Bedrock's time-to-first-token. Now that answers about Gichogu go
            # through RAG, an embedding round trip sits inside that window: the
            # live logs show `agent state -> speaking` at 22:34:58.773 while the
            # embedding request was still in flight until 22:34:59.79, followed
            # by three "flush audio emitter due to slow audio generation" lines.
            # Speaking before there is anything to say is exactly the stutter.
            "preemptive_generation": {
                "enabled": True,
                "preemptive_tts": False,
            },
            # Cut in politely if a caller monologues, rather than buffering
            # indefinitely (voicemail greetings, someone reading a list).
            "user_turn_limit": {
                "max_words": 250,
                "max_duration": 90.0,
            },
        },
        # Small gap between consecutive agent utterances so back-to-back
        # speech doesn't run together.
        min_consecutive_speech_delay=0.3,
    )

    @session.on("user_state_changed")
    def _on_user_state(ev: UserStateChangedEvent):
        logger.debug("user state: %s -> %s", ev.old_state, ev.new_state)

    @session.on("agent_state_changed")
    def _on_agent_state(ev: AgentStateChangedEvent):
        logger.debug("agent state: %s -> %s", ev.old_state, ev.new_state)

    @session.on("user_interruption_detected")
    def _on_interruption(ev):
        logger.info("user interrupted (probability=%s)", getattr(ev, "probability", None))

    @session.on("agent_false_interruption")
    def _on_false_interruption(ev):
        logger.info("false interruption — resuming agent speech")

    # Enhanced noise cancellation (BVC) — LiveKit Cloud only. It measurably
    # improves STT and turn detection by stripping background noise and
    # competing voices before they reach Flux.
    room_options = None
    try:
        from livekit.plugins import noise_cancellation

        room_options = room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVC(),
            ),
        )
    except ImportError:
        logger.warning(
            "livekit-plugins-noise-cancellation not installed — running without BVC. "
            "Turn detection will be more sensitive to background noise."
        )
    except Exception as e:
        logger.warning("Noise cancellation unavailable (%s) — continuing without it.", e)

    await session.start(
        room=ctx.room,
        agent=VoiceAgent(instructions=VOICE_AGENT_INSTRUCTIONS, tools=lk_tools.get_tools()),
        room_options=room_options,
    )

    # Greet with fixed text, not generate_reply.
    #
    # generate_reply runs a full LLM turn with every tool available, so the
    # opening line was model-generated: it fired search_about_owner before the
    # visitor had asked anything (measured ~30s from "speaking" to the first
    # audible words) and spoke instruction-shaped filler it invented from
    # training priors — "You may speak a little as though you were thinking
    # aloud...", "Let me start by searching for information about...". The
    # guardrails strip what they recognise, but the real problem is asking a
    # model to improvise a line that never varies.
    #
    # say() sends text straight to TTS: no inference, no tool selection,
    # nothing to leak, and the greeting starts as soon as TTS connects.
    await session.say(persona.GREETING, allow_interruptions=True)
    logger.info(f"Agent session started successfully in room: {ctx.room.name}")


if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)
