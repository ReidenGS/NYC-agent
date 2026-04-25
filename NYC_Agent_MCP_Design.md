# NYC Agent MCP 详细设计（MVP）

## 1. 目标
MCP 层负责把外部 API、PostgreSQL/PostGIS、Redis 缓存封装成结构化工具，供领域 Agent 调用。

MVP 拆分为 7 个 MCP 服务：
- `mcp-housing`
- `mcp-safety`
- `mcp-amenity`
- `mcp-entertainment`
- `mcp-transit`
- `mcp-weather`
- `mcp-profile`

实现方式：
- 使用 `python_a2a.mcp.FastMCP`
- 每个 MCP 是独立 Docker 服务
- 每个 MCP 只接收结构化参数，不接收自然语言
- 每个 MCP 可以读写自己领域内的数据表
- 静态/准静态数据优先读 PostgreSQL/PostGIS
- 实时/强用户相关数据允许按需调用外部 API，并写 Redis/PostgreSQL
- `mcp-housing`、`mcp-safety`、`mcp-amenity`、`mcp-entertainment` 支持受控只读 SQL 执行
- MCP 不生成 SQL；SQL 由对应 Domain Agent 基于动态注入 schema 生成
- MCP 必须先校验 SQL，再用只读数据库账号执行

## 2. 统一 MCP Response Envelope
所有 MCP tool 使用统一 envelope，`data` 内部按工具自定义。

```json
{
  "status": "success",
  "tool": "get_crime_summary",
  "data": {},
  "source": [
    {
      "name": "qgea-i56i",
      "type": "nyc_open_data",
      "timestamp": "2026-04-24T12:00:00-04:00"
    }
  ],
  "timestamp": "2026-04-24T12:00:00-04:00",
  "confidence": 0.9,
  "data_quality": "reference",
  "error": null
}
```

## 3. MCP 错误码
MCP 使用独立错误码集合，但必须映射回 A2A 错误码。

MCP 错误码：
- `INVALID_ARGUMENT`
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`
- `RATE_LIMITED`
- `DB_ERROR`
- `CACHE_ERROR`
- `UNSUPPORTED_TOOL`
- `SQL_VALIDATION_FAILED`
- `INTERNAL_ERROR`
- `OTHER`

映射：
- `MISSING_ARGUMENT` -> A2A `MISSING_REQUIRED_SLOT`
- `EXTERNAL_API_TIMEOUT` -> A2A `MCP_TIMEOUT`
- `EXTERNAL_API_ERROR` -> A2A `MCP_BAD_RESPONSE`
- `DB_ERROR` -> A2A `INTERNAL_ERROR`
- `CACHE_ERROR` -> A2A `INTERNAL_ERROR`
- `SQL_VALIDATION_FAILED` -> A2A `SQL_VALIDATION_FAILED`
- `OTHER` -> A2A `OTHER`

## 4. HTTP 管理接口
每个 MCP 服务额外提供 HTTP 管理接口：
- `GET /health`
- `GET /tools`
- `GET /tools/{tool_name}/schema`

用途：
- Docker Compose 健康检查
- 本地调试
- Demo 展示工具能力
- Orchestrator 启动时做工具发现/校验

## 4A. 受控只读 SQL 执行
`housing-agent` 和 `neighborhood-agent` 可以生成只读 SQL，但 MCP 是最终安全边界。

适用 MCP：
- `mcp-housing`
- `mcp-safety`
- `mcp-amenity`
- `mcp-entertainment`

不适用 MCP：
- `mcp-transit`：实时通勤走固定工具和外部 API
- `mcp-weather`：天气走固定工具和 NWS API
- `mcp-profile`：会话状态走固定读写接口

通用工具：`execute_readonly_sql`

输入：
```json
{
  "task_type": "neighborhood.crime_query",
  "purpose": "analysis",
  "sql": "SELECT offense_category, COUNT(*) AS crime_count FROM app_crime_incident_snapshot WHERE area_id = :area_id GROUP BY offense_category LIMIT 20",
  "params": {
    "area_id": "QN0101"
  },
  "allowed_tables": ["app_crime_incident_snapshot", "app_area_dimension"],
  "allowed_columns": {
    "app_crime_incident_snapshot": ["area_id", "offense_category", "occurred_at", "latitude", "longitude"],
    "app_area_dimension": ["area_id", "area_name", "borough", "geom"]
  }
}
```

输出 `data`：
```json
{
  "rows": [
    {
      "offense_category": "PETIT LARCENY",
      "crime_count": 18
    }
  ],
  "row_count": 1,
  "purpose": "analysis",
  "source_tables": ["app_crime_incident_snapshot"],
  "execution_ms": 120
}
```

无数据输出：
```json
{
  "status": "no_data",
  "tool": "execute_readonly_sql",
  "data": [],
  "message": "Query executed successfully, but no rows were found.",
  "source_tables": ["app_crime_incident_snapshot"],
  "error": null
}
```

SQL Validator 规则：
- 只允许 `SELECT`
- 禁止 `SELECT *`
- 禁止多语句
- 禁止 DDL/DML
- 只允许访问当前 task_type 白名单表
- 只允许访问白名单字段
- 禁止访问 session/profile/trace/debug 敏感表
- 必须带 `LIMIT`
- 默认 `LIMIT <= 50`
- 用户输入必须参数化
- 数据库连接使用只读账号
- 设置 `statement_timeout`，建议 `3s`

允许的 SQL 能力：
- 白名单表之间 `JOIN`
- `COUNT / AVG / MIN / MAX / SUM`
- `GROUP BY`
- `ORDER BY`
- 有限明细查询
- 白名单 PostGIS 函数：`ST_Within`、`ST_DWithin`、`ST_Intersects`

错误码：
- `SQL_VALIDATION_FAILED`
- `DATA_NOT_FOUND`
- `DB_ERROR`
- `OTHER`

## 5. mcp-housing
负责房源、租金区间、租金基准、候选房源。

主要执行模式：
- `housing-agent` 基于租房领域 schema 生成只读 SQL
- `mcp-housing.execute_readonly_sql` 校验并执行 SQL
- 以下固定工具可作为默认查询、fallback 或非 LLM 路径保留

### 5.1 `get_area_rental_market`
用途：查询某区域按户型聚合的租金区间和房源数量。

输入：
```json
{
  "area_id": "BK0101",
  "bedroom_type": "1br",
  "metric_date": "2026-04-24"
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "bedroom_type": "1br",
  "rent_min": 2800,
  "rent_median": 3300,
  "rent_max": 4200,
  "listing_count": 38,
  "data_quality": "realtime"
}
```

数据来源：
- SQL：`app_area_rental_market_daily`
- 上游：`app_area_rental_listing_snapshot` 聚合，或 RentCast `/markets`、ZORI、HUD FMR

错误码：
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `DB_ERROR`

### 5.2 `search_rental_listings`
用途：查询某区域候选房源，用于执行包和看房清单。

输入：
```json
{
  "area_id": "BK0101",
  "budget_min": 2500,
  "budget_max": 3800,
  "bedroom_type": "1br",
  "limit": 10,
  "refresh": false
}
```

输出 `data`：
```json
{
  "listings": [
    {
      "listing_id": "rentcast_123",
      "formatted_address": "123 Example St, Brooklyn, NY",
      "monthly_rent": 3200,
      "bedroom_type": "1br",
      "bathrooms": 1,
      "square_footage": 720,
      "listing_status": "active",
      "listed_date": "2026-04-20T00:00:00-04:00",
      "contact_available": true
    }
  ]
}
```

数据来源：
- SQL：`app_area_rental_listing_snapshot`
- 外部 API：RentCast `/listings/rental/long-term`（当 `refresh=true` 或缓存过期）
- API key：`RENTCAST_API_KEY=`

错误码：
- `MISSING_ARGUMENT`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`
- `RATE_LIMITED`
- `DB_ERROR`

### 5.3 `get_rent_benchmark`
用途：查询市场租金基准，判断当前区域租金高低。

输入：
```json
{
  "area_id": "BK0101",
  "bedroom_type": "1br",
  "benchmark_type": "zori"
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "bedroom_type": "1br",
  "benchmark_rent": 3150,
  "benchmark_type": "zori",
  "benchmark_month": "2026-04-01"
}
```

数据来源：
- SQL：`app_area_rent_benchmark_monthly`
- 外部来源：RentCast `/markets`、ZORI CSV、HUD FMR API
- API key：`RENTCAST_API_KEY=`、`HUD_USER_API_TOKEN=`（ZORI 不需要 key）

错误码：
- `DATA_NOT_FOUND`
- `DB_ERROR`
- `EXTERNAL_API_ERROR`

## 6. mcp-safety
负责犯罪数量、安全指标、安全地图图层。

主要执行模式：
- `neighborhood-agent` 基于安全领域 schema 生成只读 SQL
- `mcp-safety.execute_readonly_sql` 校验并执行 SQL
- 以下固定工具可作为默认查询、fallback 或非 LLM 路径保留

### 6.1 `get_crime_summary`
用途：查询目标区域近 N 天犯罪数量和安全指数。

输入：
```json
{
  "area_id": "BK0101",
  "window_days": 30
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "crime_count": 42,
  "crime_index_100": 67.5,
  "window_days": 30
}
```

数据来源：
- SQL：`app_area_metrics_daily`
- 上游 API：NYC Open Data `qgea-i56i`
- API token：`SOCRATA_APP_TOKEN=`（可选）

错误码：
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `DB_ERROR`

### 6.2 `get_safety_map_layer`
用途：返回安全图层数据，用于地图热力/区域变色。

输入：
```json
{
  "area_id": "BK0101",
  "layer_type": "crime_heat"
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "layer_type": "crime_heat",
  "features": []
}
```

数据来源：
- SQL：`app_area_dimension.geom`
- SQL：`app_area_metrics_daily.crime_index_100`

错误码：
- `DATA_NOT_FOUND`
- `DB_ERROR`

## 7. mcp-amenity
负责便利设施分类，如超市、公园、图书馆、学校、药店、健身房。

主要执行模式：
- `neighborhood-agent` 基于便利设施领域 schema 生成只读 SQL
- `mcp-amenity.execute_readonly_sql` 校验并执行 SQL
- 以下固定工具可作为默认查询、fallback 或非 LLM 路径保留

### 7.1 `get_convenience_categories`
用途：查询某区域便利设施分类数量。

输入：
```json
{
  "area_id": "BK0101",
  "metric_date": "2026-04-24"
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "categories": [
    {
      "category_code": "supermarket",
      "category_name": "超市",
      "facility_count": 8,
      "source_key": "tags.shop",
      "source_value": "supermarket"
    }
  ]
}
```

数据来源：
- SQL：`app_area_convenience_category_daily`
- 上游 API：Facilities `67g2-p84d`、Overpass API
- API token：`SOCRATA_APP_TOKEN=`（Facilities 可选）、Overpass 不需要 key

错误码：
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `DB_ERROR`
- `EXTERNAL_API_ERROR`

### 7.2 `get_convenience_map_layer`
用途：返回便利设施地图点位或分类图层。

输入：
```json
{
  "area_id": "BK0101",
  "category_code": "supermarket"
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "category_code": "supermarket",
  "points": []
}
```

数据来源：
- SQL：`app_area_convenience_category_daily`
- 可选外部实时点位：Overpass API

错误码：
- `DATA_NOT_FOUND`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`

## 8. mcp-entertainment
负责娱乐设施分类，如酒吧、电影院、夜店、剧院、餐厅。

主要执行模式：
- `neighborhood-agent` 基于娱乐设施领域 schema 生成只读 SQL
- `mcp-entertainment.execute_readonly_sql` 校验并执行 SQL
- 以下固定工具可作为默认查询、fallback 或非 LLM 路径保留

### 8.1 `get_entertainment_categories`
用途：查询某区域娱乐设施分类数量。

输入：
```json
{
  "area_id": "BK0101",
  "metric_date": "2026-04-24"
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "categories": [
    {
      "category_code": "bar",
      "category_name": "酒吧",
      "poi_count": 12,
      "source_key": "tags.amenity",
      "source_value": "bar"
    }
  ]
}
```

数据来源：
- SQL：`app_area_entertainment_category_daily`
- 上游 API：Overpass API
- API key：不需要

错误码：
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`
- `DB_ERROR`

### 8.2 `get_entertainment_map_layer`
用途：返回娱乐设施点位图层，用于地图蓝点展示。

输入：
```json
{
  "area_id": "BK0101",
  "category_code": "bar"
}
```

输出 `data`：
```json
{
  "area_id": "BK0101",
  "category_code": "bar",
  "points": []
}
```

数据来源：
- SQL：`app_area_entertainment_category_daily`
- 可选外部实时点位：Overpass API

错误码：
- `DATA_NOT_FOUND`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`

## 9. mcp-transit
负责静态通勤、实时地铁/公交、下一班车、步行接驳估算。

### 9.1 `find_nearby_stops`
用途：根据地址、坐标或区域找到附近合理站点。

输入：
```json
{
  "origin": {
    "area_id": "BK0101",
    "lat": 40.72,
    "lon": -73.95
  },
  "mode": "subway",
  "limit": 3
}
```

输出 `data`：
```json
{
  "stops": [
    {
      "stop_id": "G22",
      "stop_name": "Greenpoint Av",
      "mode": "subway",
      "walking_minutes": 7
    }
  ]
}
```

数据来源：
- SQL：`app_transit_stop_dimension`
- PostGIS 距离计算

错误码：
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `DB_ERROR`

### 9.2 `get_next_departures`
用途：查询某站某线路下一班/下两班车。

输入：
```json
{
  "stop_id": "G22",
  "route_id": "G",
  "direction_id": "northbound",
  "mode": "subway",
  "limit": 2
}
```

输出 `data`：
```json
{
  "stop_id": "G22",
  "route_id": "G",
  "departures": [
    {
      "departure_time": "2026-04-24T12:10:00-04:00",
      "minutes_until_departure": 6,
      "delay_seconds": 0
    }
  ]
}
```

数据来源：
- SQL/Redis：`app_transit_realtime_prediction`、`app_transit_trip_result_cache`
- 外部 API：MTA GTFS-RT、MTA Bus Time
- API key：`MTA_BUS_TIME_API_KEY=`（公交），地铁通常不需要 key

错误码：
- `MISSING_ARGUMENT`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`
- `RATE_LIMITED`
- `CACHE_ERROR`
- `DATA_NOT_FOUND`

### 9.3 `get_realtime_commute`
用途：返回从某地到某地的实时通勤结果。

输入：
```json
{
  "origin": "Greenpoint",
  "destination": "NYU",
  "mode": "subway"
}
```

输出 `data`：
```json
{
  "mode": "subway",
  "origin_stop": "Greenpoint Av",
  "route_id": "G",
  "walking_to_stop_minutes": 7,
  "waiting_minutes": 6,
  "in_vehicle_minutes": 22,
  "total_minutes": 38,
  "recommended_leave_at": "2026-04-24T12:03:00-04:00",
  "estimated_arrival_at": "2026-04-24T12:41:00-04:00",
  "realtime_used": true,
  "fallback_used": false
}
```

数据来源：
- SQL/Redis：`app_transit_stop_dimension`、`app_transit_realtime_prediction`、`app_transit_trip_result_cache`
- 外部 API：MTA GTFS-RT、MTA Bus Time

错误码：
- `MISSING_ARGUMENT`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`
- `DATA_NOT_FOUND`

## 10. mcp-weather
负责目标区域天气、小时级天气预报、指定时刻天气查询。

`mcp-weather` 不支持 SQL generation，也不长期写业务表。它只通过固定工具访问 NWS API，并使用 Redis 缓存结果。

### 10.1 `get_area_weather_summary`
用途：查询目标区域当前到未来数小时天气，用于默认天气卡片和用户当前天气问题。

输入：
```json
{
  "area_id": "QN0101",
  "hours": 6,
  "timezone": "America/New_York"
}
```

输出 `data`：
```json
{
  "area_id": "QN0101",
  "area_name": "Astoria",
  "location": {
    "latitude": 40.7644,
    "longitude": -73.9235
  },
  "periods": [
    {
      "start_time": "2026-04-25T13:00:00-04:00",
      "end_time": "2026-04-25T14:00:00-04:00",
      "temperature": 62,
      "temperature_unit": "F",
      "precipitation_probability": 20,
      "wind_speed": "8 mph",
      "wind_direction": "NW",
      "short_forecast": "Mostly Sunny",
      "is_daytime": true
    }
  ]
}
```

数据来源：
- SQL：`app_area_dimension` 读取区域中心点或几何边界
- 外部 API：NWS `GET /points/{lat},{lon}`、`forecastHourly`
- Redis：`nws:points:{lat}:{lon}` 缓存 7 天，`nws:hourly:{grid}` 缓存 30-60 分钟
- API key：不需要
- 必填配置：`NWS_USER_AGENT=`

错误码：
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `EXTERNAL_API_TIMEOUT`
- `EXTERNAL_API_ERROR`
- `RATE_LIMITED`
- `CACHE_ERROR`

### 10.2 `get_weather_at_time`
用途：查询目标区域指定时刻附近的小时级天气预报。

输入：
```json
{
  "area_id": "QN0101",
  "target_time": "2026-04-25T20:00:00-04:00",
  "timezone": "America/New_York"
}
```

输出 `data`：
```json
{
  "area_id": "QN0101",
  "target_time": "2026-04-25T20:00:00-04:00",
  "matched_period": {
    "start_time": "2026-04-25T20:00:00-04:00",
    "end_time": "2026-04-25T21:00:00-04:00",
    "temperature": 55,
    "temperature_unit": "F",
    "precipitation_probability": 35,
    "wind_speed": "10 mph",
    "wind_direction": "N",
    "short_forecast": "Chance Showers",
    "detailed_forecast": "A chance of showers before 11pm."
  }
}
```

匹配规则：
- 优先匹配 `start_time <= target_time < end_time`
- 如果无完全匹配，选择时间距离最近的 forecast period
- 如果 `target_time` 超出 NWS hourly forecast 范围，返回 `DATA_NOT_FOUND`

## 11. mcp-profile
负责 session、槽位、权重、推荐结果、A2A trace。

### 11.1 `get_session_profile`
用途：读取用户当前会话的目标区域、槽位、权重状态。

输入：
```json
{
  "session_id": "sess_123"
}
```

输出 `data`：
```json
{
  "session_id": "sess_123",
  "target_area_id": "BK0101",
  "weights": {
    "safety": 0.3,
    "commute": 0.3,
    "rent": 0.2,
    "convenience": 0.1,
    "entertainment": 0.1
  },
  "missing_required": []
}
```

数据来源：
- SQL：`app_session_profile`

错误码：
- `MISSING_ARGUMENT`
- `DATA_NOT_FOUND`
- `DB_ERROR`

### 11.2 `update_session_profile`
用途：更新目标区域、槽位、预算、目的地等会话字段。

输入：
```json
{
  "session_id": "sess_123",
  "patch": {
    "target_area_id": "BK0101",
    "target_destination": "NYU"
  }
}
```

输出 `data`：
```json
{
  "updated": true
}
```

数据来源：
- SQL：`app_session_profile`

错误码：
- `MISSING_ARGUMENT`
- `INVALID_ARGUMENT`
- `DB_ERROR`

### 11.3 `update_weights`
用途：更新用户权重。

输入：
```json
{
  "session_id": "sess_123",
  "weights": {
    "safety": 0.4,
    "commute": 0.3,
    "rent": 0.2,
    "convenience": 0.05,
    "entertainment": 0.05
  },
  "weights_source": "user"
}
```

输出 `data`：
```json
{
  "updated": true,
  "normalized": true
}
```

数据来源：
- SQL：`app_session_profile`

错误码：
- `INVALID_ARGUMENT`
- `DB_ERROR`

### 11.4 `save_recommendation`
用途：保存推荐结果。

输入：
```json
{
  "session_id": "sess_123",
  "recommendations": []
}
```

输出 `data`：
```json
{
  "saved": true
}
```

数据来源：
- SQL：`app_session_recommendation`

错误码：
- `MISSING_ARGUMENT`
- `DB_ERROR`

### 11.5 `save_a2a_trace`
用途：保存 A2A 调用链日志。

输入：
```json
{
  "trace_id": "trace_123",
  "message_id": "msg_123",
  "source_agent": "orchestrator-agent",
  "target_agent": "housing-agent",
  "status": "succeeded"
}
```

输出 `data`：
```json
{
  "saved": true
}
```

数据来源：
- SQL：`app_a2a_trace_log`

错误码：
- `MISSING_ARGUMENT`
- `DB_ERROR`
