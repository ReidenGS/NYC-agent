"""Shared aggregation helpers that touch app_area_metrics_daily.

Per docs/NYC_Agent_Data_Sources_API_SQL.md §6 table 2, the two POI
total columns (entertainment_poi_count, convenience_facility_count)
are declared as "totals derived from category daily tables". Without
this refresh step, v_area_metrics_latest reports 0 for these columns
even after sync_overpass_poi / sync_facilities run.

Both sync_overpass_poi and sync_facilities call refresh_poi_totals()
after their own per-category aggregation. Idempotent and only touches
the two relevant columns plus the matching source_snapshot keys.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


REFRESH_AREA_POI_TOTALS_SQL = text(
    """
    WITH ent AS (
        SELECT area_id, SUM(poi_count)::int AS n
        FROM app_area_entertainment_category_daily
        WHERE metric_date = CURRENT_DATE
        GROUP BY area_id
    ),
    conv AS (
        SELECT area_id, SUM(facility_count)::int AS n
        FROM app_area_convenience_category_daily
        WHERE metric_date = CURRENT_DATE
        GROUP BY area_id
    ),
    combined AS (
        SELECT COALESCE(ent.area_id, conv.area_id) AS area_id,
               COALESCE(ent.n, 0)  AS ent_n,
               COALESCE(conv.n, 0) AS conv_n
        FROM ent FULL OUTER JOIN conv USING (area_id)
    )
    INSERT INTO app_area_metrics_daily
        (area_id, metric_date,
         entertainment_poi_count, convenience_facility_count,
         source_snapshot, updated_at)
    SELECT area_id, CURRENT_DATE, ent_n, conv_n,
           jsonb_build_object(
               'entertainment_poi_count',
               jsonb_build_object('source', 'derived',
                                  'derived_from', 'app_area_entertainment_category_daily',
                                  'window_end', CURRENT_DATE),
               'convenience_facility_count',
               jsonb_build_object('source', 'derived',
                                  'derived_from', 'app_area_convenience_category_daily',
                                  'window_end', CURRENT_DATE)),
           NOW()
    FROM combined
    ON CONFLICT (area_id, metric_date) DO UPDATE SET
        entertainment_poi_count    = EXCLUDED.entertainment_poi_count,
        convenience_facility_count = EXCLUDED.convenience_facility_count,
        source_snapshot            = app_area_metrics_daily.source_snapshot
                                      || EXCLUDED.source_snapshot,
        updated_at                 = NOW()
    """
)


def refresh_poi_totals(session: Session) -> None:
    """Recompute entertainment_poi_count + convenience_facility_count from
    the per-category daily tables. Safe to call multiple times in a run."""
    session.execute(REFRESH_AREA_POI_TOTALS_SQL)
