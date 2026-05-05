"""Derive app_area_metrics_daily.rent_index_value from the rent tables.

Schema declares rent_index_value but no source dataset writes it directly.
Same pattern as crime_index_100 — call refresh_rent_index() at the end of
any job that touches rent data (sync_rentcast / sync_zori_hud / sync_hud_fmr).

Source priority per area:
  1. rentcast: AVG(rent_median) across bedroom_types on the latest metric_date
     — actual ask rent on the live market, most realistic signal.
  2. zori (all bedrooms): latest benchmark_month — broad index, present for
     most NTAs after sync_zori_hud succeeds.
  3. hud_fmr 2br: latest benchmark_month — government baseline, available
     for every NTA so it acts as the universal fallback.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


# Carry-forward step: when this refresh runs on a day where no other sync
# job has populated app_area_metrics_daily yet, an INSERT would create
# today's row with rent + zeros everywhere else. Because v_area_metrics_latest
# picks the latest metric_date per area, that row would mask yesterday's
# full snapshot. So we first copy the most recent prior row per area to
# CURRENT_DATE, leaving rent_index_value to be set by the refresh below.
# Idempotent — ON CONFLICT DO NOTHING means it only runs when today's row
# is absent.
CARRY_FORWARD_SQL = text(
    """
    INSERT INTO app_area_metrics_daily
        (area_id, metric_date, crime_count_30d, crime_index_100,
         entertainment_poi_count, convenience_facility_count,
         transit_station_count, complaint_noise_30d, rent_index_value,
         source_snapshot, updated_at)
    SELECT prev.area_id, CURRENT_DATE,
           prev.crime_count_30d, prev.crime_index_100,
           prev.entertainment_poi_count, prev.convenience_facility_count,
           prev.transit_station_count, prev.complaint_noise_30d,
           prev.rent_index_value, prev.source_snapshot, NOW()
    FROM (
        SELECT DISTINCT ON (area_id) *
        FROM app_area_metrics_daily
        WHERE metric_date < CURRENT_DATE
        ORDER BY area_id, metric_date DESC
    ) prev
    ON CONFLICT (area_id, metric_date) DO NOTHING
    """
)


REFRESH_RENT_INDEX_SQL = text(
    """
    WITH rentcast_med AS (
        SELECT area_id, AVG(rent_median)::numeric(10,2) AS rent
        FROM app_area_rental_market_daily
        WHERE source = 'rentcast'
          AND rent_median IS NOT NULL
          AND metric_date = (
              SELECT MAX(metric_date)
              FROM app_area_rental_market_daily
              WHERE source = 'rentcast'
          )
        GROUP BY area_id
    ),
    zori_latest AS (
        SELECT DISTINCT ON (area_id) area_id, benchmark_rent AS rent
        FROM app_area_rent_benchmark_monthly
        WHERE source = 'zori' AND benchmark_rent IS NOT NULL
        ORDER BY area_id, benchmark_month DESC
    ),
    hud_latest AS (
        SELECT DISTINCT ON (area_id) area_id, benchmark_rent AS rent
        FROM app_area_rent_benchmark_monthly
        WHERE source = 'hud_fmr' AND bedroom_type = '2br'
              AND benchmark_rent IS NOT NULL
        ORDER BY area_id, benchmark_month DESC
    ),
    combined AS (
        SELECT d.area_id,
               COALESCE(r.rent, z.rent, h.rent) AS rent,
               CASE WHEN r.rent IS NOT NULL THEN 'rentcast_market_median'
                    WHEN z.rent IS NOT NULL THEN 'zori_all_bedroom'
                    WHEN h.rent IS NOT NULL THEN 'hud_fmr_2br'
                    END AS src
        FROM app_area_dimension d
        LEFT JOIN rentcast_med r ON r.area_id = d.area_id
        LEFT JOIN zori_latest  z ON z.area_id = d.area_id
        LEFT JOIN hud_latest   h ON h.area_id = d.area_id
    )
    INSERT INTO app_area_metrics_daily
        (area_id, metric_date, rent_index_value, source_snapshot, updated_at)
    SELECT area_id, CURRENT_DATE, rent,
           jsonb_build_object('rent_index_value',
               jsonb_build_object('source', src,
                                  'window_end', CURRENT_DATE,
                                  'derivation', 'priority: rentcast -> zori -> hud_fmr_2br')),
           NOW()
    FROM combined
    WHERE rent IS NOT NULL
    ON CONFLICT (area_id, metric_date) DO UPDATE SET
        rent_index_value = EXCLUDED.rent_index_value,
        source_snapshot  = app_area_metrics_daily.source_snapshot
                          || EXCLUDED.source_snapshot,
        updated_at       = NOW()
    """
)


def refresh_rent_index(session: Session) -> None:
    """Idempotent — carry-forward yesterday's snapshot if today's row is
    absent, then update rent_index_value + its source_snapshot key."""
    session.execute(CARRY_FORWARD_SQL)
    session.execute(REFRESH_RENT_INDEX_SQL)
