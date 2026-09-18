"""AssemblyAI Voice Agent API integration.

The voice path is one WebSocket from the browser to AssemblyAI, carrying STT,
turn detection, LLM replies and TTS. This package holds the pieces the backend
owns: the session configuration sent at connect, and the LLM proxy that keeps
our provider fallback chain alive.
"""
