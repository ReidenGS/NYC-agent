# Table: app_area_entertainment_category_daily

Purpose: daily area-level entertainment category counts.

Allowed columns:

- `area_id`
- `metric_date`
- `category_code`
- `category_name`
- `poi_count`
- `source`
- `source_key`
- `source_value`
- `source_mapping`
- `updated_at`

Rules:

- Use this table for entertainment category summaries.
- Filter by `area_id = :area_id`.
- Suggested aggregate:
  - `SUM(poi_count) AS poi_count`
  - `MAX(metric_date) AS metric_date`
- Group by `category_code`, `category_name`.
- Order by `poi_count DESC`.
- Limit 20.

