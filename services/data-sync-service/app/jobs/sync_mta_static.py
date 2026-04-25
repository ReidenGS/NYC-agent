"""sync_mta_static — pull MTA subway station dictionary into app_transit_stop_dimension.

Source: NYS Open Data dataset 39hk-dx4f (MTA Subway Stations).
Field mapping (docs/NYC_Agent_Data_Sources_API_SQL.md §5.5 + §6 table 11):
  gtfs_stop_id      -> stop_id (PK)
  stop_name         -> stop_name
  gtfs_latitude     -> latitude
  gtfs_longitude    -> longitude
  daytime_routes    -> kept in source_snapshot (no dedicated column)
  borough/structure -> kept in source_snapshot

Aggregation: refreshes transit_station_count across subway + bus stops.

Per the metric_date convention (docs/NYC_Agent_Data_Sources_API_SQL.md
§6 table 2), the row is keyed on (area_id, CURRENT_DATE) and
source_snapshot.transit_station_count.window_end records the actual
snapshot date.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from app.clients import socrata_client
from app.db.session import db_session
from app.jobs._transit_metrics_refresh import refresh_transit_station_count
from app.jobs.base import JobResult, job_run

logger = logging.getLogger(__name__)

DATASET_ID = "39hk-dx4f"
DOMAIN = "data.ny.gov"

UPSERT_SQL = text(
    """
    INSERT INTO app_transit_stop_dimension
        (stop_id, stop_name, mode, latitude, longitude, geom,
         parent_station_id, wheelchair_boarding,
         source, updated_at)
    VALUES (
        :stop_id, :stop_name, 'subway', :lat, :lon,
        ST_SetSRID(ST_Point(:lon, :lat), 4326),
        NULL, NULL,
        'mta_subway_stations', NOW()
    )
    ON CONFLICT (stop_id) DO UPDATE SET
        stop_name  = EXCLUDED.stop_name,
        latitude   = EXCLUDED.latitude,
        longitude  = EXCLUDED.longitude,
        geom       = EXCLUDED.geom,
        source     = EXCLUDED.source,
        updated_at = NOW()
    """
)


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def run(trigger_type: str = "manual") -> JobResult:
    with job_run(
        "sync_mta_static",
        trigger_type=trigger_type,
        target_scope={"dataset": DATASET_ID, "domain": DOMAIN},
    ) as (ctx, result):
        seen = 0
        written = 0
        skipped_no_id = 0
        skipped_no_geom = 0

        with db_session() as session:
            for row in socrata_client.fetch_all(DATASET_ID, domain=DOMAIN):
                seen += 1
                stop_id = (row.get("gtfs_stop_id") or row.get("stop_id") or "").strip()
                if not stop_id:
                    skipped_no_id += 1
                    continue
                lat = _to_float(row.get("gtfs_latitude") or row.get("stop_lat"))
                lon = _to_float(row.get("gtfs_longitude") or row.get("stop_lon"))
                if lat is None or lon is None:
                    skipped_no_geom += 1
                    continue

                session.execute(
                    UPSERT_SQL,
                    {
                        "stop_id": stop_id,
                        "stop_name": (row.get("stop_name") or "").strip() or stop_id,
                        "lat": lat,
                        "lon": lon,
                    },
                )
                written += 1
            session.commit()

        with db_session() as session:
            refresh_transit_station_count(session)

        ctx.rows_fetched = seen
        ctx.rows_written = written
        ctx.metadata = {
            "dataset": DATASET_ID,
            "domain": DOMAIN,
            "skipped_no_id": skipped_no_id,
            "skipped_no_geom": skipped_no_geom,
        }
        logger.info(
            "sync_mta_static done seen=%d written=%d skipped_id=%d skipped_geom=%d",
            seen, written, skipped_no_id, skipped_no_geom,
        )
    return result
