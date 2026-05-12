-- Make v_area_metrics_latest compose the latest available value per metric.
-- This prevents a newly refreshed single metric from masking older, still
-- valid metrics with schema defaults.
CREATE OR REPLACE VIEW v_area_metrics_latest AS
SELECT
  a.area_id,
  latest.metric_date,
  COALESCE(crime.crime_count_30d, 0) AS crime_count_30d,
  crime.crime_index_100,
  COALESCE(entertainment.entertainment_poi_count, 0) AS entertainment_poi_count,
  COALESCE(convenience.convenience_facility_count, 0) AS convenience_facility_count,
  COALESCE(transit.transit_station_count, 0) AS transit_station_count,
  COALESCE(noise.complaint_noise_30d, 0) AS complaint_noise_30d,
  rent.rent_index_value,
  COALESCE(crime.source_snapshot, '{}'::jsonb)
    || COALESCE(entertainment.source_snapshot, '{}'::jsonb)
    || COALESCE(convenience.source_snapshot, '{}'::jsonb)
    || COALESCE(transit.source_snapshot, '{}'::jsonb)
    || COALESCE(noise.source_snapshot, '{}'::jsonb)
    || COALESCE(rent.source_snapshot, '{}'::jsonb) AS source_snapshot,
  latest.updated_at
FROM app_area_dimension a
LEFT JOIN LATERAL (
  SELECT metric_date, updated_at
  FROM app_area_metrics_daily m
  WHERE m.area_id = a.area_id
  ORDER BY metric_date DESC, updated_at DESC
  LIMIT 1
) latest ON TRUE
LEFT JOIN LATERAL (
  SELECT crime_count_30d, crime_index_100, source_snapshot
  FROM app_area_metrics_daily m
  WHERE m.area_id = a.area_id
    AND m.source_snapshot ? 'crime_count_30d'
  ORDER BY metric_date DESC, updated_at DESC
  LIMIT 1
) crime ON TRUE
LEFT JOIN LATERAL (
  SELECT entertainment_poi_count, source_snapshot
  FROM app_area_metrics_daily m
  WHERE m.area_id = a.area_id
    AND m.source_snapshot ? 'entertainment_poi_count'
  ORDER BY metric_date DESC, updated_at DESC
  LIMIT 1
) entertainment ON TRUE
LEFT JOIN LATERAL (
  SELECT convenience_facility_count, source_snapshot
  FROM app_area_metrics_daily m
  WHERE m.area_id = a.area_id
    AND m.source_snapshot ? 'convenience_facility_count'
  ORDER BY metric_date DESC, updated_at DESC
  LIMIT 1
) convenience ON TRUE
LEFT JOIN LATERAL (
  SELECT transit_station_count, source_snapshot
  FROM app_area_metrics_daily m
  WHERE m.area_id = a.area_id
    AND m.source_snapshot ? 'transit_station_count'
  ORDER BY metric_date DESC, updated_at DESC
  LIMIT 1
) transit ON TRUE
LEFT JOIN LATERAL (
  SELECT complaint_noise_30d, source_snapshot
  FROM app_area_metrics_daily m
  WHERE m.area_id = a.area_id
    AND m.source_snapshot ? 'complaint_noise_30d'
  ORDER BY metric_date DESC, updated_at DESC
  LIMIT 1
) noise ON TRUE
LEFT JOIN LATERAL (
  SELECT rent_index_value, source_snapshot
  FROM app_area_metrics_daily m
  WHERE m.area_id = a.area_id
    AND m.source_snapshot ? 'rent_index_value'
  ORDER BY metric_date DESC, updated_at DESC
  LIMIT 1
) rent ON TRUE
WHERE latest.metric_date IS NOT NULL;
