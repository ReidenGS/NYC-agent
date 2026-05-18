# Table: app_area_rent_benchmark_monthly

Use only as fallback when market daily data is unavailable.

Allowed columns:

- `area_id`
- `benchmark_month`
- `bedroom_type`
- `benchmark_rent`
- `benchmark_type`
- `benchmark_geo_type`
- `benchmark_geo_id`
- `data_quality`
- `source`
- `updated_at`

Do not select:

- `source_snapshot`

Common filters:

- `area_id = :area_id`
- `bedroom_type = :bedroom_type`
- `bedroom_type IN ('studio', '1br', '2br')`

Common ordering:

- `ORDER BY benchmark_month DESC`
- Add `LIMIT`.

Benchmark data must not be described as realtime listing inventory.
