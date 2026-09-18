#!/usr/bin/env python
"""Create or update the stored AssemblyAI voice agent.

    uv run python scripts/provision_agent.py            # create, print the id
    uv run python scripts/provision_agent.py --update   # update the existing one
    uv run python scripts/provision_agent.py --show     # print what's stored

A stored agent is required rather than chosen: the API rejects a custom `llm`
on session.update, and keeping our own LLM is the point of the migration.

Because the persona, voice, tools and turn detection all live on the stored
agent, editing core/persona.py is not enough on its own — re-run this with
--update afterwards or the change never reaches a call.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from core import config  # noqa: E402
from voice import session_config  # noqa: E402

AGENTS_URL = "https://agents.assemblyai.com/v1/agents"


def _headers() -> dict:
    # This product wants a Bearer prefix; AssemblyAI's other APIs take the raw
    # key. Mixing them up gives a 401.
    return {
        "Authorization": f"Bearer {config.ASSEMBLYAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _require_key() -> None:
    if not config.ASSEMBLYAI_API_KEY:
        sys.exit("ASSEMBLYAI_API_KEY is not set.")


def show() -> None:
    _require_key()
    if not config.ASSEMBLYAI_AGENT_ID:
        sys.exit("ASSEMBLYAI_AGENT_ID is not set — nothing to show.")
    r = httpx.get(
        f"{AGENTS_URL}/{config.ASSEMBLYAI_AGENT_ID}", headers=_headers(), timeout=30
    )
    r.raise_for_status()
    body = r.json()
    print(json.dumps(body, indent=2)[:4000])


def provision(update: bool) -> None:
    _require_key()
    body = session_config.build_agent()

    if not body.get("llm"):
        # Without our LLM the agent falls back to AssemblyAI's managed model,
        # which knows nothing about the owner and would answer about a real
        # person from its own memory. That is the exact failure the grounding
        # rules exist to prevent, so refuse rather than publish it.
        sys.exit(
            "Refusing to provision without an LLM: set LLM_PROXY_URL and "
            "LLM_PROXY_SECRET first.\n"
            "The agent would otherwise fall back to AssemblyAI's managed model "
            "and invent facts about the owner."
        )

    if update:
        if not config.ASSEMBLYAI_AGENT_ID:
            sys.exit("--update needs ASSEMBLYAI_AGENT_ID set.")
        r = httpx.put(
            f"{AGENTS_URL}/{config.ASSEMBLYAI_AGENT_ID}",
            headers=_headers(),
            json=body,
            timeout=60,
        )
    else:
        r = httpx.post(AGENTS_URL, headers=_headers(), json=body, timeout=60)

    if r.status_code >= 400:
        sys.exit(f"{r.status_code}: {r.text[:800]}")

    data = r.json()
    agent_id = data.get("id", config.ASSEMBLYAI_AGENT_ID)

    print(f"  agent   {data.get('name')}")
    print(f"  voice   {config.ASSEMBLYAI_VOICE}")
    print(f"  tools   {', '.join(t['name'] for t in body['tools'])}")
    print(f"  llm     {body['llm'][0]['base_url']}")
    print()
    if update:
        print("Updated.")
    else:
        print(f"Created. Set this everywhere the backend runs:\n")
        print(f"  ASSEMBLYAI_AGENT_ID={agent_id}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--update", action="store_true", help="update the existing agent")
    g.add_argument("--show", action="store_true", help="print the stored agent")
    args = p.parse_args()

    if args.show:
        show()
    else:
        provision(update=args.update)


if __name__ == "__main__":
    main()
