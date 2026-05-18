"""FastAPI entry for orchestrator-agent.

After cut 9 this is the only orchestrator: LangGraph 6 nodes, PostgresSaver,
python-a2a-flavoured downstream calls. The legacy if/elif orchestrator (v1)
was deleted in the cleanup pass — git history preserves it if rollback is
ever needed.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from pydantic import BaseModel
from flask import request
from python_a2a import A2AServer, AgentCard as PyAgentCard, AgentSkill as PyAgentSkill
from python_a2a.server.http import create_flask_app

from app.a2a_adapter import call_agent
from app.config import settings
from app.graph import build_graph
from app.state import OrchestratorState
from nyc_agent_shared.schemas import AgentCard, AgentSkill

logger = logging.getLogger("orchestrator-agent")
logging.basicConfig(level=logging.INFO)


_pool: ConnectionPool | None = None
_graph = None  # compiled LangGraph
_area_center_cache: dict[str, dict[str, float]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool, _graph
    try:
        _pool = ConnectionPool(
            conninfo=settings.database_url_async,
            max_size=4,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        checkpointer = PostgresSaver(_pool)
        checkpointer.setup()  # idempotent — creates checkpoint tables on first run
        _graph = build_graph(checkpointer=checkpointer)
        logger.info("orchestrator-agent ready (PostgresSaver + LangGraph 6 nodes)")
    except Exception as exc:
        # Without a checkpointer the graph still runs, just no cross-turn memory.
        logger.warning("checkpointer init failed (%s); falling back to ephemeral", exc)
        _graph = build_graph(checkpointer=None)
    yield
    if _pool is not None:
        _pool.close()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


def _init_graph() -> None:
    global _pool, _graph
    if _graph is not None:
        return
    try:
        _pool = ConnectionPool(
            conninfo=settings.database_url_async,
            max_size=4,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        checkpointer = PostgresSaver(_pool)
        checkpointer.setup()
        _graph = build_graph(checkpointer=checkpointer)
        logger.info("orchestrator-agent ready (PostgresSaver + LangGraph 6 nodes)")
    except Exception as exc:
        logger.warning("checkpointer init failed (%s); falling back to ephemeral", exc)
        _graph = build_graph(checkpointer=None)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    debug: bool = False


def _trace_id() -> str:
    return f"trace_{uuid4().hex[:16]}"


def _envelope(data: dict[str, Any], session_id: str | None, trace_id: str) -> dict[str, Any]:
    return {
        "success": True,
        "trace_id": trace_id,
        "session_id": session_id,
        "data": data,
        "error": None,
    }


def _extract_profile_snapshot(response: dict[str, Any]) -> dict[str, Any]:
    payload = response.get("payload") or {}
    snapshot = payload.get("profile_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    mcp_result = payload.get("mcp_result") or {}
    mcp_data = mcp_result.get("data") or {}
    nested = mcp_data.get("profile_snapshot")
    if isinstance(nested, dict):
        return nested
    return {}


def _short_summary(question: str, state: dict[str, Any]) -> str:
    area = state.get("target_area_name") or state.get("target_area_id") or "未指定区域"
    agent_results = state.get("agent_results") or []
    tasks = []
    for item in agent_results:
        data = item if isinstance(item, dict) else item.model_dump()
        task = data.get("task_type")
        if task and task not in tasks:
            tasks.append(task)
    task_text = ", ".join(tasks) if tasks else state.get("intent") or "unknown"
    answer = str(state.get("final_answer") or "")
    summary = f"最近一轮：用户询问 {area} 的 {task_text}。回答要点：{answer[:260]}"
    return summary[:800]


def _last_response_refs(state: dict[str, Any]) -> dict[str, Any]:
    refs = []
    for item in state.get("agent_results") or []:
        data = item if isinstance(item, dict) else item.model_dump()
        refs.append({
            "agent": data.get("agent"),
            "task_type": data.get("task_type"),
            "status": data.get("status"),
        })
    return {
        "target_area_id": state.get("target_area_id"),
        "target_area_name": state.get("target_area_name"),
        "agent_results": refs,
    }


def _extract_map_points(state: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []

    area_id = state.get("target_area_id")
    area_name = state.get("target_area_name")
    if area_id:
        center = _area_center_cache.get(area_id)
        if center is None:
            try:
                with httpx.Client(timeout=settings.request_timeout_seconds) as client:
                    response = client.get(f"{settings.data_sync_base_url.rstrip('/')}/areas/{area_id}/metrics")
                    response.raise_for_status()
                    payload = response.json() or {}
                    lat = payload.get("latitude")
                    lon = payload.get("longitude")
                    if lat is not None and lon is not None:
                        center = {"latitude": float(lat), "longitude": float(lon)}
                        _area_center_cache[area_id] = center
            except Exception:
                center = None
        if center is None:
            logger.warning("target_area center unresolved from data-sync: area_id=%s", area_id)
        else:
            points.append({
                "id": f"target-area-{area_id}",
                "kind": "target_area",
                "label": area_name or area_id,
                "latitude": center["latitude"],
                "longitude": center["longitude"],
            })
    for item in state.get("agent_results") or []:
        result = item if isinstance(item, dict) else item.model_dump()
        payload = result.get("payload") or {}
        housing_result = payload.get("housing_result") or {}
        candidates = housing_result.get("listing_candidates") or payload.get("listing_candidates") or []
        for row in candidates:
            if not isinstance(row, dict):
                continue
            lat = row.get("latitude")
            lon = row.get("longitude")
            if lat is None or lon is None:
                continue
            try:
                latf = float(lat)
                lonf = float(lon)
            except (TypeError, ValueError):
                continue
            listing_id = row.get("listing_id") or f"listing-{len(points)}"
            label = row.get("formatted_address") or str(listing_id)
            subtitle_parts = []
            if row.get("bedroom_type"):
                subtitle_parts.append(str(row.get("bedroom_type")))
            if row.get("monthly_rent") is not None:
                subtitle_parts.append(f"${float(row.get('monthly_rent')):,.0f}")
            points.append({
                "id": f"listing-{listing_id}",
                "kind": "listing",
                "label": label,
                "subtitle": " · ".join(subtitle_parts) if subtitle_parts else None,
                "latitude": latf,
                "longitude": lonf,
            })

        neighborhood_result = payload.get("neighborhood_result") or {}
        derived = neighborhood_result.get("derived_metrics") or {}
        sample_points = derived.get("sample_points") or []
        domain = str(neighborhood_result.get("domain") or "")
        for row in sample_points:
            if not isinstance(row, dict):
                continue
            lat = row.get("latitude")
            lon = row.get("longitude")
            if lat is None or lon is None:
                continue
            try:
                latf = float(lat)
                lonf = float(lon)
            except (TypeError, ValueError):
                continue
            poi_id = row.get("poi_id") or f"poi-{len(points)}"
            label = row.get("name") or row.get("category_name") or str(poi_id)
            subtitle_parts = []
            if row.get("category_name"):
                subtitle_parts.append(str(row.get("category_name")))
            if row.get("source"):
                subtitle_parts.append(str(row.get("source")))
            points.append({
                "id": f"poi-{poi_id}",
                "kind": f"{domain or 'neighborhood'}_poi",
                "label": label,
                "subtitle": " · ".join(subtitle_parts) if subtitle_parts else None,
                "latitude": latf,
                "longitude": lonf,
            })
    return points


def _extract_map_layer_ids(state: dict[str, Any]) -> list[str]:
    area_id = state.get("target_area_id")
    if not area_id:
        return []

    requested_metrics: list[str] = []
    for item in state.get("agent_results") or []:
        result = item if isinstance(item, dict) else item.model_dump()
        if result.get("status") not in {"success", "no_data"}:
            continue
        payload = result.get("payload") or {}
        nres = payload.get("neighborhood_result") or {}
        domain = str(nres.get("domain") or "").lower()
        task_type = str(result.get("task_type") or "")
        if domain == "entertainment" or task_type == "neighborhood.entertainment_query":
            if "entertainment" not in requested_metrics:
                requested_metrics.append("entertainment")
        elif domain == "amenity" or task_type == "neighborhood.convenience_query":
            if "convenience" not in requested_metrics:
                requested_metrics.append("convenience")
        elif domain == "safety" or task_type == "neighborhood.crime_query":
            if "crime_index" not in requested_metrics:
                requested_metrics.append("crime_index")

    if not requested_metrics:
        return []

    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(
                f"{settings.data_sync_base_url.rstrip('/')}/areas/{area_id}/map-layers",
                params={"metric_names": ",".join(requested_metrics)},
            )
            response.raise_for_status()
            payload = response.json() or {}
            layers = payload.get("layers") or []
            ids = []
            for layer in layers:
                layer_id = layer.get("layer_id")
                if isinstance(layer_id, str) and layer_id not in ids:
                    ids.append(layer_id)
            return ids
    except Exception as exc:
        logger.warning("map layer id fetch failed area_id=%s metrics=%s err=%s", area_id, requested_metrics, exc)
        return []


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "orchestrator-agent"}


@app.get("/agent.json", response_model=AgentCard)
def agent_card() -> AgentCard:
    return AgentCard(
        name="orchestrator-agent",
        description="Routes user queries to NYC domain agents and composes final answers.",
        url="http://orchestrator-agent:8010",
        skills=[
            AgentSkill(
                id="orchestrate_chat",
                name="Orchestrate chat",
                description="Understand, route, execute, observe, respond, and persist session memory.",
                task_types=["chat.orchestrate"],
            )
        ],
        capabilities={"session_memory": "langgraph_checkpoint", "wire": "python_a2a"},
    )


@app.get("/ready")
def ready() -> dict[str, Any]:
    deps = {
        "graph": "compiled" if _graph is not None else "not_ready",
        "checkpointer": "postgres" if _pool is not None else "ephemeral",
        "openai_api_key": "configured" if settings.openai_api_key else "missing",
        "nl_to_sql_agent": settings.nl_to_sql_agent_url,
    }
    return {"status": "ok" if _graph is not None else "degraded", "dependencies": deps}


@app.post("/sessions")
def create_session() -> dict[str, Any]:
    """Cut 9: gateway used to call v1 for this; now we proxy through to
    profile-agent via A2A so the new orchestrator handles every request
    the gateway emits."""
    trace_id = _trace_id()
    response = call_agent(
        "profile",
        task_type="profile.create_session",
        session_id=None,
        payload={},
        trace_id=trace_id,
    )
    payload = response.get("payload") or {}
    snapshot = payload.get("profile_snapshot") or {}
    sid = snapshot.get("session_id")
    return _envelope({"session_id": sid, "profile_snapshot": snapshot}, sid, trace_id)


@app.get("/sessions/{session_id}/profile")
def get_profile(session_id: str) -> dict[str, Any]:
    trace_id = _trace_id()
    response = call_agent(
        "profile",
        task_type="profile.get_snapshot",
        session_id=session_id,
        payload={},
        trace_id=trace_id,
    )
    snapshot = _extract_profile_snapshot(response)
    return _envelope(snapshot, session_id, trace_id)


@app.patch("/sessions/{session_id}/profile")
def patch_profile(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    trace_id = _trace_id()
    slots = {k: v for k, v in body.items() if k in {
        "target_area_id", "budget", "target_destination",
        "max_commute_minutes", "preferences",
    }}
    if slots:
        call_agent("profile", task_type="profile.patch_slots",
                   session_id=session_id, payload={"slots": slots}, trace_id=trace_id)
    if body.get("weights"):
        call_agent("profile", task_type="profile.update_weights",
                   session_id=session_id, payload={"weights": body["weights"]}, trace_id=trace_id)
    # Re-fetch the canonical snapshot so the gateway sees the latest values.
    response = call_agent("profile", task_type="profile.get_snapshot",
                          session_id=session_id, payload={}, trace_id=trace_id)
    snapshot = _extract_profile_snapshot(response)
    return _envelope(snapshot, session_id, trace_id)


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    if _graph is None:
        raise HTTPException(503, detail="graph not ready")
    if not req.message.strip():
        raise HTTPException(400, detail="message is required")

    trace_id = _trace_id()
    config = {"configurable": {"thread_id": req.session_id}}

    initial = {
        "session_id": req.session_id,
        "trace_id": trace_id,
        "debug": req.debug,
        "current_user_message": req.message,
        "messages": [HumanMessage(content=req.message)],
        # Per-turn working values — reset to defaults so prior turn's intent
        # doesn't leak into this turn's gate/plan_execute.
        "intent": None,
        "detected_areas": [],
        "constraints": {},
        "persistable_field_updates": {},
        "agent_results": [],
        "final_missing_slots": [],
        "final_answer": "",
    }

    final_state: OrchestratorState = _graph.invoke(initial, config=config)

    # graph.invoke returns a dict-shaped state when using StateGraph(BaseModel).
    state_dict = final_state if isinstance(final_state, dict) else final_state.model_dump()
    conversation_summary = _short_summary(req.message, state_dict)
    last_response_refs = _last_response_refs(state_dict)
    profile_snapshot: dict[str, Any] = {}
    try:
        call_agent(
            "profile",
            task_type="profile.save_conversation_summary",
            session_id=req.session_id,
            payload={"conversation_summary": conversation_summary},
            trace_id=trace_id,
        )
        call_agent(
            "profile",
            task_type="profile.save_last_response_refs",
            session_id=req.session_id,
            payload={"last_response_refs": last_response_refs},
            trace_id=trace_id,
        )
        profile_resp = call_agent(
            "profile",
            task_type="profile.get_snapshot",
            session_id=req.session_id,
            payload={},
            trace_id=trace_id,
        )
        profile_snapshot = _extract_profile_snapshot(profile_resp)
    except Exception as exc:
        logger.warning("post-response profile memory persist failed (non-blocking): %s", exc)

    data = {
        "message_type": state_dict.get("final_message_type", "answer"),
        "answer": state_dict.get("final_answer", ""),
        "next_action": state_dict.get("final_next_action", "respond_final"),
        "missing_slots": state_dict.get("final_missing_slots") or [],
        "cards": [],
        "display_refs": {
            "map_layer_ids": _extract_map_layer_ids(state_dict),
            "display_result_ids": [],
            "map_points": _extract_map_points(state_dict),
        },
        "sources": state_dict.get("final_sources") or [],
        "data_quality": state_dict.get("final_data_quality", "reference"),
        "profile_snapshot": (
            profile_snapshot
            if profile_snapshot
            else {
                "session_id": req.session_id,
                "target_area_id": state_dict.get("target_area_id"),
                "target_area": (
                    {"area_id": state_dict.get("target_area_id"),
                     "area_name": state_dict.get("target_area_name") or state_dict.get("target_area_id")}
                    if state_dict.get("target_area_id") else None
                ),
                "missing_required_fields": state_dict.get("final_missing_slots") or [],
                "preferences": [],
                "weights": {"safety": 0.30, "commute": 0.30, "rent": 0.20,
                              "convenience": 0.10, "entertainment": 0.10},
                "conversation_summary": conversation_summary,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        ),
        "debug": (
            {
                "trace_id": trace_id,
                "trace_summary": [
                    {"step": "orchestrator.langgraph", "service": "orchestrator-agent",
                     "status": "success", "latency_ms": 0},
                ],
                "intent_detected": state_dict.get("intent"),
                "agent_results": [
                    r if isinstance(r, dict) else r.model_dump()
                    for r in (state_dict.get("agent_results") or [])
                ],
            }
            if req.debug else None
        ),
    }
    return _envelope(data, req.session_id, trace_id)


class OrchestratorAgentServer(A2AServer):
    def handle_message(self, message):
        from nyc_agent_shared.a2a_protocol import build_response_message, extract_request_content

        content = extract_request_content(message)
        task_type = content.get("task_type")
        if task_type != "chat.orchestrate":
            return build_response_message(
                message,
                task_type=task_type or "unknown",
                status="unsupported_data_request",
                payload={},
                source_agent="orchestrator-agent",
                target_agent=content.get("source_agent"),
                trace_id=content.get("trace_id"),
                session_id=content.get("session_id"),
                error={"code": "UNSUPPORTED_TASK", "message": f"unsupported orchestrator task: {task_type}", "retryable": False},
            )
        payload = content.get("payload") or {}
        result = chat(ChatRequest(session_id=content.get("session_id") or payload["session_id"], message=payload["message"], debug=bool(payload.get("debug"))))
        return build_response_message(
            message,
            task_type="chat.orchestrate",
            status="success",
            payload=result.get("data") or {},
            source_agent="orchestrator-agent",
            target_agent=content.get("source_agent"),
            trace_id=result.get("trace_id") or content.get("trace_id"),
            session_id=result.get("session_id") or content.get("session_id"),
        )


_init_graph()
server = OrchestratorAgentServer(
    agent_card=PyAgentCard(
        name="orchestrator-agent",
        description="意图理解、任务拆分、A2A 调度、结果合并",
        url="http://orchestrator-agent:8010",
        version="1.0.0",
        skills=[PyAgentSkill(name="chat.orchestrate", description="Understand, route, execute, observe, respond, and persist session memory.")],
        capabilities={"streaming": False, "async_tasks": False},
        default_input_modes=["text"],
        default_output_modes=["text", "data"],
    ),
    google_a2a_compatible=False,
)
server.agent_card.capabilities["streaming"] = False
app = create_flask_app(server)


@app.get("/health")
def flask_health():
    return health()


@app.get("/ready")
def flask_ready():
    return ready()


@app.post("/sessions")
def flask_create_session():
    return create_session()


@app.get("/sessions/<session_id>/profile")
def flask_get_profile(session_id: str):
    return get_profile(session_id)


@app.patch("/sessions/<session_id>/profile")
def flask_patch_profile(session_id: str):
    return patch_profile(session_id, request.get_json(silent=True) or {})


@app.post("/chat")
def flask_chat():
    body = request.get_json(silent=True) or {}
    return chat(ChatRequest(**body))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8010)
