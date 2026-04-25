"""sync_311 — pull recent NYC 311 noise complaints and aggregate to NTAs.

Source: Socrata `erm2-nwe9` (NYC 311 Service Requests).
Field mapping (docs/NYC_Agent_Data_Sources_API_SQL.md §5.2 + §6 table 2):
  unique_key      -> source_record_id (per-row)
  created_date    -> 30-day window anchor for complaint_noise_30d
  complaint_type  -> filter (must match '%Noise%')
  latitude/lon    -> spatial assignment via ST_Contains

311 has no dedicated snapshot table per design §8 — only aggregation
to app_area_metrics_daily.complaint_noise_30d. We stream rows into a
TEMP table and do spatial assignment + counting entirely in PostGIS.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.clients import socrata_client
from app.db.session import db_session
from app.jobs.base import JobResult, job_run

logger = logging.getLogger(__name__)

DATASET_ID = "erm2-nwe9"

CREATE_TEMP_SQL = text(
    """
    CREATE TEMP TABLE _stg_311_noise (
        unique_key   TEXT,
        created_date TIMESTAMPTZ,
        lat          DOUBLE PRECISION,
        lon          DOUBLE PRECISION,
        complaint_type TEXT,
        descriptor   TEXT
    ) ON COMMIT DROP
    """
)

INSERT_TEMP_SQL = text(
    """
    INSERT INTO _stg_311_noise (unique_key, created_date, lat, lon, complaint_type, descriptor)
    VALUES (:unique_key, :created_date, :lat, :lon, :complaint_type, :descriptor)
    """
)

AGGREGATE_SQL = text(
    """
    WITH ref AS (
        SELECT MAX(created_date::date) AS max_date,
               COUNT(*) AS total_rows
        FROM _stg_311_noise
    ),
    counts AS (
        SELECT a.area_id, COUNT(*) AS n
        FROM _stg_311_noise t
        JOIN app_area_dimension a
          ON ST_Contains(a.geom, ST_SetSRID(ST_Point(t.lon, t.lat), 4326))
        CROSS JOIN ref
        WHERE t.created_date::date >= ref.max_date - INTERVAL '30 days'
          AND t.created_date::date <= ref.max_date
        GROUP BY a.area_id
    ),
    upserted AS (
        INSERT INTO app_area_metrics_daily
            (area_id, metric_date, complaint_noise_30d, source_snapshot, updated_at)
        SELECT counts.area_id, ref.max_date, counts.n,
               jsonb_build_object('complaint_noise_30d',
                   jsonb_build_object('source', '311_service_requests',
                                      'dataset', 'erm2-nwe9',
                                      'window_end', ref.max_date,
                                      'window_days', 30)),
               NOW()
        FROM counts, ref
        ON CONFLICT (area_id, metric_date) DO UPDATE SET
            complaint_noise_30d = EXCLUDED.complaint_noise_30d,
            source_snapshot     = app_area_metrics_daily.source_snapshot
                                   || EXCLUDED.source_snapshot,
            updated_at          = NOW()
        RETURNING 1
    )
    SELECT (SELECT max_date FROM ref) AS max_date,
           (SELECT total_rows FROM ref) AS staged_rows,
           (SELECT COUNT(*) FROM upserted) AS area_rows_written
    """
)


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def run(trigger_type: str = "manual") -> JobResult:
    select = "unique_key, created_date, complaint_type, descriptor, latitude, longitude"
    where = "complaint_type like '%Noise%' AND latitude IS NOT NULL AND longitude IS NOT NULL"
    order = "created_date DESC NULLS LAST"

    with job_run(
        "sync_311",
        trigger_type=trigger_type,
        target_scope={"dataset": DATASET_ID, "filter": "complaint_type ~ 'Noise'"},
    ) as (ctx, result):
        seen = 0
        staged = 0
        skipped_no_id = 0
        skipped_no_geom = 0
        BATCH = 1000

        with db_session() as session:
            session.execute(CREATE_TEMP_SQL)

            buf: list[dict[str, Any]] = []
            for row in socrata_client.fetch_all(
                DATASET_ID, select=select, where=where, order=order
            ):
                seen += 1
                uid = (row.get("unique_key") or "").strip()
                if not uid:
                    skipped_no_id += 1
                    continue
                lat = _to_float(row.get("latitude"))
                lon = _to_float(row.get("longitude"))
                if lat is None or lon is None:
                    skipped_no_geom += 1
                    continue
                buf.append({
                    "unique_key": uid,
                    "created_date": _parse_dt(row.get("created_date")),
                    "lat": lat,
                    "lon": lon,
                    "complaint_type": (row.get("complaint_type") or "").strip() or None,
                    "descriptor": (row.get("descriptor") or "").strip() or None,
                })
                if len(buf) >= BATCH:
                    session.execute(INSERT_TEMP_SQL, buf)
                    staged += len(buf)
                    buf.clear()
            if buf:
                session.execute(INSERT_TEMP_SQL, buf)
                staged += len(buf)
                buf.clear()

            agg = session.execute(AGGREGATE_SQL).mappings().one()

        ctx.rows_fetched = seen
        ctx.rows_written = int(agg["area_rows_written"] or 0)
        ctx.metadata = {
            "dataset": DATASET_ID,
            "filter": "complaint_type ~ 'Noise'",
            "max_date": str(agg["max_date"]) if agg["max_date"] else None,
            "staged_rows": int(agg["staged_rows"] or 0),
            "skipped_no_id": skipped_no_id,
            "skipped_no_geom": skipped_no_geom,
        }
        logger.info(
            "sync_311 done seen=%d staged=%d areas_written=%d max_date=%s",
            seen, staged, ctx.rows_written, agg["max_date"],
        )
    return result
