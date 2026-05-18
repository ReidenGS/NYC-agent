# Table: app_area_rental_listing_snapshot

Use for active or recently seen rental listing candidates and budget-fit listing counts.

Allowed columns:

- `listing_id`
- `area_id`
- `snapshot_date`
- `formatted_address`
- `city`
- `state`
- `zip_code`
- `latitude`
- `longitude`
- `property_type`
- `bedroom_type`
- `bedrooms`
- `bathrooms`
- `square_footage`
- `monthly_rent`
- `listing_status`
- `listed_date`
- `last_seen_date`
- `days_on_market`
- `source`
- `updated_at`

Do not select by default:

- `listing_agent_name`
- `listing_agent_phone`
- `raw_source`
- `geom`

Required listing output columns:

- `listing_id`
- `formatted_address`
- `bedroom_type`
- `bedrooms`
- `bathrooms`
- `square_footage`
- `monthly_rent`
- `latitude`
- `longitude`
- `listing_status`
- `listed_date`
- `last_seen_date`
- `days_on_market`
- `source`

Common filters:

- `area_id = :area_id`
- `bedroom_type = :bedroom_type`
- `monthly_rent <= :budget_monthly`
- `listing_status = :active_status`

Common ordering:

- Active listings: `ORDER BY monthly_rent ASC, last_seen_date DESC`
- Fallback listings: `ORDER BY last_seen_date DESC, monthly_rent ASC NULLS LAST`

Do not add a default recent-days filter. Use `LIMIT` to control returned row count.
