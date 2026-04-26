from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from nyc_agent_shared.prompt_loader import list_prompts, load_prompt
from nyc_agent_shared.schemas import A2ARequest
from nyc_agent_shared.time import now_iso

app = FastAPI(title="NYC Agent Orchestrator Agent", version="0.1.0")

AREA_ALIASES: dict[str, dict[str, str]] = {
    "astoria": {"area_id": "QN0101", "area_name": "Astoria", "borough": "Queens"},
    "阿斯托利亚": {"area_id": "QN0101", "area_name": "Astoria", "borough": "Queens"},
    "lic": {"area_id": "QN0102", "area_name": "Long Island City", "borough": "Queens"},
    "long island city": {"area_id": "QN0102", "area_name": "Long Island City", "borough": "Queens"},
    "williamsburg": {"area_id": "BK0101", "area_name": "Williamsburg", "borough": "Brooklyn"},
    "greenpoint": {"area_id": "BK0102", "area_name": "Greenpoint", "borough": "Brooklyn"},
    "midtown": {"area_id": "MN0101", "area_name": "Midtown", "borough": "Manhattan"},
}


class ChatRequest(BaseModel):
    session_id: str
    message: str
    debug: bool = False
    client_context: dict[str, Any] | None = None


class SessionCreateRequest(BaseModel):
    client_timezone: str | None = None
    client_locale: str | None = None


class ProfilePatchRequest(BaseModel):
    target_area_id: str | None = None
    budget: dict[str, Any] | None = None
    target_destination: str | None = None
    max_commute_minutes: int | None = None
    weights: dict[str, float] | None = None
    preferences: list[str] | None = None


def trace_id() -> str:
    return f"trace_{uuid4().hex[:16]}"


def envelope(data: Any, session_id: str | None = None, trace: str | None = None) -> dict[str, Any]:
    return {"success": True, "trace_id": trace or trace_id(), "session_id": session_id, "data": data, "error": None}


def _profile_a2a(task_type: str, trace: str, session_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    req = A2ARequest(
        trace_id=trace,
        session_id=session_id,
        source_agent="orchestrator-agent",
        target_agent="profile-agent",
        task_type=task_type,
        payload=payload,
    )
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(f"{settings.profile_agent_url.rstrip('/')}/a2a", json=req.model_dump())
        response.raise_for_status()
        body = response.json()
    if body.get("status") != "success":
        raise HTTPException(status_code=502, detail=body)
    return body["payload"]["profile_snapshot"]


def _housing_a2a(task_type: str, trace: str, session_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    req = A2ARequest(
        trace_id=trace,
        session_id=session_id,
        source_agent="orchestrator-agent",
        target_agent="housing-agent",
        task_type=task_type,
        payload=payload,
    )
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(f"{settings.housing_agent_url.rstrip('/')}/a2a", json=req.model_dump())
        response.raise_for_status()
        return response.json()


def _neighborhood_a2a(task_type: str, trace: str, session_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    req = A2ARequest(
        trace_id=trace,
        session_id=session_id,
        source_agent="orchestrator-agent",
        target_agent="neighborhood-agent",
        task_type=task_type,
        payload=payload,
    )
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(f"{settings.neighborhood_agent_url.rstrip('/')}/a2a", json=req.model_dump())
        response.raise_for_status()
        return response.json()


def _transit_a2a(task_type: str, trace: str, session_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    req = A2ARequest(
        trace_id=trace,
        session_id=session_id,
        source_agent="orchestrator-agent",
        target_agent="transit-agent",
        task_type=task_type,
        payload=payload,
    )
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(f"{settings.transit_agent_url.rstrip('/')}/a2a", json=req.model_dump())
        response.raise_for_status()
        return response.json()


def _find_area(message: str) -> dict[str, str] | None:
    lower = message.lower()
    for alias, area in AREA_ALIASES.items():
        if alias in lower or alias in message:
            return area
    return None


def _extract_budget(message: str) -> int | None:
    if not any(token in message.lower() for token in ["budget", "rent", "租", "预算", "$", "美元"]):
        return None
    match = re.search(r"\$?\s?([1-9]\d{2,4})", message)
    return int(match.group(1)) if match else None


def _extract_bedroom(message: str) -> str | None:
    lower = message.lower()
    if "studio" in lower or "开间" in message:
        return "studio"
    if re.search(r"\b1\\s*(b|br|bed)\\b", lower) or "1b" in lower or "一居" in message:
        return "1br"
    if re.search(r"\b2\\s*(b|br|bed)\\b", lower) or "2b" in lower or "两居" in message:
        return "2br"
    return None


def _housing_task_type(message: str) -> str:
    lower = message.lower()
    if any(k in lower or k in message for k in ["listing", "房源", "公寓", "apartment", "有哪些房"]):
        return "housing.listing_search"
    return "housing.rent_query"


def _build_housing_payload(message: str, profile: dict[str, Any], area: dict[str, str] | None, budget: int | None) -> dict[str, Any]:
    active_area = area or profile.get("target_area") or {}
    profile_budget = profile.get("budget") or {}
    budget_value = budget or profile_budget.get("max")
    slots: dict[str, Any] = {
        "area_id": {"value": active_area.get("area_id") or profile.get("target_area_id"), "source": "user_explicit" if area else "session_memory", "confidence": 0.95 if area else 0.85},
        "area_name": {"value": active_area.get("area_name"), "source": "user_explicit" if area else "session_memory", "confidence": 0.95 if area else 0.85},
    }
    bedroom = _extract_bedroom(message)
    if bedroom:
        slots["bedroom_type"] = {"value": bedroom, "source": "user_explicit", "confidence": 0.95}
    if budget_value:
        slots["budget_monthly"] = {"value": float(budget_value), "source": "user_explicit" if budget else "session_memory", "confidence": 0.95 if budget else 0.85}
    return {
        "domain_user_query": message,
        "slots": slots,
        "domain_context": {"currency": "USD", "listing_limit": 5},
    }


def _neighborhood_task_type(message: str) -> str:
    lower = message.lower()
    if any(k in lower or k in message for k in ["安全", "犯罪", "治安", "偷", "抢劫", "safe", "crime", "theft", "robbery"]):
        return "neighborhood.crime_query"
    if any(k in lower or k in message for k in ["超市", "便利", "公园", "学校", "图书馆", "药店", "医院", "健身", "amenity", "supermarket", "park", "library", "school", "pharmacy"]):
        return "neighborhood.convenience_query"
    if any(k in lower or k in message for k in ["娱乐", "酒吧", "餐厅", "咖啡", "影院", "夜生活", "博物馆", "bar", "restaurant", "cafe", "cinema", "nightlife"]):
        return "neighborhood.entertainment_query"
    return "area.metrics_query"


def _is_neighborhood_query(message: str) -> bool:
    return _neighborhood_task_type(message) != "area.metrics_query" or any(k in message.lower() or k in message for k in ["附近怎么样", "这个区怎么样", "区域怎么样", "nearby", "neighborhood"])


def _build_neighborhood_payload(message: str, profile: dict[str, Any], area: dict[str, str] | None) -> dict[str, Any]:
    active_area = area or profile.get("target_area") or {}
    return {
        "domain_user_query": message,
        "slots": {
            "area_id": {"value": active_area.get("area_id") or profile.get("target_area_id"), "source": "user_explicit" if area else "session_memory", "confidence": 0.95 if area else 0.85},
            "area_name": {"value": active_area.get("area_name"), "source": "user_explicit" if area else "session_memory", "confidence": 0.95 if area else 0.85},
        },
        "domain_context": {"window_days": 30, "point_limit": 20, "map_layer_requests": []},
    }


def _is_transit_query(message: str) -> bool:
    lower = message.lower()
    return any(k in lower or k in message for k in ["地铁", "公交", "下一班", "出发", "通勤", "多久能到", "subway", "bus", "train", "commute", "departure"])


def _transit_task_type(message: str) -> str:
    lower = message.lower()
    if any(k in lower or k in message for k in ["下一班", "什么时候来", "什么时候出发", "departure", "next train", "next bus"]):
        return "transit.next_departure"
    return "transit.realtime_commute"


def _extract_transit_mode(message: str) -> str | None:
    lower = message.lower()
    if "公交" in message or "bus" in lower:
        return "bus"
    if "地铁" in message or "subway" in lower or "train" in lower:
        return "subway"
    if "都可以" in message or "either" in lower:
        return "either"
    return None


def _extract_route_id(message: str) -> str | None:
    match = re.search(r"\b([A-Z]\d{0,2}|[1-7])\s*(线|train|bus)?\b", message.upper())
    return match.group(1) if match else None


def _build_transit_payload(message: str) -> dict[str, Any]:
    mode = _extract_transit_mode(message)
    task_type = _transit_task_type(message)
    slots: dict[str, Any] = {}
    if mode:
        slots["mode"] = {"value": mode, "source": "user_explicit", "confidence": 0.9}
    if task_type == "transit.next_departure":
        route = _extract_route_id(message)
        if route:
            slots["route_id"] = {"value": route, "source": "user_explicit", "confidence": 0.8}
        station_match = re.search(r"(?:在|从|at)\s*([A-Za-z0-9 .'/&-]{2,40}|[\u4e00-\u9fffA-Za-z0-9 .'/&-]{2,40})", message)
        if station_match:
            slots["stop_name"] = {"value": station_match.group(1).strip(), "source": "user_explicit", "confidence": 0.6}
        if "manhattan" in message.lower() or "曼哈顿" in message:
            slots["direction"] = {"value": "toward Manhattan", "source": "user_explicit", "confidence": 0.85}
    else:
        match = re.search(r"从(.+?)(?:到|去)(.+?)(?:坐|要|多久|$)", message)
        if match:
            slots["origin"] = {"value": match.group(1).strip(), "source": "user_explicit", "confidence": 0.8}
            slots["destination"] = {"value": match.group(2).strip(), "source": "user_explicit", "confidence": 0.8}
    return {"domain_user_query": message, "slots": slots, "domain_context": {"departure_count": 2, "cache_ttl_seconds": 60}}


def _needs_area(message: str) -> bool:
    lower = message.lower()
    keywords = ["安全", "犯罪", "房租", "租金", "预算", "附近", "这个区", "区域", "便利", "娱乐", "超市", "酒吧", "rent", "housing", "safe", "crime", "nearby", "area", "amenity"]
    return any(k in lower or k in message for k in keywords)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "orchestrator-agent", "prompts_loaded": len(list_prompts())}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.profile_agent_url.rstrip('/')}/ready")
            response.raise_for_status()
        profile = "ok"
    except Exception as exc:
        profile = f"unavailable: {exc}"
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.housing_agent_url.rstrip('/')}/ready")
            response.raise_for_status()
        housing = "ok"
    except Exception as exc:
        housing = f"unavailable: {exc}"
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.neighborhood_agent_url.rstrip('/')}/ready")
            response.raise_for_status()
        neighborhood = "ok"
    except Exception as exc:
        neighborhood = f"unavailable: {exc}"
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.transit_agent_url.rstrip('/')}/ready")
            response.raise_for_status()
        transit = "ok"
    except Exception as exc:
        transit = f"unavailable: {exc}"
    status = "ok" if profile == "ok" and housing == "ok" and neighborhood == "ok" and transit == "ok" else "degraded"
    return {"status": status, "dependencies": {"profile-agent": profile, "housing-agent": housing, "neighborhood-agent": neighborhood, "transit-agent": transit}}


@app.get("/debug/prompts")
def debug_prompts() -> dict[str, Any]:
    names = list_prompts()
    return {
        "prompts": names,
        "understand_prompt_preview": load_prompt("orchestrator/understand_prompt.txt")[:300]
        if "orchestrator/understand_prompt.txt" in names
        else None,
    }


@app.post("/sessions")
def create_session(_: SessionCreateRequest | None = None) -> dict[str, Any]:
    trace = trace_id()
    profile = _profile_a2a("profile.create_session", trace, None, {})
    return envelope({"session_id": profile["session_id"], "profile_snapshot": profile}, profile["session_id"], trace)


@app.get("/sessions/{session_id}/profile")
def get_profile(session_id: str) -> dict[str, Any]:
    trace = trace_id()
    profile = _profile_a2a("profile.get_snapshot", trace, session_id, {})
    return envelope(profile, session_id, trace)


@app.patch("/sessions/{session_id}/profile")
def patch_profile(session_id: str, patch: ProfilePatchRequest) -> dict[str, Any]:
    trace = trace_id()
    slots: dict[str, Any] = {}
    if patch.target_area_id:
        slots["target_area_id"] = patch.target_area_id
    if patch.budget and patch.budget.get("max") is not None:
        slots["budget_monthly"] = patch.budget["max"]
    if patch.target_destination:
        slots["target_destination"] = patch.target_destination
    if patch.max_commute_minutes:
        slots["max_commute_minutes"] = patch.max_commute_minutes
    if patch.preferences is not None:
        slots["preferences"] = patch.preferences
    profile = _profile_a2a("profile.patch_slots", trace, session_id, {"slots": slots})
    if patch.weights:
        profile = _profile_a2a("profile.update_weights", trace, session_id, {"weights": patch.weights})
    return envelope(profile, session_id, trace)


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    trace = trace_id()
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    profile = _profile_a2a("profile.get_snapshot", trace, request.session_id, {})
    slots: dict[str, Any] = {}
    area = _find_area(message)
    if area and not profile.get("target_area_id"):
        slots["target_area_id"] = area["area_id"]
    budget = _extract_budget(message)
    if budget:
        slots["budget_monthly"] = budget
    if slots:
        profile = _profile_a2a("profile.patch_slots", trace, request.session_id, {"slots": slots})

    active_area = area or profile.get("target_area")
    if _needs_area(message) and not active_area:
        data = {
            "message_type": "follow_up",
            "answer": "你想了解纽约哪个具体区域？例如 Astoria、Long Island City、Williamsburg。",
            "next_action": "ask_follow_up",
            "profile_snapshot": profile,
            "missing_slots": ["target_area"],
            "cards": [],
            "display_refs": {"map_layer_ids": [], "display_result_ids": []},
            "sources": [],
            "data_quality": "unknown",
            "debug": _debug(request.debug, trace, [("orchestrator.missing_slot", "orchestrator-agent", "success", 18, None)]),
        }
        return envelope(data, request.session_id, trace)

    lower = message.lower()
    area_name = (active_area or {}).get("area_name", "当前区域")
    sources = [{"name": "orchestrator-agent rule fallback", "type": "system", "updated_at": now_iso()}]

    if _is_transit_query(message):
        task_type = _transit_task_type(message)
        transit_response = _transit_a2a(task_type, trace, request.session_id, _build_transit_payload(message))
        if transit_response.get("status") == "clarification_required":
            answer = transit_response.get("payload", {}).get("clarification") or "我还需要一个通勤相关信息。"
            next_action = "ask_follow_up"
            missing = transit_response.get("payload", {}).get("missing_slots", [])
            sources = [{"name": "transit-agent", "type": "a2a", "updated_at": now_iso()}]
        elif transit_response.get("status") == "no_data":
            answer = "当前实时通勤数据表中没有找到匹配结果。可以确认站点/线路/方向，或者等后续接入 MTA 实时 API 后再查。"
            next_action = "respond_final"
            missing = []
            sources = [{"name": "mcp-transit", "type": "fixed_tool", "updated_at": now_iso()}]
        else:
            result = transit_response.get("payload", {}).get("transit_result", {})
            metrics = result.get("derived_metrics", {})
            if result.get("transit_result_type") == "next_departure":
                departures = metrics.get("departures") or []
                if departures:
                    first = departures[0]
                    answer = f"{metrics.get('route_id')} 线 {metrics.get('stop_name')} 往 {metrics.get('direction')} 的下一班预计出发时间是 {first.get('departure_time') or first.get('arrival_time')}。"
                else:
                    answer = "当前实时 feed 没有返回匹配的下一班车。"
            else:
                answer = (
                    f"从 {metrics.get('origin_text') or metrics.get('origin')} 到 {metrics.get('destination_text') or metrics.get('destination')} "
                    f"坐 {metrics.get('mode')} 的缓存通勤时间约为 {metrics.get('total_minutes')} 分钟。"
                )
            next_action = "respond_final"
            missing = []
            sources = [{"name": "transit-agent", "type": "a2a", "updated_at": now_iso()}, {"name": "mcp-transit", "type": "fixed_tool", "updated_at": now_iso()}]
    elif any(k in message or k in lower for k in ["预算", "房租", "租金", "rent", "1b", "1br", "listing", "房源", "公寓"]):
        housing_payload = _build_housing_payload(message, profile, area, budget)
        housing_response = _housing_a2a(_housing_task_type(message), trace, request.session_id, housing_payload)
        if housing_response.get("status") == "clarification_required":
            clarification = housing_response.get("payload", {}).get("clarification") or "我还需要一个租房相关条件。"
            answer = clarification
            next_action = "ask_follow_up"
            missing = housing_response.get("payload", {}).get("missing_slots", [])
            sources = [{"name": "housing-agent", "type": "a2a", "updated_at": now_iso()}]
        elif housing_response.get("status") == "unsupported_data_request":
            payload = housing_response.get("payload", {})
            answer = f"当前数据库暂时不能回答这个租房问题：{payload.get('unsupported_reason', '缺少对应字段')} {payload.get('suggested_alternative', '')}".strip()
            next_action = "respond_final"
            missing = []
            sources = [{"name": "housing-agent", "type": "a2a", "updated_at": now_iso()}]
        elif housing_response.get("status") == "no_data":
            result = housing_response.get("payload", {}).get("housing_result", {})
            answer = f"当前数据库中没有找到 {area_name} 的匹配租房数据。{result.get('suggested_alternative', '可以先运行租金同步任务或换一个户型查询。')}"
            next_action = "respond_final"
            missing = []
            sources = [{"name": "mcp-sql", "type": "sql", "updated_at": now_iso()}]
        else:
            result = housing_response.get("payload", {}).get("housing_result", {})
            metrics = result.get("derived_metrics", {})
            context = result.get("data_context", {})
            bedroom = metrics.get("bedroom_type") or _extract_bedroom(message) or "该户型"
            if result.get("housing_result_type") == "budget_fit":
                answer = (
                    f"{area_name} 的 {bedroom} 当前查询结果："
                    f"最低约 ${metrics.get('rent_min')}, 中位数约 ${metrics.get('rent_median')}, 最高约 ${metrics.get('rent_max')}。"
                    f"你的预算是 ${metrics.get('budget_monthly')}，预算匹配判断为 {metrics.get('budget_fit') or 'unknown'}。"
                    f"数据库中找到 {metrics.get('matching_listing_count', 0)} 条预算内 active 房源。"
                )
            else:
                answer = (
                    f"{area_name} 的租金数据已查到。"
                    f"数据来源类型：{context.get('source_type')}；"
                    f"如果是具体户型，租金区间约为 ${metrics.get('rent_min')} - ${metrics.get('rent_max')}，中位数约 ${metrics.get('rent_median')}。"
                )
            if context.get("benchmark_only"):
                answer += " 注意：当前只命中租金基准数据，不代表实时房源库存。"
            next_action = "respond_final"
            missing = []
            sources = [{"name": "housing-agent", "type": "a2a", "updated_at": now_iso()}, {"name": "mcp-sql", "type": "sql", "updated_at": now_iso()}]
    elif _is_neighborhood_query(message):
        task_type = _neighborhood_task_type(message)
        neighborhood_response = _neighborhood_a2a(task_type, trace, request.session_id, _build_neighborhood_payload(message, profile, area))
        if neighborhood_response.get("status") == "clarification_required":
            clarification = neighborhood_response.get("payload", {}).get("clarification") or "我需要知道你想查询哪个区域。"
            answer = clarification
            next_action = "ask_follow_up"
            missing = neighborhood_response.get("payload", {}).get("missing_slots", [])
            sources = [{"name": "neighborhood-agent", "type": "a2a", "updated_at": now_iso()}]
        elif neighborhood_response.get("status") == "unsupported_data_request":
            payload = neighborhood_response.get("payload", {})
            answer = f"当前数据库暂时不能回答这个区域问题：{payload.get('unsupported_reason', '缺少对应字段')} {payload.get('suggested_alternative', '')}".strip()
            next_action = "respond_final"
            missing = []
            sources = [{"name": "neighborhood-agent", "type": "a2a", "updated_at": now_iso()}]
        elif neighborhood_response.get("status") == "no_data":
            result = neighborhood_response.get("payload", {}).get("neighborhood_result", {})
            answer = f"当前数据库中没有找到 {area_name} 的匹配区域画像数据。{result.get('suggested_alternative', '可以先运行对应数据同步任务后再查。')}"
            next_action = "respond_final"
            missing = []
            sources = [{"name": "mcp-sql", "type": "sql", "updated_at": now_iso()}]
        else:
            result = neighborhood_response.get("payload", {}).get("neighborhood_result", {})
            metrics = result.get("derived_metrics", {})
            result_type = result.get("neighborhood_result_type")
            if result_type in {"safety_summary", "crime_breakdown"}:
                answer = (
                    f"{area_name} 的安全数据查询结果：近 30 天犯罪数为 {metrics.get('total_crime_count_30d')}，"
                    f"犯罪指数为 {metrics.get('crime_index_100')}，风险等级参考为 {metrics.get('safety_level')}。"
                )
                if metrics.get("crime_count_by_category"):
                    top = metrics["crime_count_by_category"][:3]
                    answer += " 主要犯罪类别：" + "、".join(f"{row.get('offense_category')}({row.get('crime_count')})" for row in top) + "。"
            elif result_type in {"amenity_summary", "amenity_breakdown"}:
                top = metrics.get("top_categories") or []
                answer = f"{area_name} 的便利设施总数为 {metrics.get('total_count')}，密度参考为 {metrics.get('poi_density_level')}。"
                if top:
                    answer += " 主要分类：" + "、".join(f"{row.get('category_name')}({row.get('poi_count')})" for row in top[:5]) + "。"
            elif result_type in {"entertainment_summary", "entertainment_breakdown"}:
                top = metrics.get("top_categories") or []
                answer = f"{area_name} 的娱乐设施总数为 {metrics.get('total_count')}，密度参考为 {metrics.get('poi_density_level')}。"
                if top:
                    answer += " 主要分类：" + "、".join(f"{row.get('category_name')}({row.get('poi_count')})" for row in top[:5]) + "。"
            else:
                raw = metrics.get("metrics") or {}
                answer = (
                    f"{area_name} 的区域概览：犯罪数 {raw.get('crime_count_30d')}，"
                    f"便利设施 {raw.get('convenience_facility_count')}，娱乐设施 {raw.get('entertainment_poi_count')}，"
                    f"交通站点 {raw.get('transit_station_count')}。"
                )
            next_action = "respond_final"
            missing = []
            sources = [{"name": "neighborhood-agent", "type": "a2a", "updated_at": now_iso()}, {"name": "mcp-sql", "type": "sql", "updated_at": now_iso()}]
    elif any(k in message or k in lower for k in ["你是谁", "能做什么", "who are you"]):
        answer = "我是一个纽约租房与生活区域决策助手，主要帮助刚到纽约的人理解不同区域的安全、租金、通勤、便利设施和娱乐设施，并根据你的偏好逐步缩小候选居住区域。"
        next_action = "respond_final"
        missing = []
    else:
        answer = f"我先按 {area_name} 来看。A2A 链路已接入 profile-agent 和 mcp-profile；后续会继续把 housing、neighborhood、transit、weather 领域 Agent 接进来。你可以继续问这个区域的房租、安全、通勤或设施。"
        next_action = "respond_final"
        missing = []

    refs = {"last_intents": ["housing.rent_query" if "租" in message or "rent" in lower else "area.metrics_query"], "sources": sources}
    _profile_a2a("profile.save_last_response_refs", trace, request.session_id, {"last_response_refs": refs})

    data = {
        "message_type": "answer" if not missing else "follow_up",
        "answer": answer,
        "next_action": next_action,
        "profile_snapshot": profile,
        "missing_slots": missing,
        "cards": [],
        "display_refs": {"map_layer_ids": [], "display_result_ids": []},
        "sources": sources,
        "data_quality": "reference",
        "debug": _debug(
            request.debug,
            trace,
            [
                ("orchestrator.received", "orchestrator-agent", "success", 12, None),
                ("profile.get_snapshot", "profile-agent", "success", 40, "mcp-profile"),
            ],
        ),
    }
    return envelope(data, request.session_id, trace)


def _debug(enabled: bool, trace: str, rows: list[tuple[str, str, str, int, str | None]]) -> dict[str, Any] | None:
    if not enabled:
        return None
    return {
        "trace_summary": [
            {"step": step, "service": service, "status": status, "latency_ms": latency, "mcp": mcp}
            for step, service, status, latency, mcp in rows
        ],
        "trace_id": trace,
    }
