# Intent: neighborhood.entertainment_query

Goal: answer entertainment / nightlife / culture POI questions for one canonical NYC area.

Required slots:

- `area_id`
- `area_name` for display only

Domain:

- Every query must use `domain = "entertainment"`.

Required queries:

1. `analysis` query over `app_area_entertainment_category_daily`
   - `expected_result`: `entertainment_count_by_category`
   - group by `category_code`, `category_name`
   - return category counts as `poi_count`
   - order by `poi_count DESC`
   - limit 20

2. `detail` query over `app_map_poi_snapshot`
   - `expected_result`: `sample_entertainment_points`
   - filter `area_id = :area_id`
   - filter `poi_type = :poi_type`, with `poi_type = "entertainment"`
   - select `poi_id`, `category_code`, `category_name`, `name`, `latitude`, `longitude`, `source`
   - order by `category_code ASC, name ASC`
   - limit 20

The detail query must select `latitude` and `longitude`.

`neighborhood_result_type` must be `entertainment_breakdown`.

