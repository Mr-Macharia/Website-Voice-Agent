"""The stored agent's definition, and the session that binds to it.

Originally this built a full inline `session.update`, which needs no
provisioning step. That is not possible here: the API rejects a custom `llm`
inline —

    BYO LLM config is not allowed on session.update;
    define it on a stored agent via POST /v1/agents

and keeping our own LLM is the whole point of the migration. So the agent is
stored, created by scripts/provision_agent.py from build_agent() below.

`agent_id` is mutually exclusive with every inline field, so the prompt, voice,
tools and turn detection all live on the stored agent. The browser sends only
the id. core/persona.py is still the single source of truth — provisioning
reads from it, so changing the persona means a deploy plus a re-provision.
"""

from __future__ import annotations

from core import config, persona
from core.adapters import assemblyai as tools

# AssemblyAI Voice Agent audio is PCM16 mono at 24 kHz, base64 inside JSON
# events. Note this differs from their streaming STT product, which takes raw
# binary frames at 16 kHz.
SAMPLE_RATE = 24_000

# Terms the STT most often gets wrong on this site. Keyterms bias recognition
# toward them; they cost nothing when unused.
_KEYTERMS = [
    config.OWNER_NAME,
    *config.OWNER_NAME.split(),
    "Agno",
    "AssemblyAI",
    "LiveKit",
    "pgvector",
]


def build_agent() -> dict:
    """The POST/PUT /v1/agents body.

    Turn detection is deliberately almost unconfigured. AssemblyAI's default is
    semantic — it decides the visitor has finished from what they said, not
    just from silence — and it paces itself to each speaker. Setting
    min_silence or max_silence turns that adaptive behaviour off for the whole
    session, so we set neither. interrupt_response is the one thing we state,
    and only because barge-in is central to the experience.
    """
    return {
        "name": f"{config.OWNER_NAME} site assistant",
        "system_prompt": persona.for_voice(),
        # Fixed text, never generated. See persona.GREETING for why: a
        # generated greeting leaked instruction text into live sessions.
        "greeting": persona.GREETING,
        "voice": {"voice_id": config.ASSEMBLYAI_VOICE},
        "tools": tools.get_tool_schemas(),
        "input": {
            "format": {"encoding": "audio/pcm", "sample_rate": SAMPLE_RATE},
            # Isolates the visitor's voice from background chatter, a TV, or
            # room echo before it reaches the transcription model. This is the
            # setting that stops the agent answering the television.
            "voice_focus": config.ASSEMBLYAI_VOICE_FOCUS,
            "transcription_mode": config.ASSEMBLYAI_TRANSCRIPTION_MODE,
            "keyterms": _KEYTERMS,
            "turn_detection": {"interrupt_response": True},
        },
        "output": {
            "voice": config.ASSEMBLYAI_VOICE,
            "format": {"encoding": "audio/pcm", "sample_rate": SAMPLE_RATE},
            "volume": 100,
        },
        "llm": _llm_config(),
    }


def build_session() -> dict:
    """The `session` object the browser sends as its first message.

    Just the id: binding to a stored agent and also sending any inline field is
    rejected outright.
    """
    return {"agent_id": config.ASSEMBLYAI_AGENT_ID}


def _llm_config() -> list[dict]:
    """Point the agent at our own LLM proxy.

    AssemblyAI accepts exactly one llm entry — there is no fallback list — and
    calls it server-to-server, so the URL must be public HTTPS. Our proxy is
    what keeps the Bedrock/xAI/OpenAI fallback chain alive behind that single
    stable URL, and it is the only remaining place guardrails can act on the
    reply text before it is spoken.

    An empty list means "use AssemblyAI's managed model". We never want that
    silently: the managed model knows nothing about the owner and would answer
    from its own memory, which is exactly the failure persona._GROUNDING exists
    to prevent. Provisioning refuses to write an agent without it.
    """
    if not (config.LLM_PROXY_URL and config.LLM_PROXY_SECRET):
        return []

    return [
        {
            "base_url": config.LLM_PROXY_URL.rstrip("/"),
            # The proxy decides the real upstream model; this is the name it
            # receives and is free to override.
            "model": config.BEDROCK_MODEL_ID or "deepseek.v3.2",
            # Not a provider key — a shared secret the proxy checks, so the
            # public endpoint isn't open to whoever finds it.
            "api_key": config.LLM_PROXY_SECRET,
        }
    ]
