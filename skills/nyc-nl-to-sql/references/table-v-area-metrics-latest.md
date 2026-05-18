# Table (View): v_area_metrics_latest

Purpose: latest cross-domain area metric snapshot. One row per `area_id`.

Allowed columns:

- `area_id`
- `metric_date`
- `crime_count_30d`
- `crime_index_100`
- `entertainment_poi_count`
- `convenience_facility_count`
- `transit_station_count`
- `complaint_noise_30d`
- `source_snapshot`
- `updated_at`

Rules:

- Use this view to retrieve the most recent metrics — do NOT aggregate or group by `metric_date`.
- Always filter `area_id = :area_id`.
- `LIMIT 1` (one row per area).
- For `area.metrics_query` select every metric column listed above.
- For `neighborhood.crime_query` only `area_id`, `metric_date`, `crime_count_30d`, `crime_index_100`, `source_snapshot` are required.
- `source_snapshot` is a JSON object describing upstream data freshness — surface it as-is, do not parse columns out of it.
