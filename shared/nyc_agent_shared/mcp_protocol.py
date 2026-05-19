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
import json
import inspect
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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


def create_sse_compatible_fastapi_app(mcp_server):
    """Create a FastAPI MCP app compatible with python-a2a's SSE MCPClient.

    python-a2a 0.5.10's MCPClient uses an SSE transport for URL-based servers:
    it posts JSON-RPC requests with ``Accept: text/event-stream`` and waits for
    ``data: {...}`` lines. The bundled ``create_fastapi_app`` returns plain JSON
    for the same JSON-RPC endpoint, so URL clients never see an SSE event. This
    wrapper keeps the same route surface and returns either plain JSON or a
    single-event SSE response depending on the request's Accept header.
    """
    from python_a2a.mcp.fastmcp import MCPResponse

    app = FastAPI(
        title=mcp_server.name,
        description=getattr(mcp_server, "description", ""),
        version=getattr(mcp_server, "version", "1.0.0"),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def json_rpc_response(*, result: Any = None, error: dict[str, Any] | None = None, request_id: Any = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        return payload

    def maybe_sse(payload: dict[str, Any], request: Request):
        if "text/event-stream" not in request.headers.get("accept", ""):
            return payload

        async def generate():
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    async def invoke_tool_response(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_def = getattr(mcp_server, "tools", {}).get(tool_name)
        if tool_def is None:
            raise ValueError(f"Tool not found: {tool_name}")

        result = tool_def.handler(**(arguments or {}))
        if inspect.isawaitable(result):
            result = await result

        if isinstance(result, str):
            text = result
        else:
            text = json.dumps(jsonable_encoder(result), ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "isError": False}

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}

    @app.get("/metadata")
    async def get_metadata():
        return mcp_server.get_metadata()

    @app.get("/tools")
    async def list_tools():
        return mcp_server.get_tools()

    @app.get("/resources")
    async def list_resources():
        return mcp_server.get_resources()

    @app.post("/tools/{tool_name}")
    async def call_tool(tool_name: str, request: Request):
        try:
            params = await request.json()
        except json.JSONDecodeError:
            params = {}

        try:
            return await invoke_tool_response(tool_name, params)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Error calling tool %s: %s", tool_name, exc)
            error_response = MCPResponse(
                content=[{"type": "text", "text": f"Error calling tool {tool_name}: {exc}"}],
                is_error=True,
            )
            return error_response.to_dict()

    @app.get("/resources/{path:path}")
    async def get_resource(path: str):
        try:
            response = await mcp_server.get_resource(path)
            return response.to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Error getting resource %s: %s", path, exc)
            error_response = MCPResponse(
                content=[{"type": "text", "text": f"Error getting resource {path}: {exc}"}],
                is_error=True,
            )
            return error_response.to_dict()

    @app.post("/")
    async def json_rpc_endpoint(request: Request):
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return maybe_sse(
                json_rpc_response(error={"code": -32700, "message": "Parse error"}, request_id=None),
                request,
            )

        if not isinstance(body, dict):
            return maybe_sse(
                json_rpc_response(error={"code": -32600, "message": "Invalid Request"}, request_id=None),
                request,
            )

        request_id = body.get("id")
        if body.get("jsonrpc") != "2.0":
            return maybe_sse(
                json_rpc_response(
                    error={"code": -32600, "message": "Invalid Request - jsonrpc must be '2.0'"},
                    request_id=request_id,
                ),
                request,
            )

        method = body.get("method")
        params = body.get("params") or {}

        try:
            if method == "initialize":
                payload = {
                    "protocolVersion": (params or {}).get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {
                        "name": getattr(mcp_server, "name", "mcp-server"),
                        "version": getattr(mcp_server, "version", "1.0.0"),
                    },
                }
                return maybe_sse(json_rpc_response(result=payload, request_id=request_id), request)

            if method in {"initialized", "notifications/initialized"}:
                return maybe_sse(json_rpc_response(result={}, request_id=request_id), request)

            if method == "tools/list":
                return maybe_sse(json_rpc_response(result={"tools": mcp_server.get_tools()}, request_id=request_id), request)

            if method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                if not tool_name:
                    return maybe_sse(
                        json_rpc_response(
                            error={"code": -32602, "message": "Missing required parameter: name"},
                            request_id=request_id,
                        ),
                        request,
                    )
                try:
                    response = await invoke_tool_response(tool_name, arguments)
                except ValueError:
                    return maybe_sse(
                        json_rpc_response(
                            error={"code": -32000, "message": f"Tool not found: {tool_name}"},
                            request_id=request_id,
                        ),
                        request,
                    )
                return maybe_sse(json_rpc_response(result=response, request_id=request_id), request)

            if method == "resources/list":
                return maybe_sse(
                    json_rpc_response(result={"resources": mcp_server.get_resources()}, request_id=request_id),
                    request,
                )

            if method == "resources/read":
                uri = params.get("uri")
                if not uri:
                    return maybe_sse(
                        json_rpc_response(
                            error={"code": -32602, "message": "Missing required parameter: uri"},
                            request_id=request_id,
                        ),
                        request,
                    )
                try:
                    response = await mcp_server.get_resource(uri)
                except ValueError:
                    return maybe_sse(
                        json_rpc_response(
                            error={"code": -32000, "message": f"Resource not found: {uri}"},
                            request_id=request_id,
                        ),
                        request,
                    )
                return maybe_sse(json_rpc_response(result=response.to_dict(), request_id=request_id), request)

            return maybe_sse(
                json_rpc_response(error={"code": -32601, "message": f"Method not found: {method}"}, request_id=request_id),
                request,
            )
        except Exception as exc:
            logger.error("Error handling JSON-RPC method %s: %s", method, exc)
            return maybe_sse(
                json_rpc_response(error={"code": -32603, "message": f"Internal error: {exc}"}, request_id=request_id),
                request,
            )

    return app
