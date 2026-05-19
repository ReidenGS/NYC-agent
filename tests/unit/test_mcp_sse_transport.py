from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = REPO_ROOT / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

from nyc_agent_shared.mcp_protocol import build_mcp_server, create_sse_compatible_fastapi_app


def _client() -> TestClient:
    mcp = build_mcp_server("test-mcp")

    @mcp.tool(name="echo", description="Echo a value.")
    def echo(value: str) -> dict[str, str]:
        return {"status": "success", "value": value}

    return TestClient(create_sse_compatible_fastapi_app(mcp))


def _sse_payload(response_text: str) -> dict:
    assert response_text.startswith("data: ")
    assert response_text.endswith("\n\n")
    return json.loads(response_text.removeprefix("data: ").strip())


def test_mcp_initialize_supports_sse_response() -> None:
    response = _client().post(
        "/",
        headers={"Accept": "text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payload = _sse_payload(response.text)
    assert payload["id"] == 1
    assert payload["result"]["serverInfo"]["name"] == "test-mcp"
    assert payload["result"]["capabilities"]["tools"] == {}


def test_mcp_tools_call_supports_sse_response() -> None:
    response = _client().post(
        "/",
        headers={"Accept": "text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"value": "hello"}},
        },
    )

    assert response.status_code == 200
    payload = _sse_payload(response.text)
    content = payload["result"]["content"]
    assert payload["id"] == 2
    assert json.loads(content[0]["text"]) == {"status": "success", "value": "hello"}


def test_mcp_tools_call_still_supports_plain_json_response() -> None:
    response = _client().post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"value": "plain"}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 3
    assert json.loads(payload["result"]["content"][0]["text"]) == {"status": "success", "value": "plain"}
