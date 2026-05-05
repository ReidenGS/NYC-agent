"""Cut 8 — thin wrapper around `python_a2a.mcp.FastMCP`.

Each mcp-* service has an `app/mcp_server.py` that calls
`build_mcp_server(name)`, registers tools via `@mcp.tool()`, and exposes the
result as a parallel surface to the existing FastAPI `/tools/*` REST routes.

The wrapper degrades gracefully when `python-a2a` is not installed so the
underlying FastAPI tool routes keep working. Cut 8.5 (mounting / standalone
process) wires the FastMCP instance into the actual transport.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class _NoopMcp:
    """Stand-in for FastMCP when python-a2a is unavailable.

    `tool()` returns the original function unchanged so registration can be
    done at module import time without crashing. Other attributes raise on
    access so downstream callers fail loudly rather than silently no-op."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._tools: dict[str, Callable[..., Any]] = {}

    def tool(self, *args, **kwargs):
        def _decorator(fn: Callable[..., Any]):
            self._tools[fn.__name__] = fn
            return fn
        return _decorator

    def list_tools(self) -> list[str]:
        return sorted(self._tools)


def build_mcp_server(name: str):
    """Return a FastMCP instance, or a NoopMcp shim when unavailable."""
    try:
        from python_a2a.mcp import FastMCP  # type: ignore
    except Exception as exc:
        logger.info("FastMCP unavailable for %s (%s); using noop shim", name, exc)
        return _NoopMcp(name)
    try:
        return FastMCP(name=name)
    except Exception as exc:
        logger.warning("FastMCP(%s) construction failed (%s); using noop", name, exc)
        return _NoopMcp(name)
