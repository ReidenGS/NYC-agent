"""sync_nta — pull NTA 2020 boundaries from NYC Open Data and upsert into app_area_dimension.

Source: 9nt8-h7nd (NTA 2020)
Field mapping (docs/NYC_Agent_Data_Sources_API_SQL.md §5.3):
  nta2020   -> area_id           (PK, e.g. "BK0101")
  ntaname   -> area_name
  boroname  -> borough
  ntatype   -> area_type
  the_geom  -> geom (MULTIPOLYGON, 4326) + geom_geojson (raw GeoJSON)
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text

from app.clients import socrata_client
from app.db.session import db_session
from app.jobs.base import JobResult, job_run

logger = logging.getLogger(__name__)

DATASET_ID = "9nt8-h7nd"

UPSERT_SQL = text(
    """
    INSERT INTO app_area_dimension
        (area_id, area_name, borough, area_type, geom_geojson, geom, updated_at)
    VALUES (
        :area_id, :area_name, :borough, :area_type,
        CAST(:geom_geojson AS JSONB),
        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_geojson_text), 4326)),
        NOW()
    )
    ON CONFLICT (area_id) DO UPDATE SET
        area_name    = EXCLUDED.area_name,
        borough      = EXCLUDED.borough,
        area_type    = EXCLUDED.area_type,
        geom_geojson = EXCLUDED.geom_geojson,
        geom         = EXCLUDED.geom,
        updated_at   = NOW()
    """
)


def run(trigger_type: str = "manual") -> JobResult:
    with job_run("sync_nta", trigger_type=trigger_type, target_scope={"dataset": DATASET_ID}) as (ctx, result):
        rows_seen = 0
        rows_written = 0
        skipped_no_geom = 0
        skipped_no_id = 0

        with db_session() as session:
            for row in socrata_client.fetch_all(
                DATASET_ID,
                select="nta2020, ntaname, boroname, ntatype, the_geom",
            ):
                rows_seen += 1
                area_id = (row.get("nta2020") or "").strip()
                geom = row.get("the_geom")
                if not area_id:
                    skipped_no_id += 1
                    continue
                if not geom:
                    skipped_no_geom += 1
                    continue

                geom_text = json.dumps(geom)
                session.execute(
                    UPSERT_SQL,
                    {
                        "area_id": area_id,
                        "area_name": (row.get("ntaname") or "").strip() or area_id,
                        "borough": (row.get("boroname") or "").strip() or "Unknown",
                        "area_type": (row.get("ntatype") or None),
                        "geom_geojson": geom_text,
                        "geom_geojson_text": geom_text,
                    },
                )
                rows_written += 1

        ctx.rows_fetched = rows_seen
        ctx.rows_written = rows_written
        ctx.metadata = {
            "dataset": DATASET_ID,
            "skipped_no_geom": skipped_no_geom,
            "skipped_no_id": skipped_no_id,
        }
        logger.info(
            "sync_nta done seen=%d written=%d skipped_geom=%d skipped_id=%d",
            rows_seen, rows_written, skipped_no_geom, skipped_no_id,
        )
    return result
