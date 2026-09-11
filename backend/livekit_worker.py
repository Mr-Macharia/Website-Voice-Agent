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

# `livekit_worker.py dev` sets the ROOT logger to DEBUG, so every third-party
# library inherits it. ddgs pulls in Rust HTTP/DNS stacks (hickory, rustls,
# reqwest, primp) that log every DNS packet, which buries the agent's own logs
# on any turn that calls search_web. These carry nothing useful for debugging
# this agent, so pin them to WARNING.
#
# The CLI reconfigures logging AFTER this module is imported, so this has to be
# re-applied from inside the worker callbacks, not just at import time.
_NOISY_LOGGERS = (
    "hickory_net",
    "hickory_resolver",
    "hickory_proto",
    "h2",
    "hpack",
    "hyperframe",
    "hyper_util",
    "hyper",
    "cookie_store",
    "selectolax",
    "rustls",
    "reqwest",
    "primp",
    "httpx",
    "httpcore",
    "urllib3",
    "ddgs",
    "asyncio",
)


# ---------------------------------------------------------------------------
# Playback buffer.
#
# Deepgram's Flux TTS synthesizes slower than realtime from this region:
# measured medians of ~0.77x for flux-brooke-en (roughly 4.9s of compute for
# 3.0s of speech). LiveKit's RoomIO hardcodes its outbound AudioSource to
# queue_size_ms=200 (the rtc SDK's own default is 1000), so a 200ms cushion has
# to absorb synthesis running ~23% behind playback. It cannot, so the buffer
# drains mid-sentence and the audio stutters — the audible "glitch", and the
# cause of the constant "flush audio emitter due to slow audio generation".
#
# Raising the cushion trades a little extra latency before Brooke starts
# speaking for speech that doesn't break up. There is no public setting for
# this, so patch the constructor default. Revisit if RoomIO exposes one.
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
        logger.info("Playback buffer set to %dms (was 200ms)", queue_ms)
    except Exception as e:  # pragma: no cover - never block startup on this
        logger.warning("Could not widen playback buffer: %s", e)


def _quiet_noisy_loggers() -> None:
    for name in _NOISY_LOGGERS:
        log = logging.getLogger(name)
        log.setLevel(logging.WARNING)
        log.propagate = False


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


async def _sanitize_stream(source, transform):
    """Apply `transform` to a token stream, buffering so URLs survive chunking.

    Tokens arrive a few characters at a time, so a URL is routinely split
    across chunks and a regex over a single chunk would never match it. Text is
    therefore held until a sentence boundary before being emitted, which is
    also the granularity TTS wants.
    """
    buffer = ""
    async for chunk in source:
        buffer += chunk
        # Flush on sentence end, but only when no partial URL is pending.
        while True:
            match = re.search(r"[.!?]\s", buffer)
            if not match or "http" in buffer[match.end():]:
                break
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
    return guardrails.strip_unapproved_urls(_strip_markup(text))


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
            self, _sanitize_stream(text, guardrails.strip_unapproved_urls), model_settings
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
    #   0.7 is the default; higher = waits longer / more certain the caller
    #   actually finished, which is what stops mid-sentence chopping.
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
        eot_threshold=0.8,
        eot_timeout_ms=4000,
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
            # LLM starts on the final transcript before the turn is confirmed.
            # preemptive_tts also starts synthesis early: the logs showed
            # "flush audio emitter due to slow audio generation" on nearly every
            # turn, meaning playback was catching up to the TTS stream. Costs
            # some wasted synthesis on cancelled turns, buys smoother speech.
            "preemptive_generation": {
                "enabled": True,
                "preemptive_tts": True,
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

    # Greet the user — triggers first TTS
    await session.generate_reply(instructions=persona.greeting_instructions())
    logger.info(f"Agent session started successfully in room: {ctx.room.name}")


if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)
