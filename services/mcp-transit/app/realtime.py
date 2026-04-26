from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from google.transit import gtfs_realtime_pb2
from sqlalchemy import text

from app.config import settings

SUBWAY_FEED_BY_ROUTE = {
    "1": "gtfs", "2": "gtfs", "3": "gtfs", "4": "gtfs", "5": "gtfs", "6": "gtfs", "7": "gtfs", "S": "gtfs",
    "A": "gtfs-ace", "C": "gtfs-ace", "E": "gtfs-ace",
    "B": "gtfs-bdfm", "D": "gtfs-bdfm", "F": "gtfs-bdfm", "M": "gtfs-bdfm",
    "G": "gtfs-g",
    "J": "gtfs-jz", "Z": "gtfs-jz",
    "N": "gtfs-nqrw", "Q": "gtfs-nqrw", "R": "gtfs-nqrw", "W": "gtfs-nqrw",
    "L": "gtfs-l",
    "SI": "gtfs-si",
}

UPSERT_PREDICTION_SQL = text(
    """
    INSERT INTO app_transit_realtime_prediction
      (prediction_id, mode, stop_id, route_id, trip_id, direction_id, stop_sequence,
       arrival_time, departure_time, delay_seconds, schedule_relationship,
       prediction_rank, source, feed_timestamp, fetched_at, expires_at, raw_source)
    VALUES
      (:prediction_id, :mode, :stop_id, :route_id, :trip_id, :direction_id, :stop_sequence,
       :arrival_time, :departure_time, :delay_seconds, :schedule_relationship,
       :prediction_rank, :source, :feed_timestamp, NOW(), NOW() + (:ttl_seconds || ' seconds')::INTERVAL,
       CAST(:raw_source AS JSONB))
    ON CONFLICT (prediction_id) DO UPDATE SET
      arrival_time = EXCLUDED.arrival_time,
      departure_time = EXCLUDED.departure_time,
      delay_seconds = EXCLUDED.delay_seconds,
      schedule_relationship = EXCLUDED.schedule_relationship,
      prediction_rank = EXCLUDED.prediction_rank,
      feed_timestamp = EXCLUDED.feed_timestamp,
      fetched_at = NOW(),
      expires_at = EXCLUDED.expires_at,
      raw_source = EXCLUDED.raw_source
    """
)


def parse_ts(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)


def has_field(message: Any, field_name: str) -> bool:
    try:
        return message.HasField(field_name)
    except ValueError:
        return False


def prediction_id(*parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:32]
    return f"pred_{digest}"


def subway_feed_url(route_id: str) -> str:
    feed = SUBWAY_FEED_BY_ROUTE.get(route_id.upper())
    if not feed:
        raise ValueError(f"unsupported subway route_id for realtime feed: {route_id}")
    return f"{settings.mta_subway_feed_base_url}{feed}"


def fetch_feed(url: str, *, bus_key: str | None = None) -> gtfs_realtime_pb2.FeedMessage:
    headers: dict[str, str] = {}
    if settings.mta_api_key:
        headers["x-api-key"] = settings.mta_api_key
    params = {"key": bus_key} if bus_key else None
    with httpx.Client(timeout=settings.transit_realtime_request_timeout_seconds, headers=headers) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed


def iter_predictions(feed: gtfs_realtime_pb2.FeedMessage, *, mode: str, route_id: str, stop_id: str | None) -> list[dict[str, Any]]:
    feed_ts = parse_ts(feed.header.timestamp) if feed.header.timestamp else None
    rows: list[dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    target_route = route_id.upper()
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip_update = entity.trip_update
        trip = trip_update.trip
        trip_route = (trip.route_id or target_route).upper()
        if trip_route != target_route:
            continue
        for stu in trip_update.stop_time_update:
            if stop_id and stu.stop_id != stop_id:
                continue
            arrival_time = parse_ts(stu.arrival.time if has_field(stu, "arrival") else None)
            departure_time = parse_ts(stu.departure.time if has_field(stu, "departure") else None)
            event_time = departure_time or arrival_time
            if event_time and event_time < now_utc - timedelta(minutes=2):
                continue
            delay = None
            if has_field(stu, "departure") and has_field(stu.departure, "delay"):
                delay = stu.departure.delay
            elif has_field(stu, "arrival") and has_field(stu.arrival, "delay"):
                delay = stu.arrival.delay
            schedule_relationship = str(stu.schedule_relationship) if has_field(stu, "schedule_relationship") else None
            stop_sequence = int(stu.stop_sequence) if has_field(stu, "stop_sequence") else None
            direction_id = str(trip.direction_id) if has_field(trip, "direction_id") else None
            rows.append({
                "prediction_id": prediction_id(mode, trip_route, trip.trip_id, stu.stop_id, arrival_time, departure_time),
                "mode": mode,
                "stop_id": stu.stop_id,
                "route_id": trip_route,
                "trip_id": trip.trip_id or None,
                "direction_id": direction_id,
                "stop_sequence": stop_sequence,
                "arrival_time": arrival_time,
                "departure_time": departure_time,
                "delay_seconds": delay,
                "schedule_relationship": schedule_relationship,
                "prediction_rank": None,
                "source": "mta_subway_gtfs_rt" if mode == "subway" else "mta_bus_time_gtfs_rt",
                "feed_timestamp": feed_ts,
                "ttl_seconds": settings.transit_realtime_ttl_seconds,
                "raw_source": json.dumps({"entity_id": entity.id or None, "feed_timestamp": feed.header.timestamp or None}),
            })
    rows.sort(key=lambda row: row["departure_time"] or row["arrival_time"] or datetime.max)
    for index, row in enumerate(rows, start=1):
        row["prediction_rank"] = index
    return rows


def refresh_predictions(conn, *, mode: str, route_id: str, stop_id: str | None) -> dict[str, Any]:
    if not settings.transit_realtime_enabled:
        return {"enabled": False, "fetched": 0, "written": 0, "source": None}
    mode = mode.lower()
    route_id = route_id.upper()
    if mode == "subway":
        url = subway_feed_url(route_id)
        feed = fetch_feed(url)
    elif mode == "bus":
        if not settings.mta_bus_time_api_key:
            return {"enabled": True, "fetched": 0, "written": 0, "source": "mta_bus_time_gtfs_rt", "skipped_reason": "MTA_BUS_TIME_API_KEY not configured"}
        feed = fetch_feed(settings.mta_bus_gtfs_rt_trip_updates_url, bus_key=settings.mta_bus_time_api_key)
        url = settings.mta_bus_gtfs_rt_trip_updates_url
    else:
        raise ValueError(f"unsupported mode for realtime refresh: {mode}")

    rows = iter_predictions(feed, mode=mode, route_id=route_id, stop_id=stop_id)
    written = 0
    for row in rows[:200]:
        conn.execute(UPSERT_PREDICTION_SQL, row)
        written += 1
    return {"enabled": True, "fetched": len(rows), "written": written, "source": url}
