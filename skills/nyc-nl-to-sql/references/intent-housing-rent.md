# Intent: housing.rent_query

Goal: answer rent range and budget-fit questions for one canonical NYC area.

Required slots:

- `area_id`
- `area_name` for display only

Domain:

- Every query must use `domain = "housing"`.
- Every query must use `mcp_tool = "mcp-housing.execute_readonly_sql"`.

Supported result types:

- `rent_range`
- `budget_fit`

Unsupported in this phase:

- `rent_comparison`
- `market_freshness`

Rules:

- For rent range with a specific `bedroom_type`, query `app_area_rental_market_daily`.
- For rent range without `bedroom_type`, query overview rows for `studio`, `1br`, and `2br`.
- If market daily has no data, include a fallback query to `app_area_rent_benchmark_monthly`.
- If `budget_monthly` is present, `bedroom_type` is required.
- For `budget_fit`, include a detail query to `app_area_rental_listing_snapshot` for active listings under budget.
- Do not default to a "last 30 days" filter; use latest rows by ordering date fields and limiting row count.

`housing_result_type` must be `rent_range` or `budget_fit`.
