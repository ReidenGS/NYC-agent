from __future__ import annotations

from uuid import uuid4

import httpx

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings

from app.models.area import AreaMetricsResponse, MapLayersResponse
from app.models.chat import ChatRequest, ChatResponseData, TraceSummaryItem
from app.models.common import ApiEnvelope, ApiError
from app.models.debug import TraceDebugResponse
from app.models.profile import ProfilePatchRequest, ProfileSnapshot, SessionCreateRequest, SessionCreateResponse
from app.models.transit import TransitRealtimeRequest, TransitRealtimeResponse
from app.models.weather import WeatherResponse
from app.services import mock_data
from app.services.orchestrator import OrchestratorService
from app.services.remote_orchestrator import RemoteOrchestratorClient
from app.stores.session_store import session_store

router = APIRouter()
orchestrator = OrchestratorService(session_store)
remote_orchestrator = RemoteOrchestratorClient()


def new_trace_id() -> str:
    return f'trace_{uuid4().hex[:16]}'


def envelope(data, session_id: str | None = None, trace_id: str | None = None):
    return ApiEnvelope(success=True, trace_id=trace_id or new_trace_id(), session_id=session_id, data=data, error=None)


def error_envelope(code: str, message: str, *, session_id: str | None = None, status_code: int = 400, retryable: bool = False):
    payload = ApiEnvelope(success=False, trace_id=new_trace_id(), session_id=session_id, data=None, error=ApiError(code=code, message=message, retryable=retryable, details={}))
    raise HTTPException(status_code=status_code, detail=payload.model_dump())


def ensure_session_exists(session_id: str) -> None:
    if settings.use_remote_orchestrator:
        try:
            remote_orchestrator.get_profile(session_id)
            return
        except Exception:
            pass
    if session_store.get(session_id) is None:
        error_envelope('VALIDATION_ERROR', 'session_id not found', session_id=session_id, status_code=404)


@router.get('/health')
def health() -> dict:
    return {'status': 'ok', 'service': 'api-gateway'}


@router.get('/ready')
def ready() -> dict:
    deps = {'orchestrator': 'in_process_mock_fallback', 'profile_store': 'memory'}
    if settings.use_remote_orchestrator:
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{settings.orchestrator_agent_url.rstrip('/')}/ready")
                response.raise_for_status()
            deps['orchestrator-agent'] = 'ok'
        except Exception as exc:
            deps['orchestrator-agent'] = f'unavailable: {exc}'
    return {'status': 'ok', 'dependencies': deps}


@router.post('/sessions', response_model=ApiEnvelope[SessionCreateResponse])
def create_session(request: SessionCreateRequest | None = None):
    if settings.use_remote_orchestrator:
        try:
            data = remote_orchestrator.create_session(request.model_dump() if request else {})
            return envelope(SessionCreateResponse.model_validate(data), session_id=data['session_id'])
        except Exception:
            pass
    profile = session_store.create()
    return envelope(SessionCreateResponse(session_id=profile.session_id, profile_snapshot=profile), session_id=profile.session_id)


@router.get('/sessions/{session_id}/profile', response_model=ApiEnvelope[ProfileSnapshot])
def get_profile(session_id: str):
    if settings.use_remote_orchestrator:
        try:
            return envelope(ProfileSnapshot.model_validate(remote_orchestrator.get_profile(session_id)), session_id=session_id)
        except Exception:
            pass
    profile = session_store.get(session_id)
    if profile is None:
        error_envelope('VALIDATION_ERROR', 'session_id not found', session_id=session_id, status_code=404)
    return envelope(profile, session_id=session_id)


@router.patch('/sessions/{session_id}/profile', response_model=ApiEnvelope[ProfileSnapshot])
def patch_profile(session_id: str, patch: ProfilePatchRequest):
    if settings.use_remote_orchestrator:
        try:
            return envelope(ProfileSnapshot.model_validate(remote_orchestrator.patch_profile(session_id, patch.model_dump(exclude_none=True))), session_id=session_id)
        except Exception:
            pass
    try:
        profile = session_store.patch(session_id, patch)
    except KeyError:
        error_envelope('VALIDATION_ERROR', 'session_id not found', session_id=session_id, status_code=404)
    return envelope(profile, session_id=session_id)


@router.post('/chat', response_model=ApiEnvelope[ChatResponseData])
def chat(request: ChatRequest):
    if not request.message.strip():
        error_envelope('VALIDATION_ERROR', 'message is required', session_id=request.session_id)
    if settings.use_remote_orchestrator:
        try:
            data = remote_orchestrator.chat(request.model_dump())
            return envelope(ChatResponseData.model_validate(data), session_id=request.session_id)
        except Exception:
            pass
    try:
        data = orchestrator.handle_chat(request)
    except KeyError:
        error_envelope('VALIDATION_ERROR', 'session_id not found', session_id=request.session_id, status_code=404)
    return envelope(data, session_id=request.session_id)


@router.get('/areas/{area_id}/metrics', response_model=ApiEnvelope[AreaMetricsResponse])
def area_metrics(area_id: str, session_id: str = Query(...)):
    ensure_session_exists(session_id)
    return envelope(mock_data.area_metrics(area_id), session_id=session_id)


@router.get('/areas/{area_id}/map-layers', response_model=ApiEnvelope[MapLayersResponse])
def area_map_layers(
    area_id: str,
    session_id: str = Query(...),
    layer_types: str = Query('choropleth,marker'),
    metric_names: str = Query('crime_index,entertainment,convenience'),
):
    ensure_session_exists(session_id)
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(
                f"{settings.data_sync_base_url.rstrip('/')}/areas/{area_id}/map-layers",
                params={'layer_types': layer_types, 'metric_names': metric_names},
            )
            response.raise_for_status()
            data = MapLayersResponse.model_validate(response.json())
            return envelope(data, session_id=session_id)
    except Exception:
        pass
    return envelope(mock_data.map_layers(area_id), session_id=session_id)


@router.get('/areas/{area_id}/weather', response_model=ApiEnvelope[WeatherResponse])
def area_weather(area_id: str, session_id: str = Query(...), hours: int = Query(6, ge=1, le=24)):
    ensure_session_exists(session_id)
    return envelope(mock_data.weather(area_id, hours=hours), session_id=session_id)


@router.post('/transit/realtime', response_model=ApiEnvelope[TransitRealtimeResponse])
def realtime_transit(request: TransitRealtimeRequest):
    ensure_session_exists(request.session_id)
    return envelope(mock_data.transit(request.origin, request.destination, request.mode), session_id=request.session_id)


@router.get('/sessions/{session_id}/recommendations')
def recommendations(session_id: str):
    ensure_session_exists(session_id)
    return envelope({'recommendations': []}, session_id=session_id)


@router.get('/debug/traces/{trace_id}', response_model=ApiEnvelope[TraceDebugResponse])
def trace_debug(trace_id: str):
    return envelope(TraceDebugResponse(trace_id=trace_id, trace_summary=[
        TraceSummaryItem(step='gateway.received', service='api-gateway', status='success', latency_ms=12),
        TraceSummaryItem(step='orchestrator.mock_dispatch', service='orchestrator-agent', status='success', latency_ms=96),
    ]))


@router.get('/debug/dependencies')
def debug_dependencies():
    data_sync = {'status': 'unknown', 'freshness': []}
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{settings.data_sync_base_url.rstrip('/')}/sync/freshness")
            if response.status_code == 404:
                status_response = client.get(f"{settings.data_sync_base_url.rstrip('/')}/sync/status", params={'limit': 5})
                status_response.raise_for_status()
                data_sync = {'status': 'ok', 'freshness': [], 'freshness_available': False, 'recent': status_response.json().get('recent', [])}
            else:
                response.raise_for_status()
                data_sync = {'status': 'ok', 'freshness_available': True, **response.json()}
    except Exception as exc:
        data_sync = {'status': 'unavailable', 'error': str(exc)}

    orchestrator_status = {'status': 'disabled'}
    if settings.use_remote_orchestrator:
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{settings.orchestrator_agent_url.rstrip('/')}/ready")
                response.raise_for_status()
                orchestrator_status = {'status': 'ok', **response.json()}
        except Exception as exc:
            orchestrator_status = {'status': 'unavailable', 'error': str(exc)}

    return envelope({'dependencies': {
        'orchestrator-agent': orchestrator_status,
        'mcp-services': 'behind_orchestrator_agents',
        'postgres': 'used_by_data_sync_and_mcp_services',
        'data-sync-service': data_sync,
    }})
