"""D — Data quality / contract tests.

These read the LIVE postgres state (not an isolated schema) to verify that
the bootstrapped data the application reads at runtime satisfies the
invariants its code assumes. Failures here mean the production query path
will surface bad data even when nothing in the API layer is broken.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text


def test_v_area_metrics_latest_is_one_row_per_area(pg_engine):
    with pg_engine.connect() as conn:
        dup = conn.execute(text("""
            SELECT area_id, COUNT(*) AS n FROM v_area_metrics_latest
            GROUP BY area_id HAVING COUNT(*) > 1
        """)).fetchall()
    assert dup == [], f"v_area_metrics_latest has duplicate area_ids: {dup}"


def test_crime_index_100_within_bounds(pg_engine):
    with pg_engine.connect() as conn:
        out_of_range = conn.execute(text("""
            SELECT area_id, crime_index_100 FROM app_area_metrics_daily
            WHERE crime_index_100 IS NOT NULL
              AND (crime_index_100 < 0 OR crime_index_100 > 100)
        """)).fetchall()
    assert out_of_range == [], f"crime_index_100 out of [0,100]: {out_of_range}"


def test_rent_index_value_coverage(pg_engine):
    """At least 80% of NTAs should have a rent_index_value after the
    refresh we wired into the rent jobs."""
    with pg_engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM app_area_dimension")).scalar_one()
        with_rent = conn.execute(text("""
            SELECT COUNT(*) FROM v_area_metrics_latest
            WHERE rent_index_value IS NOT NULL AND rent_index_value > 0
        """)).scalar_one()
    coverage = with_rent / total if total else 0
    assert coverage >= 0.80, f"only {with_rent}/{total} NTAs have rent_index_value"


def test_map_layer_cache_geojson_is_valid_feature_collection(pg_engine):
    with pg_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT layer_id, geojson FROM app_map_layer_cache LIMIT 25
        """)).mappings().all()
    assert rows, "no map layers cached — bootstrap may have skipped build_map_layers"
    for row in rows:
        gj = row["geojson"]
        if isinstance(gj, str):
            gj = json.loads(gj)
        assert gj.get("type") == "FeatureCollection", f"{row['layer_id']} not a FeatureCollection"
        assert isinstance(gj.get("features"), list)


def test_crime_incident_spatial_assignment_majority(pg_engine):
    """At least 90% of crime incidents with coordinates should be assigned
    to an NTA via the PostGIS spatial join — otherwise the area filter on
    /chat queries silently misses most data."""
    with pg_engine.connect() as conn:
        total = conn.execute(text("""
            SELECT COUNT(*) FROM app_crime_incident_snapshot
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """)).scalar_one()
        assigned = conn.execute(text("""
            SELECT COUNT(*) FROM app_crime_incident_snapshot
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND area_id IS NOT NULL
        """)).scalar_one()
    if total == 0:
        pytest.skip("no crime data loaded yet")
    assert assigned / total >= 0.90, f"only {assigned}/{total} crimes assigned to NTAs"


def test_metric_source_snapshot_window_end_present(pg_engine):
    """Time-sensitive metrics must record the window_end so the agent can
    disclose data lag (BL §8 compliance)."""
    with pg_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT area_id,
                   source_snapshot->'crime_count_30d'->>'window_end' AS crime_we
            FROM v_area_metrics_latest
            WHERE crime_count_30d > 0
            LIMIT 25
        """)).mappings().all()
    if not rows:
        pytest.skip("no crime metrics populated yet")
    missing = [r["area_id"] for r in rows if not r["crime_we"]]
    assert missing == [], f"crime_count_30d missing window_end for: {missing[:5]}"


def test_v_sync_freshness_reports_all_known_jobs(pg_engine):
    """v_sync_freshness must surface every job name we expect to run, so the
    /sync/freshness endpoint can show a complete operations dashboard."""
    with pg_engine.connect() as conn:
        names = {
            r[0] for r in conn.execute(text(
                "SELECT job_name FROM v_sync_freshness"
            )).fetchall()
        }
    expected = {"sync_nta", "sync_nypd_crime", "sync_overpass_poi",
                "sync_facilities", "sync_mta_static", "build_map_layers"}
    missing = expected - names
    assert not missing, f"v_sync_freshness missing jobs: {missing}"
