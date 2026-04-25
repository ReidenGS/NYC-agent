"""sync_hud_fmr — pull HUD Fair Market Rent benchmarks per NYC county.

Source: HUD USER Fair Market Rent API (`/fmr/data/{entityId}?year=...`).
Auth:   HUD_USER_API_TOKEN (free JWT).

Empirical observation (verified on 2026-04-25 with the live API): all 5
NYC county FIPS entities return identical FMR values because they share
the "New York, NY HUD Metro FMR Area". We still write one row per
county so the benchmark_geo_id column is honest about the legal source
unit, and so the storage shape generalises if HUD ever splits the metro.

Field mapping (docs/NYC_Agent_Data_Sources_API_SQL.md §6 table 10):
  benchmark_type     = 'hud_fmr'
  benchmark_geo_type = 'county'
  benchmark_geo_id   = 10-digit HUD entityId (e.g. '3606199999')
  bedroom_type       = 'studio' / '1br' / '2br' / '3br' / '4br'
  benchmark_month    = first day of the FMR fiscal year (Oct 1)
  data_quality       = 'official'

Borough -> NTA expansion: each NTA in a borough gets a row pointing at
that borough's FMR, so a Domain Agent can do a single area_id lookup.

Coexists with sync_zori_hud rows (benchmark_type='zori', granularity
'zip') — the PK includes benchmark_type and benchmark_geo_id so both
sources accumulate without conflict.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import text

from app.clients import hud_user_client
from app.db.session import db_session
from app.jobs.base import JobResult, job_run

logger = logging.getLogger(__name__)


# borough_name (matches app_area_dimension.borough) -> 10-digit HUD entityId
BOROUGH_TO_FIPS: dict[str, str] = {
    "Bronx":         "3600599999",
    "Brooklyn":      "3604799999",   # Kings County
    "Manhattan":     "3606199999",   # New York County
    "Queens":        "3608199999",
    "Staten Island": "3608599999",   # Richmond County
}

# HUD JSON key  ->  schema bedroom_type
BEDROOM_KEY_MAP: dict[str, str] = {
    "Efficiency":     "studio",
    "One-Bedroom":    "1br",
    "Two-Bedroom":    "2br",
    "Three-Bedroom":  "3br",
    "Four-Bedroom":   "4br",
}


UPSERT_SQL = text(
    """
    INSERT INTO app_area_rent_benchmark_monthly
        (area_id, benchmark_month, bedroom_type,
         benchmark_rent, benchmark_type,
         benchmark_geo_type, benchmark_geo_id,
         data_quality, source, source_snapshot, updated_at)
    SELECT a.area_id, :benchmark_month, :bedroom_type,
           :rent, 'hud_fmr',
           'county', :fips_entity_id,
           'official', 'hud_fmr',
           CAST(:source_snapshot AS JSONB), NOW()
    FROM app_area_dimension a
    WHERE a.borough = :borough
    ON CONFLICT (area_id, benchmark_month, bedroom_type, benchmark_type, benchmark_geo_id)
    DO UPDATE SET
        benchmark_rent  = EXCLUDED.benchmark_rent,
        data_quality    = EXCLUDED.data_quality,
        source_snapshot = EXCLUDED.source_snapshot,
        updated_at      = NOW()
    """
)


def _fmr_year() -> int:
    """Pick the FMR year to query.

    HUD publishes FY data — the FY runs Oct (Y-1) → Sep (Y). Our
    benchmark_month convention (first of FY) means a FY 2025 record gets
    benchmark_month = 2024-10-01. We always ask for the most recently
    published FY based on today's date.
    """
    today = date.today()
    # FY rolls over each October. Treat October onwards as the new FY.
    return today.year + 1 if today.month >= 10 else today.year


def _benchmark_month(fmr_year: int) -> date:
    return date(fmr_year - 1, 10, 1)


def run(trigger_type: str = "manual") -> JobResult:
    fmr_year = _fmr_year()
    bm_month = _benchmark_month(fmr_year)

    with job_run(
        "sync_hud_fmr",
        trigger_type=trigger_type,
        target_scope={
            "fmr_year": fmr_year,
            "benchmark_month": bm_month.isoformat(),
            "boroughs": list(BOROUGH_TO_FIPS.keys()),
        },
    ) as (ctx, result):
        api_calls = 0
        rows_written = 0
        per_borough: dict[str, dict[str, Any]] = {}
        failed: list[str] = []

        for borough, fips in BOROUGH_TO_FIPS.items():
            try:
                payload = hud_user_client.fetch_fmr_for_county(fips, fmr_year)
                api_calls += 1
            except hud_user_client.HudError as exc:
                failed.append(f"{borough}({fips}): {exc}")
                logger.warning("hud_borough_failed borough=%s err=%s", borough, exc)
                continue

            basic = payload.get("basicdata") or {}
            missing_keys = [k for k in BEDROOM_KEY_MAP if k not in basic]
            if missing_keys:
                failed.append(f"{borough}({fips}): missing basicdata keys {missing_keys}")
                logger.warning(
                    "hud_borough_missing_keys borough=%s missing=%s",
                    borough, missing_keys,
                )
                continue
            per_borough[borough] = {
                "fips": fips,
                "area_name": payload.get("area_name"),
                "metro_name": payload.get("metro_name"),
                "rents": {BEDROOM_KEY_MAP[k]: v for k, v in basic.items() if k in BEDROOM_KEY_MAP},
            }

            with db_session() as session:
                for hud_key, schema_key in BEDROOM_KEY_MAP.items():
                    rent = basic.get(hud_key)
                    if rent is None:
                        continue
                    snap = json.dumps(
                        {
                            "fips_entity_id": fips,
                            "borough": borough,
                            "area_name": payload.get("area_name"),
                            "metro_name": payload.get("metro_name"),
                            "fmr_year": fmr_year,
                            "hud_bedroom_key": hud_key,
                        },
                        default=str,
                    )
                    rc = session.execute(
                        UPSERT_SQL,
                        {
                            "borough": borough,
                            "benchmark_month": bm_month,
                            "bedroom_type": schema_key,
                            "rent": float(rent),
                            "fips_entity_id": fips,
                            "source_snapshot": snap,
                        },
                    ).rowcount or 0
                    rows_written += rc

        ctx.api_calls_used = api_calls
        ctx.rows_written = rows_written
        ctx.rows_fetched = api_calls  # one payload per call
        ctx.metadata = {
            "fmr_year": fmr_year,
            "benchmark_month": bm_month.isoformat(),
            "per_borough": per_borough,
            "failed_boroughs": failed,
        }
        if rows_written == 0:
            raise RuntimeError(f"HUD FMR wrote 0 rows; failures={failed[:3]}")
        if failed:
            result.status = "partial"
        logger.info(
            "sync_hud_fmr done year=%d api_calls=%d rows_written=%d failed=%d",
            fmr_year, api_calls, rows_written, len(failed),
        )
    return result
