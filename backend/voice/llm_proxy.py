"""OpenAI-compatible LLM proxy for the AssemblyAI Voice Agent.

AssemblyAI accepts exactly one `llm` entry and calls it server-to-server, so
without a proxy the provider fallback chain that livekit_worker._create_llm()
used would simply disappear. This module is where it survives: AssemblyAI sees
one stable HTTPS URL, and we decide what sits behind it.

It also carries the two things that would otherwise be lost with the LiveKit
pipeline:

  - Provider keys stay on our infrastructure rather than in AssemblyAI's
    stored agent config.
  - guardrails.clean_output is reapplied to the reply text. It used to run
    before TTS in the LiveKit pipeline; now that AssemblyAI speaks the model's
    tokens directly, this is the only remaining place it can act.

Because AssemblyAI calls it from their servers, the URL must be public HTTPS —
localhost is rejected. Local development points at the deployed instance.
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncIterator

import httpx

from core import config, guardrails

logger = logging.getLogger("voice.llm_proxy")

# Reply latency is conversation latency: a slow first token is dead air the
# visitor hears. Connect fast, fail fast, but allow a long read for streaming.
_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)


def _providers() -> list[dict]:
    """Upstreams in priority order, best first.

    xAI leads, not Bedrock/DeepSeek. Measured against the Voice Agent API's
    tool-calling protocol:

      - deepseek.v3.2 given a tool it clearly should use emitted ZERO tool
        calls and answered from nothing. Handed a completed tool result, it
        replied with the malformed control token "<|DSML|function_calls"
        instead of an answer. Live, it spoke AssemblyAI's own orchestration
        instructions aloud to visitors ("Do not comment on the tool's
        existence...", "Use the reply box to speak to the person...") — the
        model failing the protocol and spilling the rules instead of following
        them.
      - grok-4.6, grok-4.5 and grok-4.20-non-reasoning all called the tool
        correctly with no spoken text, and turned a tool result into a clean
        two-sentence spoken answer.

    This is the same class of defect the LiveKit worker recorded for
    nemotron-nano-3-30b, which printed 'search_web(...)' as literal text.
    Tool calling with conversation history is the thing to test before
    changing a model here; latency is secondary.

    DeepSeek stays as a last resort so voice still answers if xAI is down.
    """
    out: list[dict] = []

    if config.XAI_API_KEY:
        out.append({
            "name": "xai",
            "base_url": "https://api.x.ai/v1",
            "api_key": config.XAI_API_KEY,
            "model": config.XAI_MODEL_ID or "grok-4.6",
        })

    if config.OPENAI_API_KEY:
        out.append({
            "name": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": config.OPENAI_API_KEY,
            "model": "gpt-4o-mini",
        })

    if config.BEDROCK_API_KEY:
        out.append({
            "name": "bedrock",
            "base_url": config.BEDROCK_BASE_URL.rstrip("/"),
            "api_key": config.BEDROCK_API_KEY,
            "model": config.BEDROCK_MODEL_ID or "deepseek.v3.2",
        })

    return out


def authorized(auth_header: str | None) -> bool:
    """Check the shared secret AssemblyAI sends as the llm[].api_key.

    Not a provider key — it exists so the public endpoint isn't open to whoever
    finds the URL. Absent a configured secret we refuse everything rather than
    running open, which would let anyone spend our LLM budget.
    """
    if not config.LLM_PROXY_SECRET:
        return False
    if not auth_header:
        return False
    token = auth_header.removeprefix("Bearer ").strip()
    return token == config.LLM_PROXY_SECRET


# DeepSeek V3.2 is a reasoning model: it thinks in the open, wrapping its chain
# of thought in <think>...</think> inside the normal content stream, and also
# exposes it as a separate `reasoning_content` delta on some providers.
#
# None of that is speech. Streamed into TTS it becomes the agent narrating its
# own planning to the visitor — heard live as "let me check his background",
# "If you can add more input while they wait for results, do so as usual", and
# a bare "</think>" spoken aloud.
#
# This is the structural fix. The guardrails in core/guardrails.py pattern-match
# the *content* of leaked reasoning, which is a losing game because the model
# writes new prose each time; this removes the channel instead.
_THINK_OPEN = re.compile(r"<\s*think\s*>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"<\s*/\s*think\s*>", re.IGNORECASE)


class _ThinkFilter:
    """Drops <think>...</think> spans from a streamed reply.

    Tags can be split across chunks ("<thi" + "nk>"), so a short tail is held
    back whenever the buffer ends in something that might become a tag.
    """

    # Long enough for "</think>" plus whitespace variants.
    _MAX_TAG = 12

    def __init__(self) -> None:
        self._buf = ""
        self._thinking = False

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buf += text
        out = []

        while self._buf:
            if self._thinking:
                m = _THINK_CLOSE.search(self._buf)
                if not m:
                    # Stay inside the think block; keep only a possible partial tag.
                    self._buf = self._buf[-self._MAX_TAG:]
                    return "".join(out)
                self._buf = self._buf[m.end():]
                self._thinking = False
                continue

            m_open = _THINK_OPEN.search(self._buf)
            # A close tag with no opener: the reasoning began before the first
            # content delta, so everything up to it was thinking. Heard live as
            # a bare "</think>" spoken to the visitor.
            m_close = _THINK_CLOSE.search(self._buf)
            if m_close and (not m_open or m_close.start() < m_open.start()):
                out.clear()
                self._buf = self._buf[m_close.end():]
                continue
            if not m_open:
                break
            out.append(self._buf[: m_open.start()])
            self._buf = self._buf[m_open.end():]
            self._thinking = True

        if not self._thinking:
            # Hold back a tail that could still become an opening tag.
            cut = len(self._buf)
            for i in range(1, min(self._MAX_TAG, len(self._buf)) + 1):
                tail = self._buf[-i:].lower().replace(" ", "")
                if "<think>".startswith(tail) or "</think>".startswith(tail):
                    cut = len(self._buf) - i
                    break
            out.append(self._buf[:cut])
            self._buf = self._buf[cut:]

        return "".join(out)

    def finish(self) -> str:
        """Flush anything still buffered, unless it is unterminated reasoning."""
        if self._thinking:
            # An unclosed <think> means the whole tail was reasoning.
            self._buf = ""
            return ""
        tail, self._buf = self._buf, ""
        return tail


class _ReplyCleaner:
    """Applies guardrails across a streamed reply, not fragment by fragment.

    guardrails.clean_output is anchored to the START of a reply: it strips a
    leaked instruction line, a leaked prefix, or an "I'll look that up"
    preamble only when they lead. A streaming proxy never sees a reply — it
    sees token-sized fragments — so running those anchored rules against each
    fragment matches almost nothing, and a preamble split across two chunks
    survives regardless.

    Observed live before this existed: the agent spoke its own reasoning
    ("I should look up what Gichogu Macharia actually does first") and then
    read a paragraph of its system prompt aloud, verbatim.

    So the head of each reply is buffered until there is enough text to judge —
    a sentence, or _HEAD_CHARS — cleaned once, and released. Everything after
    the head streams straight through, because these leaks only ever lead.

    Buffering the head costs a little time-to-first-audio. It is bounded by
    _HEAD_CHARS and only applies to the first fragment or two, which is a fair
    trade against speaking the prompt out loud.
    """

    # Enough to contain a leading sentence; a leaked preamble is far shorter.
    _HEAD_CHARS = 240

    def __init__(self) -> None:
        self._head = ""
        self._released = False

    def feed(self, text: str) -> str:
        """Return the text safe to emit now, which may be empty."""
        if self._released:
            return text
        if not text:
            return ""

        self._head += text
        # Wait for a sentence boundary or enough characters to judge the lead.
        if len(self._head) < self._HEAD_CHARS and not re.search(r"[.!?\n]", self._head):
            return ""
        return self._flush()

    def finish(self) -> str:
        """Release whatever is still buffered at the end of the reply."""
        if self._released:
            return ""
        return self._flush()

    def _flush(self) -> str:
        self._released = True
        head, self._head = self._head, ""
        return guardrails.clean_output(head)


async def stream_completion(payload: dict) -> AsyncIterator[bytes]:
    """Proxy a chat completion upstream, yielding SSE bytes as they arrive.

    Tries each provider in turn; a provider that fails to *start* streaming
    falls through to the next. Once bytes are flowing we are committed — the
    agent is already speaking, so switching mid-reply would produce a sentence
    stitched from two models.
    """
    providers = _providers()
    if not providers:
        logger.error("No LLM provider configured; voice replies will fail")
        yield _error_chunk("No language model is configured.")
        return

    last_error: Exception | None = None

    for provider in providers:
        body = dict(payload)
        body["model"] = provider["model"]
        # Voice needs tokens as they are generated, never a single blob at the
        # end — buffering turns reply latency into whole-turn latency.
        body["stream"] = True

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{provider['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")[:300]
                        logger.warning(
                            "LLM provider %s returned %s: %s",
                            provider["name"], response.status_code, detail,
                        )
                        last_error = RuntimeError(f"{provider['name']} {response.status_code}")
                        continue  # try the next provider

                    logger.info("Voice reply streaming from %s", provider["name"])
                    cleaner = _ReplyCleaner()
                    think = _ThinkFilter()
                    async for line in response.aiter_lines():
                        out = _transform_sse_line(line, cleaner, think)
                        if out is not None:
                            yield out
                    return

        except Exception as e:  # network, DNS, timeout — try the next one
            logger.warning("LLM provider %s failed: %s", provider["name"], e)
            last_error = e
            continue

    logger.error("All LLM providers failed; last error: %s", last_error)
    yield _error_chunk("I'm having trouble thinking right now. Could you try that again?")


def _transform_sse_line(
    line: str, cleaner: "_ReplyCleaner", think: "_ThinkFilter"
) -> bytes | None:
    """Pass an SSE line through, cleaning any reply text inside it.

    Returns None for lines to skip. Anything unparseable is forwarded
    untouched: a guardrail that breaks the stream is worse than one that
    misses a fragment.
    """
    if not line:
        return b"\n"
    if not line.startswith("data: "):
        return (line + "\n").encode()

    data = line[6:].strip()
    if data == "[DONE]":
        # Release anything still held back, or a reply shorter than the head
        # buffer would never be spoken at all.
        tail = cleaner.feed(think.finish()) + cleaner.finish()
        if tail:
            chunk = {"choices": [{"index": 0, "delta": {"content": tail},
                                  "finish_reason": None}]}
            return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
        return b"data: [DONE]\n\n"

    try:
        chunk = json.loads(data)
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            # Some providers stream reasoning in its own field. It is never
            # speech, so drop it outright rather than forwarding it.
            delta.pop("reasoning_content", None)
            delta.pop("reasoning", None)
            if isinstance(delta.get("content"), str):
                delta["content"] = cleaner.feed(think.feed(delta["content"]))
            # A finished reply must release the buffer even without [DONE].
            if choice.get("finish_reason"):
                tail = cleaner.feed(think.finish()) + cleaner.finish()
                if tail:
                    delta["content"] = (delta.get("content") or "") + tail
        return f"data: {json.dumps(chunk)}\n\n".encode()
    except (json.JSONDecodeError, TypeError, AttributeError):
        return (line + "\n\n").encode()


def _error_chunk(message: str) -> bytes:
    """A minimal OpenAI-shaped stream carrying a spoken fallback line.

    The visitor is mid-conversation waiting for audio, so the agent must say
    something rather than fall silent.
    """
    chunk = {
        "choices": [{"index": 0, "delta": {"content": message}, "finish_reason": "stop"}],
    }
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
