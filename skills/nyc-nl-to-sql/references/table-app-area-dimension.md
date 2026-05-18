# Table: app_area_dimension

Purpose: canonical NYC area dimension table. Use this only for optional display joins when needed.

Allowed columns:

- `area_id`
- `area_name`
- `borough`
- `area_type`
- `updated_at`

Rules:

- Prefer filtering directly by `area_id = :area_id` on metric / POI tables.
- Do not use `area_name` as the primary filter when `area_id` exists.
- Do not use geometry columns in Phase 1 SQL plans.

