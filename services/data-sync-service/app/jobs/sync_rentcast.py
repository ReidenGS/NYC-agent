"""sync_rentcast — pull RentCast long-term rental listings into NTAs.

Source: RentCast `/listings/rental/long-term` (manual trigger only).
Auth:   X-Api-Key from RENTCAST_API_KEY (.env).

Cost protection per docs/NYC_Agent_Data_Sync_Design.md §6:
  - per-run cap   : RENTCAST_MAX_CALLS_PER_RUN  (default 5)
  - per-month cap : RENTCAST_MAX_CALLS_PER_MONTH (default 50)
  - no auto retry
  - sum(api_calls_used) over current calendar month is checked from
    app_data_sync_job_log before issuing any call.

Strategy:
  - One API call covers up to 500 listings for city='New York', state='NY',
    status='Active'. Within MVP cost budget that's enough.
  - If more pages are needed, paginate with offset and respect both caps.

Field mapping (docs/NYC_Agent_Data_Sources_API_SQL.md §5.6 + §6 table 8):
  id              -> listing_id (PK), source_record_id
  formattedAddress, city, state, zipCode, latitude, longitude
  propertyType    -> property_type
  bedrooms        -> bedrooms / bedroom_type (0=studio, 1=1br, 2=2br, 3=3br)
  bathrooms, squareFootage
  price           -> monthly_rent
  status, listedDate, lastSeenDate, daysOnMarket
  listingAgent.{name,phone}

Spatial assignment via ST_Contains. Then aggregate to
app_area_rental_market_daily by (area_id, today, bedroom_type) with
rent_min/median/max + listing_count + data_quality='realtime'.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from app.clients import rentcast_client
from app.db.session import db_session
from app.jobs.base import JobResult, job_run
from app.settings import settings

logger = logging.getLogger(__name__)


MONTH_USED_SQL = text(
    """
    SELECT COALESCE(SUM(api_calls_used), 0)
    FROM app_data_sync_job_log
    WHERE job_name = 'sync_rentcast'
      AND status IN ('succeeded', 'partial', 'failed')
      AND date_trunc('month', started_at) = date_trunc('month', NOW())
    """
)


UPSERT_LISTING_SQL = text(
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
    INSERT INTO app_area_rental_listing_snapshot
        (listing_id, area_id, snapshot_date,
         formatted_address, city, state, zip_code,
         latitude, longitude, geom,
         property_type, bedroom_type, bedrooms, bathrooms, square_footage,
         monthly_rent, listing_status,
         listed_date, last_seen_date, days_on_market,
         listing_agent_name, listing_agent_phone,
         source, raw_source, updated_at)
    SELECT :listing_id, nta.area_id, :snapshot_date,
           :formatted_address, :city, :state, :zip_code,
           :lat, :lon, pt.geom,
           :property_type, :bedroom_type, :bedrooms, :bathrooms, :square_footage,
           :monthly_rent, :listing_status,
           :listed_date, :last_seen_date, :days_on_market,
           :listing_agent_name, :listing_agent_phone,
           'rentcast_listings', CAST(:raw_source AS JSONB), NOW()
    FROM nta, pt
    ON CONFLICT (listing_id) DO UPDATE SET
        area_id              = EXCLUDED.area_id,
        snapshot_date        = EXCLUDED.snapshot_date,
        formatted_address    = EXCLUDED.formatted_address,
        city                 = EXCLUDED.city,
        state                = EXCLUDED.state,
        zip_code             = EXCLUDED.zip_code,
        latitude             = EXCLUDED.latitude,
        longitude            = EXCLUDED.longitude,
        geom                 = EXCLUDED.geom,
        property_type        = EXCLUDED.property_type,
        bedroom_type         = EXCLUDED.bedroom_type,
        bedrooms             = EXCLUDED.bedrooms,
        bathrooms            = EXCLUDED.bathrooms,
        square_footage       = EXCLUDED.square_footage,
        monthly_rent         = EXCLUDED.monthly_rent,
        listing_status       = EXCLUDED.listing_status,
        listed_date          = EXCLUDED.listed_date,
        last_seen_date       = EXCLUDED.last_seen_date,
        days_on_market       = EXCLUDED.days_on_market,
        listing_agent_name   = EXCLUDED.listing_agent_name,
        listing_agent_phone  = EXCLUDED.listing_agent_phone,
        raw_source           = EXCLUDED.raw_source,
        updated_at           = NOW()
    """
)


AGGREGATE_SQL = text(
    """
    INSERT INTO app_area_rental_market_daily
        (area_id, metric_date, bedroom_type, listing_type,
         rent_min, rent_median, rent_max, listing_count,
         data_quality, source, source_snapshot, updated_at)
    SELECT area_id, CURRENT_DATE, bedroom_type, 'rental',
           MIN(monthly_rent),
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY monthly_rent),
           MAX(monthly_rent),
           COUNT(*),
           'realtime', 'rentcast',
           jsonb_build_object('source', 'rentcast_listings',
                              'snapshot_date', CURRENT_DATE),
           NOW()
    FROM app_area_rental_listing_snapshot
    WHERE source = 'rentcast_listings'
      AND monthly_rent IS NOT NULL
      AND snapshot_date = CURRENT_DATE
    GROUP BY area_id, bedroom_type
    ON CONFLICT (area_id, metric_date, bedroom_type, listing_type, source)
    DO UPDATE SET
        rent_min        = EXCLUDED.rent_min,
        rent_median     = EXCLUDED.rent_median,
        rent_max        = EXCLUDED.rent_max,
        listing_count   = EXCLUDED.listing_count,
        data_quality    = EXCLUDED.data_quality,
        source_snapshot = EXCLUDED.source_snapshot,
        updated_at      = NOW()
    """
)


BEDROOM_TYPE_BY_INT: dict[int, str] = {0: "studio", 1: "1br", 2: "2br", 3: "3br"}


def _bedroom_type(bedrooms: float | None) -> str:
    if bedrooms is None:
        return "unknown"
    try:
        n = int(round(float(bedrooms)))
    except (TypeError, ValueError):
        return "unknown"
    return BEDROOM_TYPE_BY_INT.get(n, "unknown")


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    f = _to_float(v)
    return None if f is None else int(round(f))


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def run(trigger_type: str = "manual") -> JobResult:
    if not settings.rentcast_api_key:
        raise RuntimeError("RENTCAST_API_KEY not set; refusing to run sync_rentcast.")

    snapshot_date = date.today()

    with job_run(
        "sync_rentcast",
        trigger_type=trigger_type,
        target_scope={"city": "New York", "state": "NY", "snapshot_date": str(snapshot_date)},
    ) as (ctx, result):
        # 1. Enforce per-month cap by inspecting prior job logs.
        with db_session() as session:
            month_used = int(session.execute(MONTH_USED_SQL).scalar() or 0)
        cap = settings.rentcast_max_calls_per_month
        per_run = settings.rentcast_max_calls_per_run
        remaining = cap - month_used
        if remaining <= 0:
            raise RuntimeError(
                f"RentCast monthly cap reached: used={month_used}/{cap}; aborting."
            )
        run_cap = min(per_run, remaining)
        logger.info(
            "rentcast_budget month_used=%d cap_month=%d cap_run=%d effective=%d",
            month_used, cap, per_run, run_cap,
        )

        # 2. Pull listings (one page = up to 500). Respect both caps.
        # CRITICAL (per Codex review P1): the budget counter increments BEFORE
        # the HTTP call (so failures still count as consumed quota — RentCast
        # may have charged us). We must mirror that into ctx.api_calls_used
        # whether or not the loop completes successfully, otherwise job_run()'s
        # failure path would persist api_calls_used=0 and the per-month cap
        # (which sums prior log rows) would under-count.
        budget = rentcast_client.RentCastBudget(max_per_run=run_cap)
        offset = 0
        all_listings: list[dict[str, Any]] = []
        try:
            while True:
                try:
                    page = rentcast_client.fetch_long_term_rentals(
                        budget=budget,
                        offset=offset,
                        limit=rentcast_client.LISTINGS_PER_CALL,
                    )
                except rentcast_client.RentCastQuotaExceeded:
                    logger.info(
                        "rentcast_quota_exceeded after %d calls", budget.used
                    )
                    break
                # Successful page: record now so even if a later page raises
                # we still capture every consumed call.
                ctx.api_calls_used = budget.used
                if not page:
                    break
                all_listings.extend(page)
                if len(page) < rentcast_client.LISTINGS_PER_CALL:
                    break
                offset += len(page)
        finally:
            # Failure path (network, 401/403, 5xx, anything) lands here too.
            # The increment-before-call pattern in the client means budget.used
            # is the truthful count of attempted calls.
            ctx.api_calls_used = budget.used

        seen = len(all_listings)
        logger.info("rentcast_listings_fetched count=%d calls=%d", seen, budget.used)

        # 3. Upsert snapshot rows; rows outside any NTA are dropped.
        written = 0
        skipped_no_id = 0
        skipped_no_geom = 0
        skipped_outside = 0

        with db_session() as session:
            for r in all_listings:
                listing_id = (r.get("id") or "").strip()
                if not listing_id:
                    skipped_no_id += 1
                    continue
                lat = _to_float(r.get("latitude"))
                lon = _to_float(r.get("longitude"))
                if lat is None or lon is None:
                    skipped_no_geom += 1
                    continue

                bedrooms = _to_float(r.get("bedrooms"))
                agent = r.get("listingAgent") or {}
                params = {
                    "listing_id": listing_id,
                    "snapshot_date": snapshot_date,
                    "formatted_address": (r.get("formattedAddress") or "").strip()
                                          or listing_id,
                    "city": (r.get("city") or "").strip() or None,
                    "state": (r.get("state") or "").strip() or None,
                    "zip_code": (r.get("zipCode") or "").strip() or None,
                    "lat": lat,
                    "lon": lon,
                    "property_type": (r.get("propertyType") or "").strip() or None,
                    "bedroom_type": _bedroom_type(bedrooms),
                    "bedrooms": bedrooms,
                    "bathrooms": _to_float(r.get("bathrooms")),
                    "square_footage": _to_int(r.get("squareFootage")),
                    "monthly_rent": _to_float(r.get("price")),
                    "listing_status": (r.get("status") or "").strip() or None,
                    "listed_date": _parse_dt(r.get("listedDate")),
                    "last_seen_date": _parse_dt(r.get("lastSeenDate")),
                    "days_on_market": _to_int(r.get("daysOnMarket")),
                    "listing_agent_name": (agent.get("name") or "").strip() or None,
                    "listing_agent_phone": (agent.get("phone") or "").strip() or None,
                    "raw_source": json.dumps(r, default=str),
                }
                rc = session.execute(UPSERT_LISTING_SQL, params).rowcount or 0
                if rc:
                    written += 1
                else:
                    skipped_outside += 1
            session.commit()

        # 4. Aggregate today's snapshot into the market table.
        with db_session() as session:
            session.execute(AGGREGATE_SQL)

        ctx.rows_fetched = seen
        ctx.rows_written = written
        ctx.api_calls_used = budget.used
        ctx.metadata = {
            "snapshot_date": str(snapshot_date),
            "month_calls_before_run": month_used,
            "month_calls_after_run": month_used + budget.used,
            "monthly_cap": cap,
            "run_cap_effective": run_cap,
            "skipped_no_id": skipped_no_id,
            "skipped_no_geom": skipped_no_geom,
            "skipped_outside_nta": skipped_outside,
        }
        logger.info(
            "sync_rentcast done seen=%d written=%d outside=%d calls=%d month_total=%d",
            seen, written, skipped_outside, budget.used, month_used + budget.used,
        )
    return result
