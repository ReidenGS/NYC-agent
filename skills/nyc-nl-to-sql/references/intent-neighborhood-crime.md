# Intent: neighborhood.crime_query

Goal: answer area safety / crime questions for one canonical NYC area.

Required slots:

- `area_id`
- `area_name` for display only

Domain:

- Every query must use `domain = "safety"`.
- Every query must use `mcp_tool = "mcp-safety.execute_readonly_sql"`.

Required queries:

1. `analysis` query over `v_area_metrics_latest`
   - `expected_result`: `safety_metrics_latest`
   - filter `area_id = :area_id`
   - select `area_id`, `metric_date`, `crime_count_30d`, `crime_index_100`, `source_snapshot`
   - `LIMIT 1`

2. `detail` query over `app_crime_incident_snapshot`
   - `expected_result`: `crime_count_by_category` (or `crime_count_by_requested_type` when the user asks about a specific crime pattern)
   - filter `area_id = :area_id`
   - if the user asked about a specific crime pattern (e.g. theft, robbery, assault, burglary, larceny), add `offense_category ILIKE :crime_pattern` with the pattern as a `%KEYWORD%` value
   - aggregate `COUNT(incident_id) AS crime_count`, group by `offense_category`
   - order by `crime_count DESC`
   - `LIMIT 20`

The crime detail query must NOT select `latitude` / `longitude`; crime_query does not produce map points.

`neighborhood_result_type` must be `crime_breakdown`.

Unsupported clarifications (return `unsupported_data_request` with `unsupported_reason` instead of SQL):

- street lighting / 街灯 / 路灯
- foot traffic at night / 人多
- homelessness / 流浪汉
- per-building safety / 某栋楼
- subjective neighbor judgement / 邻居
- noisy neighbors / 吵 (noise complaints are reachable elsewhere; subjective noisiness is not)
