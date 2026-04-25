"""sync_zori_hud — pull Zillow ZORI ZIP-level rent benchmarks into NTAs.

Source: Zillow Research public CSV (ZIP granularity).
URL: ZORI_ZIP_CSV_URL setting.

Dataset shape (wide): RegionID, SizeRank, RegionName=ZIP, RegionType,
StateName, State, City, Metro, CountyName, then YYYY-MM-DD columns
(end-of-month rent values).

ZIP -> NTA mapping is built each run by:
  1. Fetching NYC Modified ZCTA polygons from Socrata (`pri4-ifjk`).
  2. Loading them into a TEMP table with PostGIS geometry built from
     GeoJSON.
  3. For each ZIP, picking the NTA whose polygon contains the ZIP
     centroid (ST_Contains). One ZIP -> one NTA (largest-overlap proxy).

Per docs/NYC_Agent_Data_Sources_API_SQL.md §6 table 10
(app_area_rent_benchmark_monthly):
  benchmark_type     = 'zori'
  benchmark_geo_type = 'zip'
  benchmark_geo_id   = ZIP code (5 digits)
  bedroom_type       = 'all'  (ZORI is all-bedrooms aggregate)
  benchmark_month    = first-of-month derived from ZORI column header

HUD FMR is intentionally not in this round (public download is xlsx-only
and county-level). Defer to a separate job.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date
from typing import Any

import httpx
from sqlalchemy import text

from app.clients import socrata_client
from app.db.session import db_session
from app.jobs.base import JobResult, job_run
from app.settings import settings

logger = logging.getLogger(__name__)

MODZCTA_DATASET = "pri4-ifjk"
HISTORY_MONTHS = 24


CREATE_TMP_ZIP_NTA = text(
    """
    CREATE TEMP TABLE _stg_zip_nta (
        zip TEXT PRIMARY KEY,
        geom GEOMETRY(MULTIPOLYGON, 4326)
    ) ON COMMIT DROP
    """
)

INSERT_TMP_ZIP_GEOM = text(
    """
    INSERT INTO _stg_zip_nta (zip, geom)
    VALUES (:zip, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_text), 4326)))
    ON CONFLICT (zip) DO NOTHING
    """
)

BUILD_ZIP_TO_NTA = text(
    """
    SELECT z.zip, a.area_id
    FROM _stg_zip_nta z
    JOIN app_area_dimension a
      ON ST_Contains(a.geom, ST_Centroid(z.geom))
    """
)


UPSERT_BENCHMARK_SQL = text(
    """
    INSERT INTO app_area_rent_benchmark_monthly
        (area_id, benchmark_month, bedroom_type,
         benchmark_rent, benchmark_type,
         benchmark_geo_type, benchmark_geo_id,
         data_quality, source, source_snapshot, updated_at)
    VALUES (
        :area_id, :benchmark_month, 'all',
        :rent, 'zori',
        'zip', :zip,
        'benchmark', 'zori',
        CAST(:source_snapshot AS JSONB), NOW()
    )
    ON CONFLICT (area_id, benchmark_month, bedroom_type, benchmark_type, benchmark_geo_id)
    DO UPDATE SET
        benchmark_rent  = EXCLUDED.benchmark_rent,
        data_quality    = EXCLUDED.data_quality,
        source_snapshot = EXCLUDED.source_snapshot,
        updated_at      = NOW()
    """
)


def _parse_month_columns(headers: list[str]) -> list[str]:
    """Return CSV header columns that look like YYYY-MM-DD dates."""
    out: list[str] = []
    for h in headers:
        if (
            len(h) == 10 and h[4] == "-" and h[7] == "-"
            and h[:4].isdigit() and h[5:7].isdigit() and h[8:].isdigit()
        ):
            out.append(h)
    return out


def _to_decimal(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _build_zip_to_nta(session) -> dict[str, str]:
    """Fetch NYC ZCTA polygons, compute centroid->NTA, return {zip: area_id}."""
    session.execute(CREATE_TMP_ZIP_NTA)

    rows_loaded = 0
    for row in socrata_client.fetch_all(
        MODZCTA_DATASET, select="modzcta, the_geom"
    ):
        zip_code = (row.get("modzcta") or "").strip()
        geom = row.get("the_geom")
        if not zip_code or not geom:
            continue
        session.execute(
            INSERT_TMP_ZIP_GEOM,
            {"zip": zip_code, "geom_text": json.dumps(geom)},
        )
        rows_loaded += 1
    logger.info("zip_polygons_loaded count=%d", rows_loaded)

    pairs = session.execute(BUILD_ZIP_TO_NTA).all()
    mapping: dict[str, str] = {}
    for zip_code, area_id in pairs:
        # If a zip centroid happens to land in two NTAs (rare; can happen on
        # boundary edge), the first wins. For MVP that's acceptable.
        mapping.setdefault(zip_code, area_id)
    logger.info("zip_to_nta_mapping size=%d", len(mapping))
    return mapping


def _is_nyc_zip_row(row: dict[str, str]) -> bool:
    state = (row.get("State") or "").strip().upper()
    city = (row.get("City") or "").strip()
    return state == "NY" and city == "New York"


def run(trigger_type: str = "manual") -> JobResult:
    url = settings.zori_zip_csv_url

    with job_run(
        "sync_zori_hud",
        trigger_type=trigger_type,
        target_scope={"source": "zori_zip_csv", "history_months": HISTORY_MONTHS},
    ) as (ctx, result):
        # 1. Build ZIP -> NTA mapping.
        with db_session() as session:
            zip_to_nta = _build_zip_to_nta(session)

        if not zip_to_nta:
            raise RuntimeError("ZIP->NTA mapping is empty; cannot proceed.")

        # 2. Download ZORI ZIP CSV.
        logger.info("zori_download url=%s", url)
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "nyc-agent-data-sync/0.1"})
            r.raise_for_status()
            csv_text = r.text

        reader = csv.DictReader(io.StringIO(csv_text))
        all_headers = reader.fieldnames or []
        month_cols = _parse_month_columns(all_headers)
        if not month_cols:
            raise RuntimeError("ZORI CSV has no YYYY-MM-DD columns; format changed?")
        recent = month_cols[-HISTORY_MONTHS:]
        logger.info(
            "zori_headers months=%d window=%s..%s",
            len(month_cols), recent[0], recent[-1],
        )

        nyc_zip_rows = [r for r in reader if _is_nyc_zip_row(r)]
        seen = len(nyc_zip_rows)
        logger.info("zori_nyc_zip_rows count=%d", seen)

        # 3. Process each NYC ZIP row.
        matched_zips = 0
        unmatched_zips: list[str] = []
        rows_written = 0

        with db_session() as session:
            for zrow in nyc_zip_rows:
                zip_code = (zrow.get("RegionName") or "").strip()
                region_id = (zrow.get("RegionID") or "").strip()
                area_id = zip_to_nta.get(zip_code)
                if not area_id:
                    unmatched_zips.append(zip_code)
                    continue
                matched_zips += 1

                snapshot_base = {
                    "zillow_region_id": region_id,
                    "zip": zip_code,
                    "metro": zrow.get("Metro"),
                    "county_name": zrow.get("CountyName"),
                }

                for col in recent:
                    rent = _to_decimal(zrow.get(col))
                    if rent is None:
                        continue
                    bm = date.fromisoformat(col[:7] + "-01")
                    snap = json.dumps(
                        {**snapshot_base, "month_col": col}, default=str
                    )
                    rc = session.execute(
                        UPSERT_BENCHMARK_SQL,
                        {
                            "area_id": area_id,
                            "benchmark_month": bm,
                            "rent": rent,
                            "zip": zip_code,
                            "source_snapshot": snap,
                        },
                    ).rowcount or 0
                    rows_written += rc
            session.commit()

        ctx.rows_fetched = seen
        ctx.rows_written = rows_written
        ctx.metadata = {
            "source_url": url,
            "zip_to_nta_size": len(zip_to_nta),
            "matched_zips": matched_zips,
            "unmatched_zips_sample": unmatched_zips[:30],
            "unmatched_count": len(unmatched_zips),
            "months_window": [recent[0], recent[-1]],
        }
        logger.info(
            "sync_zori_hud done seen=%d matched=%d written=%d unmatched=%d",
            seen, matched_zips, rows_written, len(unmatched_zips),
        )
    return result
