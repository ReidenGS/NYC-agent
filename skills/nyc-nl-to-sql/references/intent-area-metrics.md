# Intent: area.metrics_query

Goal: return the latest snapshot of all available area-level metrics for one canonical NYC area in a single query.

Required slots:

- `area_id`
- `area_name` for display only

Domain:

- Every query must use `domain = "safety"`.
- Every query must use `mcp_tool = "mcp-safety.execute_readonly_sql"`.

Required queries:

1. `analysis` query over `v_area_metrics_latest`
   - `expected_result`: `area_metrics_latest`
   - filter `area_id = :area_id`
   - select `area_id`, `metric_date`, `crime_count_30d`, `crime_index_100`,
     `entertainment_poi_count`, `convenience_facility_count`, `transit_station_count`,
     `complaint_noise_30d`, `source_snapshot`
   - `LIMIT 1`

Do NOT add a `detail` query — `area.metrics_query` is a single-snapshot intent.

Do NOT query crime incident, POI, listing, or rent tables for this intent; cross-domain aggregates already live in `v_area_metrics_latest`.

`neighborhood_result_type` must be `area_overview`.
