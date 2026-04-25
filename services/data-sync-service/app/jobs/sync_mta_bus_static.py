"""sync_mta_bus_static — pull MTA static bus GTFS stops into stop dimension.

Source: MTA official static GTFS bus zip feeds from the developer resources
page. The bus GTFS is split into six zip files: Bronx, Brooklyn, Manhattan,
Queens, Staten Island, and MTA Bus Company.

Field mapping (GTFS stops.txt -> app_transit_stop_dimension):
  stop_id                -> stop_id
  stop_name              -> stop_name
  stop_lat               -> latitude
  stop_lon               -> longitude
  parent_station         -> parent_station_id (usually blank for bus)
  wheelchair_boarding    -> wheelchair_boarding
  feed name              -> source='mta_bus_static_gtfs'

After upsert, transit_station_count is refreshed from both subway and bus
stops through _transit_metrics_refresh.refresh_transit_station_count().
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from typing import Any

import httpx
from sqlalchemy import text

from app.db.session import db_session
from app.jobs._transit_metrics_refresh import refresh_transit_station_count
from app.jobs.base import JobResult, job_run
from app.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 180.0

UPSERT_SQL = text(
    """
    INSERT INTO app_transit_stop_dimension
        (stop_id, stop_name, mode, latitude, longitude, geom,
         parent_station_id, wheelchair_boarding,
         source, updated_at)
    VALUES (
        :stop_id, :stop_name, 'bus', :lat, :lon,
        ST_SetSRID(ST_Point(:lon, :lat), 4326),
        :parent_station_id, :wheelchair_boarding,
        'mta_bus_static_gtfs', NOW()
    )
    ON CONFLICT (stop_id) DO UPDATE SET
        stop_name            = EXCLUDED.stop_name,
        mode                 = EXCLUDED.mode,
        latitude             = EXCLUDED.latitude,
        longitude            = EXCLUDED.longitude,
        geom                 = EXCLUDED.geom,
        parent_station_id    = EXCLUDED.parent_station_id,
        wheelchair_boarding  = EXCLUDED.wheelchair_boarding,
        source               = EXCLUDED.source,
        updated_at           = NOW()
    """
)


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_zip(url: str) -> bytes:
    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        logger.info("mta_bus_gtfs_download url=%s", url)
        response = client.get(url, headers={"User-Agent": "nyc-agent-data-sync/0.1"})
        response.raise_for_status()
        return response.content


def _iter_stops(zip_bytes: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        if "stops.txt" not in zf.namelist():
            raise RuntimeError("GTFS zip missing stops.txt")
        with zf.open("stops.txt") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            return list(csv.DictReader(text))


def run(trigger_type: str = "manual") -> JobResult:
    feeds = settings.mta_bus_static_feed_list
    if not feeds:
        raise RuntimeError("MTA_BUS_STATIC_FEED_URLS is empty; cannot sync bus stops.")

    with job_run(
        "sync_mta_bus_static",
        trigger_type=trigger_type,
        target_scope={"feeds": feeds},
    ) as (ctx, result):
        seen = 0
        written = 0
        api_calls = 0
        skipped_no_id = 0
        skipped_no_geom = 0
        failed_feeds: list[str] = []
        per_feed: dict[str, dict[str, int]] = {}

        with db_session() as session:
            for url in feeds:
                feed_seen = 0
                feed_written = 0
                try:
                    zip_bytes = _fetch_zip(url)
                    api_calls += 1
                    stops = _iter_stops(zip_bytes)
                except Exception as exc:
                    failed_feeds.append(f"{url}: {exc}")
                    logger.warning("mta_bus_feed_failed url=%s err=%s", url, exc)
                    continue

                for row in stops:
                    seen += 1
                    feed_seen += 1
                    stop_id = (row.get("stop_id") or "").strip()
                    if not stop_id:
                        skipped_no_id += 1
                        continue
                    lat = _to_float(row.get("stop_lat"))
                    lon = _to_float(row.get("stop_lon"))
                    if lat is None or lon is None:
                        skipped_no_geom += 1
                        continue

                    rc = session.execute(
                        UPSERT_SQL,
                        {
                            "stop_id": stop_id,
                            "stop_name": (row.get("stop_name") or "").strip() or stop_id,
                            "lat": lat,
                            "lon": lon,
                            "parent_station_id": (row.get("parent_station") or "").strip() or None,
                            "wheelchair_boarding": (row.get("wheelchair_boarding") or "").strip() or None,
                        },
                    ).rowcount or 0
                    written += rc
                    feed_written += rc
                per_feed[url] = {"rows_seen": feed_seen, "rows_written": feed_written}
            session.commit()

        with db_session() as session:
            refresh_transit_station_count(session)

        ctx.rows_fetched = seen
        ctx.rows_written = written
        ctx.api_calls_used = api_calls
        ctx.metadata = {
            "feeds_requested": len(feeds),
            "feeds_failed_count": len(failed_feeds),
            "failed_feeds_sample": failed_feeds[:10],
            "per_feed": per_feed,
            "skipped_no_id": skipped_no_id,
            "skipped_no_geom": skipped_no_geom,
        }
        if written == 0:
            raise RuntimeError(f"MTA bus static wrote 0 rows; failures={failed_feeds[:3]}")
        if failed_feeds:
            result.status = "partial"
        logger.info(
            "sync_mta_bus_static done feeds=%d seen=%d written=%d failed=%d",
            len(feeds), seen, written, len(failed_feeds),
        )
    return result
