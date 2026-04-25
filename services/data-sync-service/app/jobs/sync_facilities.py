"""sync_facilities — pull NYC Facilities Database into convenience POIs.

Source: Socrata `67g2-p84d` (NYC Facilities Database).
Field mapping (docs/NYC_Agent_Data_Sources_API_SQL.md §5.4 + §6.2):
  uid           -> source_record_id, base of poi_id
  facgroup      -> category_code/category_name (5 verified categories)
  factype       -> kept in source_snapshot
  facsubgrp     -> kept in source_snapshot
  latitude/longitude -> geom POINT(4326), area_id resolved via ST_Contains

Categories (per §6.2 — only the 5 already verified from real samples):
  PARKS AND PLAZAS      -> park
  LIBRARIES             -> library
  SCHOOLS (K-12)        -> school_k12
  HEALTH CARE           -> health_care
  CULTURAL INSTITUTIONS -> cultural

Aggregation writes counts into app_area_convenience_category_daily with
source='67g2-p84d' so it coexists with overpass-sourced convenience rows
(PK includes source).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from app.clients import socrata_client
from app.db.session import db_session
from app.jobs._metrics_refresh import refresh_poi_totals
from app.jobs.base import JobResult, job_run

logger = logging.getLogger(__name__)

DATASET_ID = "67g2-p84d"

# facgroup value -> (category_code, category_name)
FACGROUP_MAP: dict[str, tuple[str, str]] = {
    "PARKS AND PLAZAS":      ("park",        "公园/广场"),
    "LIBRARIES":             ("library",     "图书馆"),
    "SCHOOLS (K-12)":        ("school_k12",  "K-12 学校"),
    "HEALTH CARE":           ("health_care", "医疗设施"),
    "CULTURAL INSTITUTIONS": ("cultural",    "文化机构"),
}


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
    INSERT INTO app_map_poi_snapshot
        (poi_id, area_id, poi_type, category_code, category_name,
         name, latitude, longitude, geom, intensity,
         source, source_key, source_value, source_record_id,
         source_snapshot, updated_at)
    SELECT :poi_id, nta.area_id, 'convenience', :category_code, :category_name,
           :name, :lat, :lon, pt.geom, 1.0,
           '67g2-p84d', 'facgroup', :facgroup, :uid,
           CAST(:source_snapshot AS JSONB), NOW()
    FROM nta, pt
    ON CONFLICT (poi_id) DO UPDATE SET
        area_id          = EXCLUDED.area_id,
        poi_type         = EXCLUDED.poi_type,
        category_code    = EXCLUDED.category_code,
        category_name    = EXCLUDED.category_name,
        name             = EXCLUDED.name,
        latitude         = EXCLUDED.latitude,
        longitude        = EXCLUDED.longitude,
        geom             = EXCLUDED.geom,
        source           = EXCLUDED.source,
        source_key       = EXCLUDED.source_key,
        source_value     = EXCLUDED.source_value,
        source_record_id = EXCLUDED.source_record_id,
        source_snapshot  = EXCLUDED.source_snapshot,
        updated_at       = NOW()
    """
)


AGGREGATE_SQL = text(
    """
    INSERT INTO app_area_convenience_category_daily
        (area_id, metric_date, category_code, category_name,
         facility_count, source, source_key, source_value,
         source_mapping, updated_at)
    SELECT area_id, CURRENT_DATE, category_code, category_name,
           COUNT(*),
           '67g2-p84d', source_key, source_value,
           jsonb_build_object(source_key, source_value), NOW()
    FROM app_map_poi_snapshot
    WHERE source = '67g2-p84d'
      AND poi_type = 'convenience'
    GROUP BY area_id, category_code, category_name, source_key, source_value
    ON CONFLICT (area_id, metric_date, category_code, source, source_key, source_value)
    DO UPDATE SET
        category_name  = EXCLUDED.category_name,
        facility_count = EXCLUDED.facility_count,
        source_mapping = EXCLUDED.source_mapping,
        updated_at     = NOW()
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
    facgroups = list(FACGROUP_MAP.keys())
    where = "facgroup in(" + ",".join(f"'{g}'" for g in facgroups) + ")"
    select = "uid, facgroup, facsubgrp, factype, facname, nta2020, boro, latitude, longitude"

    with job_run(
        "sync_facilities",
        trigger_type=trigger_type,
        target_scope={"dataset": DATASET_ID, "facgroups": facgroups},
    ) as (ctx, result):
        seen = 0
        written = 0
        skipped_no_id = 0
        skipped_no_geom = 0
        skipped_no_match = 0
        skipped_outside_nta = 0

        with db_session() as session:
            for row in socrata_client.fetch_all(DATASET_ID, select=select, where=where):
                seen += 1
                uid = (row.get("uid") or "").strip()
                if not uid:
                    skipped_no_id += 1
                    continue
                lat = _to_float(row.get("latitude"))
                lon = _to_float(row.get("longitude"))
                if lat is None or lon is None:
                    skipped_no_geom += 1
                    continue

                facgroup = (row.get("facgroup") or "").strip()
                cat = FACGROUP_MAP.get(facgroup)
                if cat is None:
                    # Should not happen given the SoQL filter, but be defensive.
                    skipped_no_match += 1
                    continue
                category_code, category_name = cat

                rc = session.execute(
                    UPSERT_SQL,
                    {
                        "poi_id": f"facilities_{uid}",
                        "uid": uid,
                        "category_code": category_code,
                        "category_name": category_name,
                        "facgroup": facgroup,
                        "name": (row.get("facname") or "").strip() or None,
                        "lat": lat,
                        "lon": lon,
                        "source_snapshot": json.dumps(row, default=str),
                    },
                ).rowcount or 0
                if rc:
                    written += 1
                else:
                    skipped_outside_nta += 1
            session.commit()

        with db_session() as session:
            session.execute(AGGREGATE_SQL)
            refresh_poi_totals(session)

        ctx.rows_fetched = seen
        ctx.rows_written = written
        ctx.metadata = {
            "dataset": DATASET_ID,
            "facgroups": facgroups,
            "skipped_no_id": skipped_no_id,
            "skipped_no_geom": skipped_no_geom,
            "skipped_no_match": skipped_no_match,
            "skipped_outside_nta": skipped_outside_nta,
        }
        logger.info(
            "sync_facilities done seen=%d written=%d outside=%d no_geom=%d",
            seen, written, skipped_outside_nta, skipped_no_geom,
        )
    return result
