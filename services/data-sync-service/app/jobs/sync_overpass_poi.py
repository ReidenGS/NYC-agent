"""sync_overpass_poi — pull entertainment + convenience POIs from OpenStreetMap.

Source: Overpass API (OSM).
Category mapping: docs/NYC_Agent_Data_Sources_API_SQL.md §6.2.

Strategy (one Overpass call per run, not per NTA):
  1. Resolve seed area NTAs from app_area_dimension by ILIKE name match.
  2. Compute the union bbox of those NTAs and issue ONE Overpass query
     scoped to that bbox. This minimises load on the public service
     (well within OVERPASS_MAX_REQUESTS_PER_RUN).
  3. For each returned element, classify by tags. Skip elements whose
     tags don't match the §6.2 mapping.
  4. Resolve area_id via ST_Contains (PostGIS) so a POI inside the bbox
     but outside every seed NTA is dropped.
  5. Upsert into app_map_poi_snapshot.
  6. Aggregate: per (area_id, metric_date=today, category) recompute
     poi_count from the snapshot for poi_type in {entertainment, convenience}.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import text

from app.clients import overpass_client
from app.db.session import db_session
from app.jobs.base import JobResult, job_run
from app.settings import settings

logger = logging.getLogger(__name__)


# (osm_key, osm_value) -> (poi_type, category_code, category_name)
CATEGORY_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("amenity", "bar"):           ("entertainment", "bar",               "酒吧"),
    ("amenity", "pub"):           ("entertainment", "pub",               "酒馆"),
    ("amenity", "nightclub"):     ("entertainment", "nightclub",         "夜店"),
    ("amenity", "cinema"):        ("entertainment", "cinema",            "电影院"),
    ("amenity", "theatre"):       ("entertainment", "theatre",           "剧院"),
    ("amenity", "restaurant"):    ("entertainment", "restaurant",        "餐厅"),
    ("amenity", "pharmacy"):      ("convenience",   "pharmacy",          "药店"),
    ("shop",    "supermarket"):   ("convenience",   "supermarket",       "超市"),
    ("shop",    "convenience"):   ("convenience",   "convenience_store", "便利店"),
    ("leisure", "fitness_centre"):("convenience",   "gym",               "健身房"),
}


SEED_BBOX_SQL = text(
    """
    SELECT
        MIN(ST_YMin(geom)) AS s,
        MIN(ST_XMin(geom)) AS w,
        MAX(ST_YMax(geom)) AS n,
        MAX(ST_XMax(geom)) AS e,
        COUNT(*) AS nta_count
    FROM app_area_dimension
    WHERE """
)
# Predicate is appended at runtime so we can OR together ILIKE patterns.


UPSERT_POI_SQL = text(
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
    SELECT :poi_id, nta.area_id, :poi_type, :category_code, :category_name,
           :name, :lat, :lon, pt.geom, 1.0,
           'overpass', :source_key, :source_value, :source_record_id,
           CAST(:source_snapshot AS JSONB), NOW()
    FROM nta, pt
    ON CONFLICT (poi_id) DO UPDATE SET
        area_id         = EXCLUDED.area_id,
        poi_type        = EXCLUDED.poi_type,
        category_code   = EXCLUDED.category_code,
        category_name   = EXCLUDED.category_name,
        name            = EXCLUDED.name,
        latitude        = EXCLUDED.latitude,
        longitude       = EXCLUDED.longitude,
        geom            = EXCLUDED.geom,
        source_key      = EXCLUDED.source_key,
        source_value    = EXCLUDED.source_value,
        source_record_id = EXCLUDED.source_record_id,
        source_snapshot = EXCLUDED.source_snapshot,
        updated_at      = NOW()
    """
)


# Aggregate snapshot -> per-category daily count for one of two daily tables.
def _build_aggregate_sql(target_table: str, poi_type: str) -> str:
    return f"""
    INSERT INTO {target_table}
        (area_id, metric_date, category_code, category_name,
         {'poi_count' if poi_type == 'entertainment' else 'facility_count'},
         source, source_key, source_value, source_mapping, updated_at)
    SELECT area_id, CURRENT_DATE, category_code, category_name,
           COUNT(*),
           'overpass', source_key, source_value,
           jsonb_build_object(source_key, source_value), NOW()
    FROM app_map_poi_snapshot
    WHERE source = 'overpass'
      AND poi_type = '{poi_type}'
    GROUP BY area_id, category_code, category_name, source_key, source_value
    ON CONFLICT (area_id, metric_date, category_code, source, source_key, source_value)
    DO UPDATE SET
        category_name  = EXCLUDED.category_name,
        {'poi_count' if poi_type == 'entertainment' else 'facility_count'}
            = EXCLUDED.{'poi_count' if poi_type == 'entertainment' else 'facility_count'},
        source_mapping = EXCLUDED.source_mapping,
        updated_at     = NOW()
    """


def _build_overpass_query(s: float, w: float, n: float, e: float) -> str:
    # Build alternation lists by OSM key.
    by_key: dict[str, list[str]] = {}
    for (k, v) in CATEGORY_MAP.keys():
        by_key.setdefault(k, []).append(v)

    bbox = f"{s},{w},{n},{e}"
    union: list[str] = []
    for key, values in by_key.items():
        regex = "^(" + "|".join(values) + ")$"
        # node + way (ways get center coordinate)
        union.append(f'node["{key}"~"{regex}"]({bbox});')
        union.append(f'way["{key}"~"{regex}"]({bbox});')

    return (
        "[out:json][timeout:90];\n"
        "(\n  " + "\n  ".join(union) + "\n);\n"
        "out center tags;"
    )


def _classify(tags: dict[str, str]) -> tuple[str, str, str, str, str] | None:
    """Return (poi_type, category_code, category_name, source_key, source_value) or None."""
    for (k, v), (poi_type, code, name) in CATEGORY_MAP.items():
        if tags.get(k) == v:
            return poi_type, code, name, f"tags.{k}", v
    return None


def _coords(elem: dict[str, Any]) -> tuple[float | None, float | None]:
    if elem.get("type") == "node":
        return elem.get("lat"), elem.get("lon")
    center = elem.get("center") or {}
    return center.get("lat"), center.get("lon")


def run(trigger_type: str = "manual") -> JobResult:
    seed_areas = settings.bootstrap_area_list
    if not seed_areas:
        raise RuntimeError("SYNC_BOOTSTRAP_AREAS is empty; nothing to sync.")

    with job_run(
        "sync_overpass_poi",
        trigger_type=trigger_type,
        target_scope={"seed_areas": seed_areas},
    ) as (ctx, result):
        # 1. Compute union bbox of NTAs matching seed areas.
        ilike_clauses = " OR ".join(
            [f"area_name ILIKE :p{i}" for i in range(len(seed_areas))]
        )
        bbox_sql = text(SEED_BBOX_SQL.text + f"({ilike_clauses})")
        params = {f"p{i}": f"%{name}%" for i, name in enumerate(seed_areas)}

        with db_session() as session:
            row = session.execute(bbox_sql, params).mappings().one()
        s, w, n, e, nta_count = row["s"], row["w"], row["n"], row["e"], row["nta_count"]
        if not nta_count or s is None:
            raise RuntimeError(f"no NTAs matched seed areas {seed_areas}; run sync_nta first")
        logger.info(
            "overpass_bbox nta_count=%d s=%s w=%s n=%s e=%s",
            nta_count, s, w, n, e,
        )

        # 2. Issue ONE Overpass query for the whole union bbox.
        budget = overpass_client.OverpassBudget()
        query = _build_overpass_query(float(s), float(w), float(n), float(e))
        payload = overpass_client.post_query(query, budget=budget)
        elements = payload.get("elements") or []

        # 3. Classify + upsert (spatial assignment via ST_Contains).
        seen = len(elements)
        classified = 0
        written = 0
        skipped_outside = 0
        skipped_no_geom = 0
        skipped_no_tag_match = 0

        with db_session() as session:
            for elem in elements:
                tags = elem.get("tags") or {}
                cls = _classify(tags)
                if cls is None:
                    skipped_no_tag_match += 1
                    continue
                lat, lon = _coords(elem)
                if lat is None or lon is None:
                    skipped_no_geom += 1
                    continue
                classified += 1

                poi_type, code, cname, src_key, src_val = cls
                osm_id = elem.get("id")
                osm_type = elem.get("type")
                poi_id = f"overpass_{osm_type}_{osm_id}"
                name = (tags.get("name") or "").strip() or None

                rc = session.execute(
                    UPSERT_POI_SQL,
                    {
                        "poi_id": poi_id,
                        "poi_type": poi_type,
                        "category_code": code,
                        "category_name": cname,
                        "name": name,
                        "lat": float(lat),
                        "lon": float(lon),
                        "source_key": src_key,
                        "source_value": src_val,
                        "source_record_id": str(osm_id) if osm_id else None,
                        "source_snapshot": json.dumps(
                            {"osm_type": osm_type, "osm_id": osm_id, "tags": tags},
                            default=str,
                        ),
                    },
                ).rowcount or 0
                if rc:
                    written += 1
                else:
                    skipped_outside += 1
            session.commit()

        # 4. Aggregate to daily category tables.
        with db_session() as session:
            session.execute(
                text(_build_aggregate_sql("app_area_entertainment_category_daily", "entertainment"))
            )
            session.execute(
                text(_build_aggregate_sql("app_area_convenience_category_daily", "convenience"))
            )

        ctx.rows_fetched = seen
        ctx.rows_written = written
        ctx.api_calls_used = budget.used
        ctx.metadata = {
            "nta_count": int(nta_count),
            "bbox": {"s": float(s), "w": float(w), "n": float(n), "e": float(e)},
            "elements_classified": classified,
            "skipped_no_tag_match": skipped_no_tag_match,
            "skipped_no_geom": skipped_no_geom,
            "skipped_outside_nta": skipped_outside,
            "metric_date": date.today().isoformat(),
        }
        logger.info(
            "sync_overpass_poi done seen=%d classified=%d written=%d outside=%d",
            seen, classified, written, skipped_outside,
        )
    return result
