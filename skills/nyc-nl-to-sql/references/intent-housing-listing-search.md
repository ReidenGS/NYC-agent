# Intent: housing.listing_search

Goal: return concrete rental listing candidates for one canonical NYC area.

Required slots:

- `area_id`
- `area_name` for display only
- `bedroom_type`

Domain:

- Every query must use `domain = "housing"`.
- Every query must use `mcp_tool = "mcp-housing.execute_readonly_sql"`.

Required behavior:

- Query `app_area_rental_listing_snapshot`.
- Primary query must prefer `listing_status = :active_status` with `active_status = "active"`.
- If `budget_monthly` is present, filter `monthly_rent <= :budget_monthly`.
- Default listing limit is 5 and maximum is 10.
- Include `latitude` and `longitude` in listing rows for map points.
- Do not default to a "last 30 days" filter; `listing_limit` only controls returned row count.

Fallback behavior:

- If active listings have no data, include a fallback query for recently seen listings.
- Fallback query must not filter `listing_status = active`.
- Fallback results must be treated as stale or unknown inventory by the normalizer.

Do not select:

- `listing_agent_name`
- `listing_agent_phone`
- `raw_source`
- `geom`

`housing_result_type` must be `listing_candidates`.
