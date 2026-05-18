# Table: app_map_poi_snapshot

Purpose: point-level POI rows used for frontend map markers.

Allowed columns:

- `poi_id`
- `area_id`
- `poi_type`
- `category_code`
- `category_name`
- `name`
- `latitude`
- `longitude`
- `intensity`
- `source`
- `source_key`
- `source_value`
- `source_record_id`
- `source_snapshot`
- `updated_at`

Rules:

- Any map marker / point detail query must select `latitude` and `longitude`.
- Filter by `area_id = :area_id`.
- For convenience, filter `poi_type = :poi_type` with param value `convenience`.
- For entertainment, filter `poi_type = :poi_type` with param value `entertainment`.
- Detail query limit must be <= 20.
- Do not query this table without an `area_id` filter.

