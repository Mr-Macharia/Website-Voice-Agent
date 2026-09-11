"""Silence third-party loggers that bury the agent's own output.

ddgs pulls in Rust and HTTP/2 stacks (hickory, rustls, reqwest, primp, h2,
hpack, hyperframe) that log every DNS packet and every HPACK header frame at
DEBUG. A single web search produces thousands of lines.

Two things make this awkward, and both are why this lives here rather than in
livekit_worker.py:

1. `livekit_worker.py dev` sets the ROOT logger to DEBUG, so any logger created
   later inherits DEBUG.
2. Those libraries are imported lazily, INSIDE the tool call. Their loggers
   therefore do not exist when the worker configures logging at startup, so
   configuring them once at import time silences nothing.

quiet_noisy_loggers() is therefore called again immediately before each search.
It is idempotent and costs microseconds.
"""

from __future__ import annotations

import logging

NOISY_LOGGERS = (
    "hickory_net",
    "hickory_resolver",
    "hickory_proto",
    "h2",
    "hpack",
    "hpack.hpack",
    "hpack.table",
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


def quiet_noisy_loggers() -> None:
    """Pin noisy third-party loggers to WARNING. Safe to call repeatedly."""
    for name in NOISY_LOGGERS:
        log = logging.getLogger(name)
        log.setLevel(logging.WARNING)
        log.propagate = False
