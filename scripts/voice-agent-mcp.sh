#!/bin/sh
# Launcher for the voice-agent MCP server.
#
# Claude Code does not load .env, so `${VAR}` interpolation in .mcp.json would
# come up empty. Sourcing here keeps the secrets in the gitignored .env and out
# of .mcp.json, which is committed.
#
# stdout is reserved for JSON-RPC, so anything noisy must go to stderr.
set -e
DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ -f "$DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$DIR/.env"
  set +a
fi

cd "$DIR"
exec uv run python backend/voice_mcp/voice_agent_server.py "$@"
