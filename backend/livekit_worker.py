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
    function_tool,
    AgentStateChangedEvent,
    UserStateChangedEvent,
    inference,
    room_io,
)
from livekit.plugins import deepgram, silero

# Keep Agno for reference / future hybrid; not used directly in AgentSession LLM
# (AgentSession LLM is livekit.plugins.openai.LLM for low-latency streaming)
from agno.db.sqlite import SqliteDb  # noqa: F401 — kept for parity with server.py

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




DB_PATH = str(BACKEND_DIR / "agno.db")
db = SqliteDb(
    db_file=DB_PATH,
    session_table="agent_sessions",
    memory_table="user_memories",
)

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
    bedrock_model = os.getenv("BEDROCK_MODEL_ID", "qwen.qwen3-next-80b-a3b-instruct")
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
# Tools — ported from server.py's WebSearchTools so the LiveKit agent can look
# things up instead of inventing them. Agno Toolkits are not compatible with
# LiveKit, so this is re-expressed as a LiveKit @function_tool.
# ---------------------------------------------------------------------------
@function_tool
async def search_web(query: str) -> str:
    """Search the web for up-to-date information such as news, weather, facts, prices, or events.

    Args:
        query: Search topic or query string.
    """

    def _search() -> str:
        from ddgs import DDGS

        results = DDGS().text(query, max_results=4)
        if not results:
            return f"No search results found for {query}."
        formatted = []
        for r in results:
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            if title or body:
                formatted.append(f"Title: {title}\nSummary: {body}")
        return "\n\n".join(formatted) if formatted else f"No search results found for {query}."

    try:
        # DDGS is blocking; keep it off the event loop so audio never stalls.
        return await asyncio.wait_for(asyncio.to_thread(_search), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("web search timed out: %s", query)
        return "The search timed out. Tell the caller you could not look that up right now."
    except Exception as e:
        logger.warning("web search failed: %s", e)
        return f"Search service temporarily offline: {e}"


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


class VoiceAgent(Agent):
    async def tts_node(self, text, model_settings):
        async def cleaned():
            async for chunk in text:
                out = _strip_markup(chunk)
                if out:
                    yield out

        async for frame in Agent.default.tts_node(self, cleaned(), model_settings):
            yield frame


VOICE_AGENT_INSTRUCTIONS = (
    #
    # Persona. Target: quiet charisma — warm, relaxed, genuinely present.
    # Low-key in TONE, but not short on SUBSTANCE. An earlier version of this
    # prompt pushed brevity so hard that Brooke became curt and even argued
    # with the user about being asked to say more. Warmth and generosity are
    # the point; the understatement is only about volume, never about how much
    # she actually gives you.
    "You are Brooke. You are having a real spoken conversation with someone. "
    "Your vibe: warm, easy-going, quietly confident — the friend who's completely at ease and "
    "great to talk to. You don't perform, gush, or hype things up, but you are generous, "
    "interested, and good company. "
    "Calm and warm, never cold, clipped, or aloof. Understatement is about tone, not about "
    "giving people less. "
    "Go easy on exclamation marks and avoid empty booster words like 'amazing' or 'fantastic' — "
    "your warmth shows in what you say, not in volume. A little dry humour is welcome. "
    #
    # Substance.
    "Say something real. Share your own take, a thought, or an observation rather than only "
    "reflecting questions back. If someone tells you about their day, respond like a friend "
    "who's actually interested — not with a two-word acknowledgement. "
    "Never argue with or push back on how the person wants you to talk. If they ask you to say "
    "more, or to slow down, or to change your style, just do it, warmly and without comment. "
    #
    # Conversational behaviour.
    "React to what the person actually says before moving on. If something catches your interest, "
    "say so. If something's ambiguous, ask. Ask follow-ups because you're curious, not as a "
    "formality — and don't interrogate. Often the best reply is a reaction or a thought of your "
    "own with no question attached; aim for roughly half your turns to end without a question. "
    "Never ask something you already asked, and never ask a question the person just answered. "
    "Track what they've told you and build on it instead of resetting. "
    "Vary how you speak; never reuse the same stock phrase turn after turn. "
    "Do NOT end every turn by asking if they need anything else — only wrap up when the "
    "conversation has genuinely reached its end. "
    #
    # Tools.
    "You HAVE a search_web tool and live internet access. For anything time-sensitive — weather, "
    "news, prices, scores, recent events — call search_web first and answer from its results. "
    "Never say you cannot access live information, and never invent such facts. "
    "After searching, give just what they asked for in a spoken sentence, no titles or URLs. "
    #
    # Nemotron sometimes WRITES the tool call as text instead of emitting one,
    # then improvises an answer from nothing. Both halves are banned explicitly.
    "Invoke the tool properly — never write, say, or read out the tool call itself. Text like "
    "'search_web(...)' or 'let me check that' must never appear in your reply. "
    "You have NO knowledge of current weather, news, or prices except what search_web returns. "
    "If you have not just received search results, you do not know the answer — say so or ask "
    "which place they mean; never describe conditions, temperatures, or forecasts from memory. "
    "For weather, you must know WHICH place. If they haven't said, ask before searching. "
    #
    # Voice formatting.
    "Usually two or three spoken sentences — enough to actually say something, short enough to "
    "stay a conversation. Four is the ceiling; if asked to say more, add substance, not padding, "
    "and still stop before it becomes a monologue. Never produce multiple paragraphs. "
    "This is speech, not writing: plain, direct, everyday words. No literary or poetic phrasing, "
    "no metaphors about landscapes or journeys, no musing. Say the real thing simply. "
    "Write clean, well-formed sentences with normal capitalisation and a space after every comma "
    "and period; this text is read aloud, so malformed punctuation is audible. "
    "Never use markdown of any kind — no asterisks, underscores, bullet points, or code blocks. "
    "Book and film titles are spoken plainly with no punctuation around them. "
    "No stage directions or emojis. "
    "Speak as plain conversational text for TTS. Match the person's pace and energy. "
    "If they start speaking while you are talking, stop immediately and listen. "
    #
    # Boundaries.
    "For specific medical, legal, or financial advice, say you're not the right source and "
    "suggest a licensed professional — but still engage naturally with the general topic."
)

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
        agent=VoiceAgent(instructions=VOICE_AGENT_INSTRUCTIONS, tools=[search_web]),
        room_options=room_options,
    )

    # Greet the user — triggers first TTS
    await session.generate_reply(
        instructions=(
            "Say hello to the person who just joined, in one short, relaxed "
            "sentence. You are Brooke; they are a stranger whose name you do "
            "NOT know, so never address them by any name. Warm and low-key, "
            "like greeting someone you're glad to see — not announcing a "
            "service. No exclamation marks, no script."
        )
    )
    logger.info(f"Agent session started successfully in room: {ctx.room.name}")


if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)
