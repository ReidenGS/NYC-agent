from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.realtime import SUBWAY_FEED_BY_ROUTE, refresh_predictions

FIND_STOP_SQL = text(
    """
    SELECT stop_id, stop_name, mode, latitude, longitude, source
    FROM app_transit_stop_dimension
    WHERE mode = :mode AND stop_name ILIKE :query
    ORDER BY
      CASE
        WHEN lower(stop_name) = lower(:exact) THEN 0
        WHEN lower(stop_name) LIKE lower(:prefix) THEN 1
        ELSE 2
      END,
      stop_name ASC
    LIMIT 1
    """
)

QUERY_DEPARTURES_SQL = text(
    """
    SELECT prediction_id, mode, stop_id, route_id, trip_id, direction_id,
           arrival_time, departure_time, delay_seconds, prediction_rank,
           source, feed_timestamp, fetched_at, expires_at
    FROM app_transit_realtime_prediction
    WHERE mode = :mode
      AND route_id = :route_id
      AND stop_id = :stop_id
      AND expires_at >= NOW()
    ORDER BY COALESCE(departure_time, arrival_time) ASC
    LIMIT :limit
    """
)

QUERY_CACHE_SQL = text(
    """
    SELECT cache_key, session_id, origin_text, destination_text, mode,
           origin_stop_id, destination_stop_id, route_id,
           walking_to_stop_minutes, waiting_minutes, in_vehicle_minutes, total_minutes,
           recommended_leave_at, estimated_arrival_at, next_departures,
           realtime_used, fallback_used, source_snapshot, fetched_at, expires_at
    FROM app_transit_trip_result_cache
    WHERE cache_key = :cache_key AND expires_at >= NOW()
    LIMIT 1
    """
)

UPSERT_CACHE_SQL = text(
    """
    INSERT INTO app_transit_trip_result_cache
      (cache_key, session_id, origin_text, destination_text, mode,
       origin_stop_id, destination_stop_id, route_id,
       walking_to_stop_minutes, waiting_minutes, in_vehicle_minutes, total_minutes,
       recommended_leave_at, estimated_arrival_at, next_departures,
       realtime_used, fallback_used, source_snapshot, fetched_at, expires_at)
    VALUES
      (:cache_key, :session_id, :origin_text, :destination_text, :mode,
       :origin_stop_id, :destination_stop_id, :route_id,
       :walking_to_stop_minutes, :waiting_minutes, :in_vehicle_minutes, :total_minutes,
       :recommended_leave_at, :estimated_arrival_at, CAST(:next_departures AS JSONB),
       :realtime_used, :fallback_used, CAST(:source_snapshot AS JSONB), NOW(),
       NOW() + (:ttl_seconds || ' seconds')::INTERVAL)
    ON CONFLICT (cache_key) DO UPDATE SET
      origin_stop_id = EXCLUDED.origin_stop_id,
      destination_stop_id = EXCLUDED.destination_stop_id,
      route_id = EXCLUDED.route_id,
      walking_to_stop_minutes = EXCLUDED.walking_to_stop_minutes,
      waiting_minutes = EXCLUDED.waiting_minutes,
      in_vehicle_minutes = EXCLUDED.in_vehicle_minutes,
      total_minutes = EXCLUDED.total_minutes,
      recommended_leave_at = EXCLUDED.recommended_leave_at,
      estimated_arrival_at = EXCLUDED.estimated_arrival_at,
      next_departures = EXCLUDED.next_departures,
      realtime_used = EXCLUDED.realtime_used,
      fallback_used = EXCLUDED.fallback_used,
      source_snapshot = EXCLUDED.source_snapshot,
      fetched_at = NOW(),
      expires_at = EXCLUDED.expires_at
    """
)


def cache_key(*parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:32]
    return f"trip_{digest}"


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_miles * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def to_jsonable(row: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            output[key] = value.isoformat()
        else:
            output[key] = value
    return output


def find_stop(conn, *, mode: str, text_value: str) -> dict[str, Any] | None:
    result = conn.execute(
        FIND_STOP_SQL,
        {"mode": mode, "query": f"%{text_value}%", "exact": text_value, "prefix": f"{text_value}%"},
    )
    row = result.first()
    return dict(row._mapping) if row else None


def get_cached_commute(conn, *, session_id: str | None, origin: str, destination: str, mode: str, route_id: str | None) -> dict[str, Any] | None:
    key = cache_key(origin.lower(), destination.lower(), mode, route_id)
    row = conn.execute(QUERY_CACHE_SQL, {"cache_key": key}).first()
    return dict(row._mapping) if row else None


def query_departures(conn, *, mode: str, route_id: str, stop_id: str, limit: int = 2) -> list[dict[str, Any]]:
    refresh_meta = refresh_predictions(conn, mode=mode, route_id=route_id, stop_id=stop_id)
    rows = conn.execute(QUERY_DEPARTURES_SQL, {"mode": mode, "route_id": route_id, "stop_id": stop_id, "limit": limit}).fetchall()
    departures = [dict(row._mapping) for row in rows]
    for row in departures:
        row["refresh"] = refresh_meta
    return departures


def estimate_for_mode(
    conn,
    *,
    session_id: str | None,
    origin: str,
    destination: str,
    mode: str,
    route_id: str | None,
) -> dict[str, Any] | None:
    cached = get_cached_commute(conn, session_id=session_id, origin=origin, destination=destination, mode=mode, route_id=route_id)
    if cached:
        cached["cache_hit"] = True
        return cached

    origin_stop = find_stop(conn, mode=mode, text_value=origin)
    destination_stop = find_stop(conn, mode=mode, text_value=destination)
    if not origin_stop or not destination_stop:
        return None

    departures: list[dict[str, Any]] = []
    realtime_used = False
    refresh_error: str | None = None
    if route_id:
        try:
            departures = query_departures(conn, mode=mode, route_id=route_id, stop_id=origin_stop["stop_id"], limit=2)
            realtime_used = bool(departures)
        except Exception as exc:
            refresh_error = f"{type(exc).__name__}: {exc}"

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    first_departure = None
    if departures:
        first_departure = departures[0].get("departure_time") or departures[0].get("arrival_time")
    default_wait = 5 if mode == "subway" else 8
    waiting_minutes = max(0, math.ceil((first_departure - now_utc).total_seconds() / 60)) if first_departure else default_wait

    distance = haversine_miles(
        float(origin_stop["latitude"]),
        float(origin_stop["longitude"]),
        float(destination_stop["latitude"]),
        float(destination_stop["longitude"]),
    )
    avg_speed_mph = 17 if mode == "subway" else 11
    in_vehicle_minutes = max(3, math.ceil((distance / avg_speed_mph) * 60) + 3)
    walking_to_stop_minutes = 0
    total_minutes = walking_to_stop_minutes + waiting_minutes + in_vehicle_minutes
    estimated_arrival_at = now_utc + timedelta(minutes=total_minutes)
    output = {
        "cache_key": cache_key(origin.lower(), destination.lower(), mode, route_id),
        "session_id": session_id,
        "origin_text": origin,
        "destination_text": destination,
        "mode": mode,
        "origin_stop_id": origin_stop["stop_id"],
        "destination_stop_id": destination_stop["stop_id"],
        "route_id": route_id,
        "walking_to_stop_minutes": walking_to_stop_minutes,
        "waiting_minutes": waiting_minutes,
        "in_vehicle_minutes": in_vehicle_minutes,
        "total_minutes": total_minutes,
        "recommended_leave_at": now_utc,
        "estimated_arrival_at": estimated_arrival_at,
        "next_departures": [to_jsonable(row) for row in departures],
        "realtime_used": realtime_used,
        "fallback_used": not realtime_used,
        "source_snapshot": {
            "origin_stop": to_jsonable(origin_stop),
            "destination_stop": to_jsonable(destination_stop),
            "distance_miles": round(distance, 2),
            "estimation_method": "realtime_departure_plus_distance_speed" if realtime_used else "static_distance_speed_fallback",
            "refresh_error": refresh_error,
        },
        "cache_hit": False,
    }
    conn.execute(
        UPSERT_CACHE_SQL,
        {
            **output,
            "next_departures": json.dumps(output["next_departures"]),
            "source_snapshot": json.dumps(output["source_snapshot"]),
            "ttl_seconds": settings.transit_realtime_ttl_seconds,
        },
    )
    return output


def build_commute_result(
    conn,
    *,
    session_id: str | None,
    origin: str,
    destination: str,
    mode: str,
    route_id: str | None = None,
) -> dict[str, Any] | None:
    if mode == "either" and route_id:
        modes = ["subway"] if route_id.upper() in SUBWAY_FEED_BY_ROUTE else ["bus"]
    else:
        modes = ["subway", "bus"] if mode == "either" else [mode]
    candidates: list[dict[str, Any]] = []
    for candidate_mode in modes:
        if candidate_mode not in {"subway", "bus"}:
            continue
        candidate = estimate_for_mode(
            conn,
            session_id=session_id,
            origin=origin,
            destination=destination,
            mode=candidate_mode,
            route_id=route_id,
        )
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.get("total_minutes") or 9999, item["mode"]))[0]
