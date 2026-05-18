# Table: app_area_convenience_category_daily

Purpose: daily area-level convenience / amenity category counts.

Allowed columns:

- `area_id`
- `metric_date`
- `category_code`
- `category_name`
- `facility_count`
- `source`
- `source_key`
- `source_value`
- `source_mapping`
- `updated_at`

Rules:

- Use this table for convenience category summaries.
- Filter by `area_id = :area_id`.
- Return count as `poi_count` for compatibility with downstream summarization.
- Suggested aggregate:
  - `SUM(facility_count) AS poi_count`
  - `MAX(metric_date) AS metric_date`
- Group by `category_code`, `category_name`.
- Order by `poi_count DESC`.
- Limit 20.

