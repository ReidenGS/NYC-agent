"""build_map_layers — pre-generate front-end GeoJSON layers for seed NTAs.

Per docs/NYC_Agent_Data_Sync_Design.md §11 + table 7 (app_map_layer_cache):
  - seed areas get cached layers after bootstrap
  - non-seed areas are generated on demand later (not in this job)
  - failures of one layer must not block other layers

For each seed NTA, this job builds four layers:
  1. choropleth · safety        — NTA polygon shaded by crime_count_30d
  2. heatmap    · crime         — recent crime points (capped per NTA)
  3. marker     · entertainment — POIs with poi_type='entertainment'
  4. marker     · convenience   — POIs with poi_type='convenience'

Each row in app_map_layer_cache is keyed on
(area_id, layer_type, metric_name, metric_date) plus a stable layer_id
derived from those four fields. Layers expire 7 days after generation
(static-ish data, refreshed by re-running this job).

Cap per heatmap: HEATMAP_POINTS_PER_AREA points (most recent by
occurred_at). This bounds GeoJSON size; UI clusters anything bigger.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.session import db_session
from app.jobs.base import JobResult, job_run
from app.settings import settings

logger = logging.getLogger(__name__)


HEATMAP_POINTS_PER_AREA = 1000
MARKER_POINTS_PER_AREA = 1000
LAYER_TTL_DAYS = 7


# Style hints — frontend MapLibre/Leaflet can read these without round-tripping.
STYLE_CHOROPLETH_SAFETY: dict[str, Any] = {
    "kind": "fill",
    "property": "crime_intensity",
    "stops": [
        [0,   "#1a9850"],
        [25,  "#a6d96a"],
        [50,  "#fee08b"],
        [75,  "#fdae61"],
        [100, "#d73027"],
    ],
    "fill_opacity": 0.5,
    "outline_color": "#333333",
}
STYLE_HEATMAP_CRIME: dict[str, Any] = {
    "kind": "heatmap",
    "weight_property": "intensity",
    "radius_px": 18,
    "max_zoom": 15,
}
STYLE_MARKER_ENTERTAINMENT: dict[str, Any] = {
    "kind": "circle",
    "color": "#9c27b0",
    "radius_px": 5,
    "stroke_color": "#ffffff",
    "stroke_width_px": 1,
}
STYLE_MARKER_CONVENIENCE: dict[str, Any] = {
    "kind": "circle",
    "color": "#4caf50",
    "radius_px": 5,
    "stroke_color": "#ffffff",
    "stroke_width_px": 1,
}


# ---------- SQL builders (each returns one GeoJSON FeatureCollection) ----------

CHOROPLETH_SAFETY_SQL = text(
    """
    SELECT jsonb_build_object(
        'type', 'FeatureCollection',
        'features', jsonb_build_array(
            jsonb_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(a.geom)::jsonb,
                'properties', jsonb_build_object(
                    'area_id', a.area_id,
                    'area_name', a.area_name,
                    'borough', a.borough,
                    'crime_count_30d', COALESCE(m.crime_count_30d, 0),
                    -- Map raw count -> 0..100 intensity. NYC NTAs span 0..~1000;
                    -- log scale would be nicer but for MVP linear w/ cap is fine.
                    'crime_intensity', LEAST(100,
                        ROUND(COALESCE(m.crime_count_30d, 0)::numeric / 10.0, 2)),
                    'window_end',
                        m.source_snapshot->'crime_count_30d'->>'window_end'
                )
            )
        )
    ) AS geojson
    FROM app_area_dimension a
    LEFT JOIN app_area_metrics_daily m
      ON m.area_id = a.area_id AND m.metric_date = CURRENT_DATE
    WHERE a.area_id = :area_id
    """
)

HEATMAP_CRIME_SQL = text(
    """
    WITH pts AS (
        SELECT geom, occurred_at, offense_category, law_category, incident_id
        FROM app_crime_incident_snapshot
        WHERE area_id = :area_id AND geom IS NOT NULL
        ORDER BY occurred_at DESC NULLS LAST
        LIMIT :limit
    )
    SELECT jsonb_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(jsonb_agg(
            jsonb_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(geom)::jsonb,
                'properties', jsonb_build_object(
                    'incident_id', incident_id,
                    'occurred_at', occurred_at,
                    'offense_category', offense_category,
                    'law_category', law_category,
                    'intensity',
                        CASE law_category
                            WHEN 'FELONY'      THEN 1.0
                            WHEN 'MISDEMEANOR' THEN 0.6
                            WHEN 'VIOLATION'   THEN 0.3
                            ELSE 0.5
                        END
                )
            )
        ), '[]'::jsonb)
    ) AS geojson
    FROM pts
    """
)

# Markers parameterise on poi_type so we can reuse for entertainment + convenience.
MARKER_BY_TYPE_SQL = text(
    """
    WITH pts AS (
        SELECT geom, poi_id, name, category_code, category_name, source
        FROM app_map_poi_snapshot
        WHERE area_id = :area_id
          AND poi_type = :poi_type
          AND geom IS NOT NULL
        LIMIT :limit
    )
    SELECT jsonb_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE(jsonb_agg(
            jsonb_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(geom)::jsonb,
                'properties', jsonb_build_object(
                    'poi_id', poi_id,
                    'name', name,
                    'category_code', category_code,
                    'category_name', category_name,
                    'source', source
                )
            )
        ), '[]'::jsonb)
    ) AS geojson
    FROM pts
    """
)


UPSERT_LAYER_SQL = text(
    """
    INSERT INTO app_map_layer_cache
        (layer_id, area_id, layer_type, metric_name, metric_date,
         geojson, style_hint, source_snapshot, expires_at, updated_at)
    VALUES
        (:layer_id, :area_id, :layer_type, :metric_name, :metric_date,
         CAST(:geojson AS JSONB), CAST(:style_hint AS JSONB),
         CAST(:source_snapshot AS JSONB), :expires_at, NOW())
    ON CONFLICT (area_id, layer_type, metric_name, metric_date) DO UPDATE SET
        layer_id        = EXCLUDED.layer_id,
        geojson         = EXCLUDED.geojson,
        style_hint      = EXCLUDED.style_hint,
        source_snapshot = EXCLUDED.source_snapshot,
        expires_at      = EXCLUDED.expires_at,
        updated_at      = NOW()
    """
)


SEED_AREAS_SQL = text(
    """
    SELECT area_id, area_name
    FROM app_area_dimension
    WHERE """
)


def _resolve_seed_area_ids(session) -> list[tuple[str, str]]:
    seeds = settings.bootstrap_area_list
    if not seeds:
        return []
    clauses = " OR ".join([f"area_name ILIKE :p{i}" for i in range(len(seeds))])
    sql = text(SEED_AREAS_SQL.text + f"({clauses}) ORDER BY area_id")
    params = {f"p{i}": f"%{name}%" for i, name in enumerate(seeds)}
    return [(r["area_id"], r["area_name"]) for r in session.execute(sql, params).mappings()]


def _build_layer(
    session,
    *,
    area_id: str,
    area_name: str,
    layer_type: str,
    metric_name: str,
    sql: Any,
    sql_params: dict[str, Any],
    style: dict[str, Any],
    metric_date: date,
    expires_at: datetime,
) -> bool:
    """Build and upsert a single layer. Returns True if a row was written."""
    import json

    geojson = session.execute(sql, sql_params).scalar()
    if geojson is None:
        return False
    feature_count = 0
    if isinstance(geojson, dict) and isinstance(geojson.get("features"), list):
        feature_count = len(geojson["features"])
    layer_id = f"{area_id}__{layer_type}__{metric_name}__{metric_date.isoformat()}"
    snapshot = {
        "area_id": area_id,
        "area_name": area_name,
        "layer_type": layer_type,
        "metric_name": metric_name,
        "feature_count": feature_count,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    session.execute(
        UPSERT_LAYER_SQL,
        {
            "layer_id": layer_id,
            "area_id": area_id,
            "layer_type": layer_type,
            "metric_name": metric_name,
            "metric_date": metric_date,
            "geojson": json.dumps(geojson),
            "style_hint": json.dumps(style),
            "source_snapshot": json.dumps(snapshot),
            "expires_at": expires_at,
        },
    )
    return True


def run(trigger_type: str = "manual") -> JobResult:
    if not settings.map_layer_pregenerate_for_seed:
        # Operator opted out — do nothing but still log.
        with job_run(
            "build_map_layers",
            trigger_type=trigger_type,
            target_scope={"skipped": "MAP_LAYER_PREGENERATE_FOR_SEED=false"},
        ) as (ctx, result):
            ctx.metadata = {"skipped": True}
        return result

    today = date.today()
    expires_at = datetime.now(timezone.utc) + timedelta(days=LAYER_TTL_DAYS)

    with job_run(
        "build_map_layers",
        trigger_type=trigger_type,
        target_scope={
            "seed_areas": settings.bootstrap_area_list,
            "ttl_days": LAYER_TTL_DAYS,
        },
    ) as (ctx, result):
        with db_session() as session:
            areas = _resolve_seed_area_ids(session)
        if not areas:
            raise RuntimeError("No NTAs match SYNC_BOOTSTRAP_AREAS; run sync_nta first.")

        layers_built = 0
        layers_failed: list[str] = []
        per_area: dict[str, int] = {}

        for area_id, area_name in areas:
            built_for_this = 0
            specs = [
                ("choropleth", "safety",
                 CHOROPLETH_SAFETY_SQL, {"area_id": area_id},
                 STYLE_CHOROPLETH_SAFETY),
                ("heatmap", "crime",
                 HEATMAP_CRIME_SQL,
                 {"area_id": area_id, "limit": HEATMAP_POINTS_PER_AREA},
                 STYLE_HEATMAP_CRIME),
                ("marker", "entertainment",
                 MARKER_BY_TYPE_SQL,
                 {"area_id": area_id, "poi_type": "entertainment",
                  "limit": MARKER_POINTS_PER_AREA},
                 STYLE_MARKER_ENTERTAINMENT),
                ("marker", "convenience",
                 MARKER_BY_TYPE_SQL,
                 {"area_id": area_id, "poi_type": "convenience",
                  "limit": MARKER_POINTS_PER_AREA},
                 STYLE_MARKER_CONVENIENCE),
            ]
            for layer_type, metric_name, sql, sql_params, style in specs:
                # Each layer in its own session so one failure doesn't roll
                # back the others (per design "图层生成失败不阻塞").
                try:
                    with db_session() as session:
                        ok = _build_layer(
                            session,
                            area_id=area_id, area_name=area_name,
                            layer_type=layer_type, metric_name=metric_name,
                            sql=sql, sql_params=sql_params,
                            style=style, metric_date=today,
                            expires_at=expires_at,
                        )
                    if ok:
                        layers_built += 1
                        built_for_this += 1
                except Exception as exc:
                    key = f"{area_id}/{layer_type}/{metric_name}"
                    layers_failed.append(f"{key}: {exc}")
                    logger.warning("layer_build_failed key=%s err=%s", key, exc)
            per_area[area_id] = built_for_this

        ctx.rows_fetched = len(areas) * 4
        ctx.rows_written = layers_built
        ctx.metadata = {
            "areas_processed": len(areas),
            "layers_per_area_target": 4,
            "layers_built": layers_built,
            "layers_failed_count": len(layers_failed),
            "layers_failed_sample": layers_failed[:10],
            "ttl_days": LAYER_TTL_DAYS,
            "metric_date": today.isoformat(),
        }
        logger.info(
            "build_map_layers done areas=%d built=%d failed=%d",
            len(areas), layers_built, len(layers_failed),
        )
    return result
