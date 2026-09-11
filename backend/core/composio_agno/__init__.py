"""Composio → Agno provider.

Ported from Gichogu's WhatsApp agent (app/composio_agno). The __annotations__
fix in provider.py is the load-bearing part: Agno wraps tools with Pydantic's
validate_call, which reads __annotations__ rather than __signature__, and
without it every tool registration fails with a silent warning.
"""

from .provider import AgnoProvider

__all__ = ["AgnoProvider"]
