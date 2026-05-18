# Table: app_crime_incident_snapshot

Purpose: area-bound crime incident snapshot rows used to break down recent offenses by category.

Allowed columns:

- `incident_id`
- `area_id`
- `occurred_at`
- `occurred_date`
- `occurred_hour`
- `borough`
- `offense_category`
- `offense_description`
- `law_category`
- `latitude`
- `longitude`
- `source`
- `source_record_id`
- `updated_at`

Rules:

- Always filter `area_id = :area_id`.
- For pattern-specific drill-down add `offense_category ILIKE :crime_pattern` with a `%KEYWORD%` value (e.g. `%LARCENY%`, `%ROBBERY%`, `%ASSAULT%`, `%BURGLARY%`).
- Aggregate by `offense_category`:
  - `COUNT(incident_id) AS crime_count`
- Group by `offense_category`.
- Order by `crime_count DESC`.
- `LIMIT 20`.
- For `neighborhood.crime_query` the default detail query does NOT need `latitude` / `longitude` — crime_query produces a category breakdown, not map points. Coordinates may only be selected when the caller explicitly asks for point-level data.
- Do NOT select `geom` or `raw_source`; they are not exposed by the safety MCP SQL whitelist.
- This table is the only acceptable source for `crime_count_by_category` / `crime_count_by_requested_type` results.
