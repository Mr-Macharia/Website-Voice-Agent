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

    Order and model choices carry over from livekit_worker._create_llm(),
    including its hard-won note: nemotron-nano-3-30b could not reliably emit
    tool calls once the chat had any history — it printed 'search_web(...)' as
    literal text or invented the answer outright. Don't substitute models here
    without testing tool calls with conversation history present.
    """
    out: list[dict] = []

    if config.BEDROCK_API_KEY:
        out.append({
            "name": "bedrock",
            "base_url": config.BEDROCK_BASE_URL.rstrip("/"),
            "api_key": config.BEDROCK_API_KEY,
            "model": config.BEDROCK_MODEL_ID or "deepseek.v3.2",
        })

    if config.OPENAI_API_KEY:
        out.append({
            "name": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": config.OPENAI_API_KEY,
            "model": "gpt-4o-mini",
        })

    if config.XAI_API_KEY:
        out.append({
            "name": "xai",
            "base_url": "https://api.x.ai/v1",
            "api_key": config.XAI_API_KEY,
            "model": "grok-4.20-0309-non-reasoning",
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
                    async for line in response.aiter_lines():
                        out = _transform_sse_line(line, cleaner)
                        if out is not None:
                            yield out
                    return

        except Exception as e:  # network, DNS, timeout — try the next one
            logger.warning("LLM provider %s failed: %s", provider["name"], e)
            last_error = e
            continue

    logger.error("All LLM providers failed; last error: %s", last_error)
    yield _error_chunk("I'm having trouble thinking right now. Could you try that again?")


def _transform_sse_line(line: str, cleaner: "_ReplyCleaner") -> bytes | None:
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
        tail = cleaner.finish()
        if tail:
            chunk = {"choices": [{"index": 0, "delta": {"content": tail},
                                  "finish_reason": None}]}
            return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
        return b"data: [DONE]\n\n"

    try:
        chunk = json.loads(data)
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            if isinstance(delta.get("content"), str):
                delta["content"] = cleaner.feed(delta["content"])
            # A finished reply must release the buffer even without [DONE].
            if choice.get("finish_reason"):
                tail = cleaner.finish()
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
