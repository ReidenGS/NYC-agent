from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.store import store
from nyc_agent_shared.time import now_iso

app = FastAPI(title='NYC Agent MCP Profile', version='0.1.0')


class ToolRequest(BaseModel):
    session_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


def mcp_success(tool: str, data: Any) -> dict[str, Any]:
    return {
        'status': 'success',
        'tool': tool,
        'data': data,
        'source': [{'name': 'mcp-profile-memory', 'type': 'mcp_profile', 'timestamp': now_iso()}],
        'timestamp': now_iso(),
        'confidence': 1.0,
        'data_quality': 'reference',
        'error': None,
    }


def mcp_error(tool: str, code: str, message: str, status: int = 400) -> None:
    raise HTTPException(status_code=status, detail={
        'status': 'error', 'tool': tool, 'data': None,
        'source': [], 'timestamp': now_iso(), 'confidence': 0.0,
        'data_quality': 'unknown',
        'error': {'code': code, 'message': message, 'retryable': status >= 500},
    })


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok', 'service': 'mcp-profile'}


@app.get('/ready')
def ready() -> dict[str, Any]:
    return {'status': 'ok', 'dependencies': store.backend_status()}


@app.get('/tools')
def tools() -> dict[str, list[str]]:
    return {'tools': ['create_session', 'get_snapshot', 'patch_slots', 'update_weights', 'update_comparison_areas', 'save_conversation_summary', 'save_last_response_refs', 'delete_session']}


@app.post('/tools/create_session')
def create_session(_: ToolRequest | None = None) -> dict[str, Any]:
    profile = store.create_session()
    return mcp_success('create_session', {'profile_snapshot': profile.model_dump()})


@app.post('/tools/get_snapshot')
def get_snapshot(request: ToolRequest) -> dict[str, Any]:
    if not request.session_id:
        mcp_error('get_snapshot', 'MISSING_ARGUMENT', 'session_id is required')
    profile = store.get(request.session_id)
    if profile is None:
        mcp_error('get_snapshot', 'DATA_NOT_FOUND', 'session not found', status=404)
    return mcp_success('get_snapshot', {'profile_snapshot': profile.model_dump()})


@app.post('/tools/patch_slots')
def patch_slots(request: ToolRequest) -> dict[str, Any]:
    if not request.session_id:
        mcp_error('patch_slots', 'MISSING_ARGUMENT', 'session_id is required')
    try:
        profile = store.patch_slots(request.session_id, request.arguments.get('slots', {}))
    except KeyError:
        mcp_error('patch_slots', 'DATA_NOT_FOUND', 'session not found', status=404)
    return mcp_success('patch_slots', {'profile_snapshot': profile.model_dump()})


@app.post('/tools/update_weights')
def update_weights(request: ToolRequest) -> dict[str, Any]:
    if not request.session_id:
        mcp_error('update_weights', 'MISSING_ARGUMENT', 'session_id is required')
    try:
        profile = store.update_weights(request.session_id, request.arguments.get('weights', {}))
    except KeyError:
        mcp_error('update_weights', 'DATA_NOT_FOUND', 'session not found', status=404)
    return mcp_success('update_weights', {'profile_snapshot': profile.model_dump()})


@app.post('/tools/update_comparison_areas')
def update_comparison_areas(request: ToolRequest) -> dict[str, Any]:
    if not request.session_id:
        mcp_error('update_comparison_areas', 'MISSING_ARGUMENT', 'session_id is required')
    try:
        profile = store.update_comparison_areas(request.session_id, request.arguments.get('comparison_areas', []))
    except KeyError:
        mcp_error('update_comparison_areas', 'DATA_NOT_FOUND', 'session not found', status=404)
    return mcp_success('update_comparison_areas', {'profile_snapshot': profile.model_dump()})


@app.post('/tools/save_conversation_summary')
def save_conversation_summary(request: ToolRequest) -> dict[str, Any]:
    if not request.session_id:
        mcp_error('save_conversation_summary', 'MISSING_ARGUMENT', 'session_id is required')
    try:
        profile = store.save_summary(request.session_id, str(request.arguments.get('conversation_summary', '')))
    except KeyError:
        mcp_error('save_conversation_summary', 'DATA_NOT_FOUND', 'session not found', status=404)
    return mcp_success('save_conversation_summary', {'profile_snapshot': profile.model_dump()})


@app.post('/tools/save_last_response_refs')
def save_last_response_refs(request: ToolRequest) -> dict[str, Any]:
    if not request.session_id:
        mcp_error('save_last_response_refs', 'MISSING_ARGUMENT', 'session_id is required')
    try:
        profile = store.save_last_response_refs(request.session_id, request.arguments.get('last_response_refs', {}))
    except KeyError:
        mcp_error('save_last_response_refs', 'DATA_NOT_FOUND', 'session not found', status=404)
    return mcp_success('save_last_response_refs', {'profile_snapshot': profile.model_dump()})


@app.post('/tools/delete_session')
def delete_session(request: ToolRequest) -> dict[str, Any]:
    if not request.session_id:
        mcp_error('delete_session', 'MISSING_ARGUMENT', 'session_id is required')
    deleted = store.delete_session(request.session_id)
    return mcp_success('delete_session', {'deleted': deleted})
