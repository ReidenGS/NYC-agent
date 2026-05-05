from __future__ import annotations

from typing import Any

from python_a2a import Message, MessageRole
from python_a2a.models.content import (
    ErrorContent,
    FunctionCallContent,
    FunctionParameter,
    FunctionResponseContent,
    TextContent,
)


def build_request_message(
    *,
    task_type: str,
    payload: dict[str, Any],
    trace_id: str,
    session_id: str | None,
    source_agent: str,
    target_agent: str,
) -> Message:
    content = {
        "task_type": task_type,
        "trace_id": trace_id,
        "session_id": session_id,
        "source_agent": source_agent,
        "target_agent": target_agent,
        "next_action": "call_agent",
        "payload": payload,
    }
    return Message(
        content=FunctionCallContent(
            name=task_type,
            parameters=[FunctionParameter(name="content", value=content)],
        ),
        role=MessageRole.USER,
        conversation_id=session_id,
    )


def build_response_message(
    request: Message,
    *,
    task_type: str,
    status: str,
    payload: dict[str, Any],
    source_agent: str,
    target_agent: str | None,
    trace_id: str | None,
    session_id: str | None,
    error: dict[str, Any] | None = None,
    confidence: dict[str, Any] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> Message:
    content = {
        "task_type": task_type,
        "status": status,
        "trace_id": trace_id,
        "session_id": session_id,
        "source_agent": source_agent,
        "target_agent": target_agent,
        "payload": payload,
        "confidence": confidence or {},
        "data_quality": data_quality or {},
        "error": error,
    }
    return Message(
        content=FunctionResponseContent(name=task_type, response=content),
        role=MessageRole.AGENT,
        parent_message_id=request.message_id,
        conversation_id=session_id or request.conversation_id,
    )


def extract_request_content(message: Message) -> dict[str, Any]:
    content = message.content
    if isinstance(content, FunctionCallContent) or getattr(content, "type", None) == "function_call":
        for param in getattr(content, "parameters", []) or []:
            if getattr(param, "name", None) == "content" and isinstance(getattr(param, "value", None), dict):
                return param.value
        return {
            "task_type": getattr(content, "name", None),
            "payload": {
                getattr(param, "name", ""): getattr(param, "value", None)
                for param in getattr(content, "parameters", []) or []
            },
            "session_id": message.conversation_id,
        }
    if isinstance(content, TextContent) or getattr(content, "type", None) == "text":
        import json

        text = getattr(content, "text", "") or "{}"
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("A2A text content must decode to an object")
        return parsed
    raise ValueError(f"unsupported A2A request content type: {getattr(content, 'type', None)}")


def request_content_to_legacy_a2a(content: dict[str, Any]):
    from nyc_agent_shared.schemas import A2ARequest

    return A2ARequest(
        trace_id=content["trace_id"],
        session_id=content.get("session_id"),
        source_agent=content.get("source_agent", "unknown-agent"),
        target_agent=content.get("target_agent", ""),
        task_type=content["task_type"],
        payload=content.get("payload") or {},
        debug=bool(content.get("debug", False)),
    )


def legacy_a2a_response_to_content(response) -> dict[str, Any]:
    data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    error = data.get("error")
    return {
        "task_type": data.get("task_type"),
        "status": data.get("status"),
        "trace_id": data.get("trace_id"),
        "session_id": data.get("session_id"),
        "source_agent": data.get("source_agent"),
        "target_agent": data.get("target_agent"),
        "payload": data.get("payload") or {},
        "confidence": data.get("confidence") or {},
        "data_quality": data.get("data_quality") or {},
        "error": error,
    }


def extract_response_content(message: Message) -> dict[str, Any]:
    content = message.content
    if isinstance(content, FunctionResponseContent) or getattr(content, "type", None) == "function_response":
        response = getattr(content, "response", None)
        if isinstance(response, dict):
            return response
        raise ValueError("A2A function response content must be an object")
    if isinstance(content, TextContent) or getattr(content, "type", None) == "text":
        import json

        parsed = json.loads(getattr(content, "text", "") or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("A2A text response must decode to an object")
        return parsed
    if isinstance(content, ErrorContent) or getattr(content, "type", None) == "error":
        return {
            "status": "error",
            "payload": {},
            "error": {
                "code": "A2A_ERROR",
                "message": getattr(content, "message", "A2A error"),
                "retryable": False,
            },
        }
    raise ValueError(f"unsupported A2A response content type: {getattr(content, 'type', None)}")
