"""A7 — Verify the derivation SQL we added to fill `crime_index_100` and
`rent_index_value` produces correct results against deterministic fixtures.

Each test runs in its own ephemeral PG schema (via the `isolated_schema`
fixture in conftest.py) so the production data we share with other tests is
never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[2]
NYPD_JOB = REPO_ROOT / "services" / "data-sync-service" / "app" / "jobs" / "sync_nypd_crime.py"
RENT_REFRESH = REPO_ROOT / "services" / "data-sync-service" / "app" / "jobs" / "_rent_refresh.py"


def _extract_sql(source: Path, marker: str) -> str:
    """Pull a single text("...") block from a source file by its variable name."""
    contents = source.read_text(encoding="utf-8")
    needle = f"{marker} = text("
    idx = contents.index(needle) + len(needle)
    # Find the matching closing parenthesis at the original indent.
    depth = 1
    end = idx
    while end < len(contents) and depth > 0:
        ch = contents[end]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        end += 1
    return contents[idx:end - 1].strip().strip('"').strip("'").strip('"""').strip("'''")


# Re-extract the SQL bodies once per session.
INDEX_REFRESH_SQL = _extract_sql(NYPD_JOB, "INDEX_REFRESH_SQL")
CARRY_FORWARD_SQL = _extract_sql(RENT_REFRESH, "CARRY_FORWARD_SQL")
REFRESH_RENT_INDEX_SQL = _extract_sql(RENT_REFRESH, "REFRESH_RENT_INDEX_SQL")


@pytest.fixture()
def seeded(isolated_schema):
    """Seed three NTAs + a couple of rent fact rows. Returns the engine."""
    with isolated_schema.begin() as conn:
        # Three NTAs with simple polygons (we don't need real geometry for
        # derivation correctness, but the column exists and is NOT NULL-safe
        # because we pass valid GeoJSON).
        conn.execute(text("""
            INSERT INTO app_area_dimension (area_id, area_name, borough)
            VALUES ('TST01', 'A', 'Queens'),
                   ('TST02', 'B', 'Queens'),
                   ('TST03', 'C', 'Brooklyn')
        """))
    return isolated_schema


def test_crime_index_min_max_normalization(seeded):
    """With counts 10/50/100 the worst NTA must end up at index 100; others
    are scaled proportionally."""
    with seeded.begin() as conn:
        conn.execute(text("""
            INSERT INTO app_area_metrics_daily (area_id, metric_date, crime_count_30d)
            VALUES ('TST01', CURRENT_DATE, 10),
                   ('TST02', CURRENT_DATE, 50),
                   ('TST03', CURRENT_DATE, 100)
        """))
        conn.execute(text(INDEX_REFRESH_SQL))
        rows = {
            r["area_id"]: float(r["crime_index_100"])
            for r in conn.execute(text(
                "SELECT area_id, crime_index_100 FROM app_area_metrics_daily "
                "WHERE metric_date=CURRENT_DATE"
            )).mappings()
        }
    assert rows["TST03"] == pytest.approx(100.0, abs=0.01)
    assert rows["TST02"] == pytest.approx(50.0, abs=0.01)
    assert rows["TST01"] == pytest.approx(10.0, abs=0.01)


def test_crime_index_handles_all_zero_counts(seeded):
    """If everyone is 0, division by zero must not crash; index stays 0."""
    with seeded.begin() as conn:
        conn.execute(text("""
            INSERT INTO app_area_metrics_daily (area_id, metric_date, crime_count_30d)
            VALUES ('TST01', CURRENT_DATE, 0),
                   ('TST02', CURRENT_DATE, 0)
        """))
        conn.execute(text(INDEX_REFRESH_SQL))
        rows = list(conn.execute(text(
            "SELECT crime_index_100 FROM app_area_metrics_daily WHERE metric_date=CURRENT_DATE"
        )).mappings())
    assert all(float(r["crime_index_100"]) == 0.0 for r in rows)


def test_rent_index_priority_rentcast_over_zori(seeded):
    """Priority order: rentcast median > zori_all > hud_fmr_2br."""
    with seeded.begin() as conn:
        # TST01 has only HUD, TST02 has HUD + ZORI, TST03 has all three.
        conn.execute(text("""
            INSERT INTO app_area_rent_benchmark_monthly
                (area_id, benchmark_month, bedroom_type, benchmark_rent,
                 benchmark_type, benchmark_geo_type, benchmark_geo_id, source)
            VALUES ('TST01','2026-01-01','2br',2000,'hud_fmr','metro','m1','hud_fmr'),
                   ('TST02','2026-01-01','2br',2200,'hud_fmr','metro','m1','hud_fmr'),
                   ('TST02','2026-01-01','all',3500,'zori','zip','11101','zori'),
                   ('TST03','2026-01-01','2br',2400,'hud_fmr','metro','m1','hud_fmr'),
                   ('TST03','2026-01-01','all',3700,'zori','zip','11102','zori')
        """))
        conn.execute(text("""
            INSERT INTO app_area_rental_market_daily
                (area_id, metric_date, bedroom_type, listing_type, rent_median, source)
            VALUES ('TST03', CURRENT_DATE, '1br', 'rental', 4200, 'rentcast'),
                   ('TST03', CURRENT_DATE, '2br', 'rental', 5800, 'rentcast')
        """))
        conn.execute(text(CARRY_FORWARD_SQL))
        conn.execute(text(REFRESH_RENT_INDEX_SQL))
        rows = {
            r["area_id"]: (float(r["rent_index_value"]),
                           r["source_snapshot"]["rent_index_value"]["source"])
            for r in conn.execute(text(
                "SELECT area_id, rent_index_value, source_snapshot "
                "FROM app_area_metrics_daily WHERE metric_date=CURRENT_DATE"
            )).mappings()
        }
    # TST01 → only HUD available.
    assert rows["TST01"][1] == "hud_fmr_2br"
    assert rows["TST01"][0] == pytest.approx(2000.0)
    # TST02 → ZORI wins over HUD.
    assert rows["TST02"][1] == "zori_all_bedroom"
    assert rows["TST02"][0] == pytest.approx(3500.0)
    # TST03 → RentCast wins, rent = avg(4200, 5800) = 5000.
    assert rows["TST03"][1] == "rentcast_market_median"
    assert rows["TST03"][0] == pytest.approx(5000.0)


def test_carry_forward_copies_yesterday_when_today_absent(seeded):
    """CARRY_FORWARD_SQL is the safety net so a rent-only refresh doesn't
    blank out crime/poi columns from yesterday."""
    with seeded.begin() as conn:
        # Yesterday — full snapshot for TST01.
        conn.execute(text("""
            INSERT INTO app_area_metrics_daily
                (area_id, metric_date, crime_count_30d, crime_index_100,
                 entertainment_poi_count, transit_station_count)
            VALUES ('TST01', CURRENT_DATE - 1, 99, 88.5, 42, 7)
        """))
        conn.execute(text(CARRY_FORWARD_SQL))
        row = conn.execute(text(
            "SELECT crime_count_30d, crime_index_100, entertainment_poi_count, "
            "transit_station_count FROM app_area_metrics_daily "
            "WHERE area_id='TST01' AND metric_date=CURRENT_DATE"
        )).mappings().first()
    assert row is not None
    assert row["crime_count_30d"] == 99
    assert float(row["crime_index_100"]) == pytest.approx(88.5)
    assert row["entertainment_poi_count"] == 42
    assert row["transit_station_count"] == 7


def test_carry_forward_is_idempotent_does_not_overwrite_today(seeded):
    """If today's row already exists with newer values, CARRY_FORWARD must
    not stomp on it (ON CONFLICT DO NOTHING)."""
    with seeded.begin() as conn:
        conn.execute(text("""
            INSERT INTO app_area_metrics_daily (area_id, metric_date, crime_count_30d)
            VALUES ('TST01', CURRENT_DATE - 1, 50),
                   ('TST01', CURRENT_DATE, 200)
        """))
        conn.execute(text(CARRY_FORWARD_SQL))
        row = conn.execute(text(
            "SELECT crime_count_30d FROM app_area_metrics_daily "
            "WHERE area_id='TST01' AND metric_date=CURRENT_DATE"
        )).mappings().first()
    assert row["crime_count_30d"] == 200
