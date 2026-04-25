"""Shared aggregation for transit station coverage.

`app_transit_stop_dimension` stores both subway and bus stops. The dashboard
summary column `app_area_metrics_daily.transit_station_count` should therefore
count both modes after `sync_mta_static` and `sync_mta_bus_static` have run.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


REFRESH_TRANSIT_STATION_COUNT_SQL = text(
    """
    WITH counts AS (
        SELECT a.area_id, COUNT(DISTINCT s.stop_id) AS n
        FROM app_area_dimension a
        LEFT JOIN app_transit_stop_dimension s
          ON s.geom IS NOT NULL
         AND s.mode IN ('subway', 'bus')
         AND ST_Contains(a.geom, s.geom)
        GROUP BY a.area_id
    )
    INSERT INTO app_area_metrics_daily
        (area_id, metric_date, transit_station_count, source_snapshot, updated_at)
    SELECT area_id, CURRENT_DATE, n,
           jsonb_build_object('transit_station_count',
               jsonb_build_object('source', 'mta_static_gtfs',
                                  'modes', jsonb_build_array('subway', 'bus'),
                                  'window_end', CURRENT_DATE)),
           NOW()
    FROM counts
    ON CONFLICT (area_id, metric_date) DO UPDATE SET
        transit_station_count = EXCLUDED.transit_station_count,
        source_snapshot       = app_area_metrics_daily.source_snapshot
                                 || EXCLUDED.source_snapshot,
        updated_at            = NOW()
    """
)


def refresh_transit_station_count(session: Session) -> None:
    session.execute(REFRESH_TRANSIT_STATION_COUNT_SQL)
