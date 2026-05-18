# Table: app_area_rental_market_daily

Use for housing rent market summaries by area and bedroom type.

Allowed columns:

- `area_id`
- `metric_date`
- `bedroom_type`
- `listing_type`
- `rent_min`
- `rent_median`
- `rent_max`
- `listing_count`
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

- `ORDER BY metric_date DESC`
- Add `LIMIT`.
