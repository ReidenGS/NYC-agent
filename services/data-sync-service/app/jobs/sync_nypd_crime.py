"""sync_nypd_crime — pull recent NYPD crime complaints and aggregate to NTAs.

Source: Socrata `qgea-i56i` (NYPD Complaint Data).
Field mapping (NYC_Agent_Data_Sources_API_SQL.md §5.1 + §6 table 3):
  cmplnt_num    -> incident_id (PK), source_record_id
  cmplnt_fr_dt  -> occurred_date
  cmplnt_fr_tm  -> occurred_hour (combined with date -> occurred_at)
  ofns_desc     -> offense_category, offense_description (raw)
  pd_desc       -> offense_description fallback
  law_cat_cd    -> law_category
  boro_nm       -> borough
  latitude/longitude -> geom POINT(4326), area_id resolved via ST_Contains

Spatial assignment is done in-DB during INSERT via a CTE that picks the
NTA polygon containing the point. Rows that fall outside every NTA are
skipped (we cannot violate the FK on area_id).

Aggregation step writes `crime_count_30d` into app_area_metrics_daily,
keyed by the latest occurred_date in the snapshot (so the metric is
meaningful even if the public dataset lags by months).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from app.clients import socrata_client
from app.db.session import db_session
from app.jobs.base import JobResult, job_run

logger = logging.getLogger(__name__)

DATASET_ID = "qgea-i56i"

UPSERT_SQL = text(
    """
    WITH pt AS (
        SELECT ST_SetSRID(ST_Point(:lon, :lat), 4326) AS geom
    ),
    nta AS (
        SELECT a.area_id
        FROM app_area_dimension a, pt
        WHERE a.geom IS NOT NULL AND ST_Contains(a.geom, pt.geom)
        LIMIT 1
    )
    INSERT INTO app_crime_incident_snapshot
        (incident_id, area_id, occurred_at, occurred_date, occurred_hour,
         borough, offense_category, offense_description, law_category,
         latitude, longitude, geom,
         source, source_record_id, raw_source, updated_at)
    SELECT :incident_id, nta.area_id, :occurred_at, :occurred_date, :occurred_hour,
           :borough, :offense_category, :offense_description, :law_category,
           :lat, :lon, pt.geom,
           'nypd_complaint_data', :incident_id,
           CAST(:raw_source AS JSONB), NOW()
    FROM nta, pt
    ON CONFLICT (incident_id) DO UPDATE SET
        area_id             = EXCLUDED.area_id,
        occurred_at         = EXCLUDED.occurred_at,
        occurred_date       = EXCLUDED.occurred_date,
        occurred_hour       = EXCLUDED.occurred_hour,
        borough             = EXCLUDED.borough,
        offense_category    = EXCLUDED.offense_category,
        offense_description = EXCLUDED.offense_description,
        law_category        = EXCLUDED.law_category,
        latitude            = EXCLUDED.latitude,
        longitude           = EXCLUDED.longitude,
        geom                = EXCLUDED.geom,
        raw_source          = EXCLUDED.raw_source,
        updated_at          = NOW()
    """
)

AGGREGATE_SQL = text(
    """
    WITH ref AS (
        SELECT MAX(occurred_date) AS max_date
        FROM app_crime_incident_snapshot
    ),
    counts AS (
        SELECT c.area_id,
               COUNT(*) AS crime_count
        FROM app_crime_incident_snapshot c, ref
        WHERE c.occurred_date IS NOT NULL
          AND ref.max_date IS NOT NULL
          AND c.occurred_date >= ref.max_date - INTERVAL '30 days'
          AND c.occurred_date <= ref.max_date
        GROUP BY c.area_id
    ),
    upserted AS (
        INSERT INTO app_area_metrics_daily
            (area_id, metric_date, crime_count_30d, source_snapshot, updated_at)
        SELECT counts.area_id, ref.max_date, counts.crime_count,
               jsonb_build_object('crime_count_30d',
                   jsonb_build_object('source', 'nypd_complaint_data',
                                      'window_end', ref.max_date,
                                      'window_days', 30)),
               NOW()
        FROM counts, ref
        ON CONFLICT (area_id, metric_date) DO UPDATE SET
            crime_count_30d = EXCLUDED.crime_count_30d,
            source_snapshot = app_area_metrics_daily.source_snapshot
                              || EXCLUDED.source_snapshot,
            updated_at      = NOW()
        RETURNING 1
    )
    SELECT COUNT(*) FROM upserted
    """
)


def _parse_occurred(row: dict[str, Any]) -> tuple[datetime | None, date | None, int | None]:
    raw_dt = row.get("cmplnt_fr_dt")  # ISO like 2023-05-12T00:00:00.000
    raw_tm = row.get("cmplnt_fr_tm")  # "HH:MM:SS"
    occurred_date: date | None = None
    occurred_hour: int | None = None
    occurred_at: datetime | None = None
    if raw_dt:
        try:
            occurred_date = datetime.fromisoformat(raw_dt.replace("Z", "+00:00")).date()
        except ValueError:
            return None, None, None
    if raw_tm and isinstance(raw_tm, str):
        parts = raw_tm.split(":")
        if parts and parts[0].isdigit():
            occurred_hour = int(parts[0]) if 0 <= int(parts[0]) <= 23 else None
    if occurred_date is not None:
        h = occurred_hour or 0
        m = 0
        s = 0
        if raw_tm:
            try:
                hh, mm, ss = (raw_tm.split(":") + ["0", "0"])[:3]
                h = int(hh) if hh.isdigit() else 0
                m = int(mm) if mm.isdigit() else 0
                s = int(ss) if ss.isdigit() else 0
                if not (0 <= h <= 23):
                    h = 0
            except ValueError:
                pass
        occurred_at = datetime(
            occurred_date.year, occurred_date.month, occurred_date.day, h, m, s,
            tzinfo=timezone.utc,
        )
    return occurred_at, occurred_date, occurred_hour


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def run(trigger_type: str = "manual") -> JobResult:
    select = (
        "cmplnt_num, cmplnt_fr_dt, cmplnt_fr_tm, ofns_desc, pd_desc,"
        " law_cat_cd, boro_nm, latitude, longitude"
    )
    # No date filter: dataset cadence varies, so we just take the most recent N
    # records ordered descending. Cap is settings.socrata_max_rows_per_job.
    order = "cmplnt_fr_dt DESC NULLS LAST"

    with job_run(
        "sync_nypd_crime",
        trigger_type=trigger_type,
        target_scope={"dataset": DATASET_ID, "order": order},
    ) as (ctx, result):
        seen = 0
        written = 0
        skipped_no_id = 0
        skipped_no_geom = 0
        skipped_outside_nta = 0
        BATCH = 500

        with db_session() as session:
            batch_buf: list[dict[str, Any]] = []
            for row in socrata_client.fetch_all(DATASET_ID, select=select, order=order):
                seen += 1
                incident_id = (row.get("cmplnt_num") or "").strip()
                if not incident_id:
                    skipped_no_id += 1
                    continue
                lat = _to_float(row.get("latitude"))
                lon = _to_float(row.get("longitude"))
                if lat is None or lon is None:
                    skipped_no_geom += 1
                    continue

                occurred_at, occurred_date, occurred_hour = _parse_occurred(row)
                offense = (row.get("ofns_desc") or "").strip() or None
                pd_desc = (row.get("pd_desc") or "").strip() or None

                params = {
                    "incident_id": incident_id,
                    "occurred_at": occurred_at,
                    "occurred_date": occurred_date,
                    "occurred_hour": occurred_hour,
                    "borough": (row.get("boro_nm") or "").strip() or None,
                    "offense_category": offense,
                    "offense_description": pd_desc or offense,
                    "law_category": (row.get("law_cat_cd") or "").strip() or None,
                    "lat": lat,
                    "lon": lon,
                    "raw_source": json.dumps(row, default=str),
                }
                batch_buf.append(params)

                if len(batch_buf) >= BATCH:
                    inserted = _flush(session, batch_buf)
                    written += inserted
                    skipped_outside_nta += len(batch_buf) - inserted
                    batch_buf.clear()
                    session.commit()

            if batch_buf:
                inserted = _flush(session, batch_buf)
                written += inserted
                skipped_outside_nta += len(batch_buf) - inserted
                batch_buf.clear()
                session.commit()

        # Aggregation runs in its own transaction.
        with db_session() as session:
            agg_rows = session.execute(AGGREGATE_SQL).scalar() or 0

        ctx.rows_fetched = seen
        ctx.rows_written = written
        ctx.metadata = {
            "dataset": DATASET_ID,
            "skipped_no_id": skipped_no_id,
            "skipped_no_geom": skipped_no_geom,
            "skipped_outside_nta": skipped_outside_nta,
            "metrics_rows_upserted": int(agg_rows),
        }
        logger.info(
            "sync_nypd_crime done seen=%d written=%d outside_nta=%d agg_rows=%d",
            seen, written, skipped_outside_nta, agg_rows,
        )
    return result


def _flush(session, batch: list[dict[str, Any]]) -> int:
    """Execute the upsert per row and return the count of rows actually inserted/updated.

    The CTE skips rows whose point falls outside every NTA, so the affected
    rowcount tells us how many were actually accepted.
    """
    inserted = 0
    for params in batch:
        rc = session.execute(UPSERT_SQL, params).rowcount or 0
        inserted += rc
    return inserted
