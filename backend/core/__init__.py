"""Shared core for the personal-site agent.

Everything the agents need — config, database, persona, tools — lives here so
server.py (Agno/text), livekit_worker.py (LiveKit/voice) and the MCP server all
consume one implementation instead of three drifting copies.
"""
