# NYC Agent API 与 Schema 契约（MVP）

## 1. 目标
本文件定义前后端 API 契约和后端内部 Agent/MCP schema 契约。

用途：
- 前端根据本文件设计页面、状态管理和 TypeScript types
- 后端根据本文件实现 FastAPI Pydantic models
- Agent 服务根据本文件对齐 A2A / Domain Agent / MCP 消息格式
- Debug panel 根据本文件展示 trace、状态和错误

原则：
- 前端只依赖 API Gateway 契约
- 后端内部服务依赖 A2A / Domain / MCP 契约
- 所有接口使用统一 envelope
- 用户可见回答不默认展示数值置信度
- `trace_id` 贯穿 Gateway、Orchestrator、Domain Agent、MCP、data-sync
- API Key、完整 Prompt、未脱敏 SQL 参数不返回前端

## 2. 通用约定

### 2.1 ID 命名

| 字段 | 格式示例 | 说明 |
|---|---|---|
| `session_id` | `sess_01H...` | 匿名会话ID |
| `trace_id` | `trace_01H...` | 单次请求链路ID |
| `message_id` | `msg_01H...` | A2A 消息ID |
| `task_id` | `task_01H...` | 异步任务ID |
| `area_id` | `QN0101` | NTA 区域ID |
| `map_layer_id` | `map_01H...` | 地图图层缓存ID |
| `display_result_id` | `disp_01H...` | 展示结果缓存ID |
| `job_id` | `sync_01H...` | 数据同步任务ID |

### 2.2 时间格式
所有 API 时间使用 ISO 8601 字符串。

示例：

```text
2026-04-25T12:30:00-04:00
```

数据库内部可以使用 `TIMESTAMP`，API 输出必须序列化为 ISO 8601。

### 2.3 坐标格式

```json
{
  "latitude": 40.7644,
  "longitude": -73.9235
}
```

规则：
- `latitude`: `-90` 到 `90`
- `longitude`: `-180` 到 `180`
- API 返回给前端时保留经纬度
- PostGIS `geom` 不直接返回前端，地图使用 GeoJSON 或经纬度

## 3. 通用 Response Envelope

所有 API Gateway 接口返回统一 envelope。

成功：

```json
{
  "success": true,
  "trace_id": "trace_01H...",
  "session_id": "sess_01H...",
  "data": {},
  "error": null
}
```

失败：

```json
{
  "success": false,
  "trace_id": "trace_01H...",
  "session_id": "sess_01H...",
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "message is required",
    "retryable": true,
    "details": {}
  }
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `success` | boolean | 是 | 请求是否成功 |
| `trace_id` | string | 是 | 链路追踪ID |
| `session_id` | string/null | 否 | 会话ID；`POST /sessions` 前可为空 |
| `data` | object/null | 是 | 成功数据 |
| `error` | object/null | 是 | 错误对象 |

## 4. 通用 Error Schema

```json
{
  "code": "VALIDATION_ERROR",
  "message": "message is required",
  "retryable": true,
  "details": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | string | 是 | 错误码 |
| `message` | string | 是 | 用户/开发者可读错误摘要 |
| `retryable` | boolean | 是 | 是否可重试 |
| `details` | object | 是 | 结构化错误详情 |

API Gateway 错误码：
- `VALIDATION_ERROR`
- `RATE_LIMITED`
- `DEPENDENCY_UNAVAILABLE`
- `ORCHESTRATOR_TIMEOUT`
- `AGENT_ERROR`
- `INTERNAL_ERROR`

A2A / Agent 错误码：
- `MISSING_REQUIRED_SLOT`
- `LOW_CONFIDENCE_SLOT`
- `MCP_TIMEOUT`
- `MCP_BAD_RESPONSE`
- `SQL_VALIDATION_FAILED`
- `DATA_NOT_FOUND`
- `RATE_LIMITED`
- `LLM_PARSE_FAILED`
- `UNSUPPORTED_INTENT`
- `INTERNAL_ERROR`
- `OTHER`

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

## 5. 通用 Enum

### 5.1 `next_action`

允许值：
- `ask_follow_up`
- `confirm_slots`
- `update_profile`
- `call_agent`
- `call_mcp`
- `respond_final`
- `run_async_task`
- `fallback`
- `error`

### 5.2 `message_type`

允许值：
- `answer`
- `follow_up`
- `confirmation`
- `no_data`
- `unsupported`
- `error`

### 5.3 `data_quality`

允许值：
- `realtime`
- `reference`
- `estimated`
- `benchmark`
- `cached`
- `no_data`
- `unknown`

### 5.4 `domain`

允许值：
- `housing`
- `neighborhood`
- `transit`
- `weather`
- `profile`
- `recommendation`
- `system`
- `unknown`

### 5.5 `task_type`

MVP 允许值：
- `housing.rent_query`
- `housing.listing_search`
- `neighborhood.crime_query`
- `neighborhood.entertainment_query`
- `neighborhood.convenience_query`
- `area.metrics_query`
- `profile.update_weights`
- `transit.next_departure`
- `transit.commute_time`
- `transit.realtime_commute`
- `weather.current_query`
- `weather.forecast_query`
- `recommendation.generate`
- `system.capability_question`
- `system.identity_question`
- `unknown`

### 5.6 `transport_mode`

允许值：
- `subway`
- `bus`
- `either`
- `walk`
- `unknown`

### 5.7 `map_layer_type`

允许值：
- `choropleth`
- `heatmap`
- `marker`
- `cluster`
- `route`

## 6. 通用业务 Schema

### 6.1 Slot Value

```json
{
  "value": "Astoria",
  "source": "user_explicit",
  "confidence": 0.95,
  "updated_at": "2026-04-25T12:30:00-04:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `value` | any | 是 | 槽位值 |
| `source` | string | 是 | `user_explicit/session_memory/agent_inferred/default/rule_fallback` |
| `confidence` | number | 是 | 内部判断用，不默认展示给用户 |
| `updated_at` | string | 否 | 更新时间 |

### 6.2 Weights

```json
{
  "safety": 0.3,
  "commute": 0.3,
  "rent": 0.2,
  "convenience": 0.1,
  "entertainment": 0.1
}
```

规则：
- 每个值范围 `0` 到 `1`
- 总和建议归一化为 `1`
- 用户修改后必须回显

### 6.3 Profile Snapshot

```json
{
  "session_id": "sess_01H...",
  "target_area": {
    "area_id": "QN0101",
    "area_name": "Astoria",
    "source": "user_explicit",
    "confidence": 0.95
  },
  "budget": {
    "min": null,
    "max": 2500,
    "currency": "USD",
    "source": "user_explicit"
  },
  "target_destination": {
    "value": "NYU",
    "source": "user_explicit",
    "confidence": 0.9
  },
  "max_commute_minutes": {
    "value": 35,
    "source": "user_explicit",
    "confidence": 0.9
  },
  "weights": {
    "safety": 0.45,
    "commute": 0.25,
    "rent": 0.15,
    "convenience": 0.1,
    "entertainment": 0.05
  },
  "weights_source": "user_explicit",
  "preferences": ["安静", "少换乘"],
  "missing_required_fields": [],
  "conversation_summary": "用户正在评估 Astoria，安全优先，预算约 2500。",
  "updated_at": "2026-04-25T12:30:00-04:00"
}
```

前端用途：
- 状态面板
- 权重面板
- 用户确认 Agent 是否理解正确
- 后续推荐页面的输入状态

## 7. API Gateway 外部接口契约

## 7.1 `POST /sessions`

用途：创建匿名 session。

Request：

```json
{
  "client_timezone": "America/New_York",
  "client_locale": "zh-CN"
}
```

字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `client_timezone` | string | 否 | 前端时区 |
| `client_locale` | string | 否 | 前端语言 |

Response `data`：

```json
{
  "session_id": "sess_01H...",
  "profile_snapshot": {
    "session_id": "sess_01H...",
    "target_area": null,
    "weights": {
      "safety": 0.3,
      "commute": 0.3,
      "rent": 0.2,
      "convenience": 0.1,
      "entertainment": 0.1
    },
    "missing_required_fields": ["target_area"],
    "conversation_summary": "",
    "updated_at": "2026-04-25T12:30:00-04:00"
  }
}
```

## 7.2 `POST /chat`

用途：自然语言主入口。

Request：

```json
{
  "session_id": "sess_01H...",
  "message": "我想看 Astoria，安全最重要",
  "debug": false,
  "client_context": {
    "active_area_id": null,
    "active_view": "chat"
  }
}
```

字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | string | 是 | 会话ID |
| `message` | string | 是 | 用户自然语言输入，建议 1-2000 字符 |
| `debug` | boolean | 否 | 是否返回简短 trace |
| `client_context` | object | 否 | 前端当前视图状态 |

Response `data`：

```json
{
  "message_type": "answer",
  "answer": "Astoria 的安全情况整体属于中等偏好。我按你刚才说的“安全最重要”更新了权重，后续比较会优先考虑安全。",
  "next_action": "respond_final",
  "profile_snapshot": {},
  "cards": [
    {
      "card_type": "metric",
      "title": "安全概况",
      "subtitle": "近 30 天公开犯罪记录",
      "metrics": [
        {
          "label": "犯罪记录数",
          "value": 42,
          "unit": "起"
        }
      ],
      "data_quality": "reference",
      "source": [
        {
          "name": "NYPD Complaint Data",
          "updated_at": "2026-04-25T00:00:00-04:00"
        }
      ]
    }
  ],
  "display_refs": {
    "map_layer_ids": ["map_01H..."],
    "display_result_ids": []
  },
  "sources": [
    {
      "name": "NYPD Complaint Data",
      "type": "nyc_open_data",
      "updated_at": "2026-04-25T00:00:00-04:00"
    }
  ],
  "data_quality": "reference",
  "debug": null
}
```

缺槽 Response `data`：

```json
{
  "message_type": "follow_up",
  "answer": "你想了解纽约哪个区域？例如 Astoria、LIC、Williamsburg。",
  "next_action": "ask_follow_up",
  "profile_snapshot": {
    "target_area": null,
    "missing_required_fields": ["target_area"]
  },
  "missing_slots": ["target_area"],
  "cards": [],
  "display_refs": {},
  "sources": [],
  "data_quality": "unknown",
  "debug": null
}
```

`debug=true` 时 Response `data.debug`：

```json
{
  "trace_summary": [
    {
      "step": "orchestrator.intent_detected",
      "service": "orchestrator-agent",
      "status": "success",
      "latency_ms": 120
    },
    {
      "step": "neighborhood.crime_query",
      "service": "neighborhood-agent",
      "mcp": "mcp-safety",
      "status": "success",
      "latency_ms": 420
    }
  ]
}
```

安全规则：
- 不返回完整 Prompt
- 不返回 API Key
- 不返回未脱敏 SQL 参数
- 不默认展示数值置信度

## 7.3 `GET /sessions/{session_id}/profile`

用途：前端状态面板初始化/刷新。

Response `data`：

```json
{
  "profile_snapshot": {}
}
```

其中 `profile_snapshot` 使用第 6.3 节 schema。

## 7.4 `PATCH /sessions/{session_id}/profile`

用途：前端手动修改权重、预算、目标区域等。

Request：

```json
{
  "target_area_id": "QN0101",
  "budget": {
    "min": null,
    "max": 2500
  },
  "weights": {
    "safety": 0.45,
    "commute": 0.25,
    "rent": 0.15,
    "convenience": 0.1,
    "entertainment": 0.05
  },
  "preferences": ["安静", "少换乘"]
}
```

Response `data`：

```json
{
  "profile_snapshot": {}
}
```

规则：
- Gateway 只做类型和范围校验
- profile-agent 负责合并和冲突处理
- 更新后返回完整 `profile_snapshot`

## 7.5 `GET /areas/{area_id}/metrics`

用途：区域指标卡片。

Query params：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `session_id` | string | 是 | 无 | 用于 trace 和个性化权重 |
| `metric_date` | string | 否 | latest | 指标日期 |

Response `data`：

```json
{
  "area": {
    "area_id": "QN0101",
    "area_name": "Astoria",
    "borough": "Queens"
  },
  "metrics": {
    "crime_count_30d": 42,
    "crime_index_100": 63.5,
    "entertainment_poi_count": 86,
    "convenience_facility_count": 54,
    "transit_station_count": 7,
    "complaint_noise_30d": 19,
    "rent_index_value": 2850
  },
  "metric_cards": [
    {
      "card_type": "metric",
      "title": "安全",
      "score_label": "中等",
      "metrics": [
        {
          "label": "近 30 天犯罪记录",
          "value": 42,
          "unit": "起"
        }
      ]
    }
  ],
  "source_snapshot": {},
  "updated_at": "2026-04-25T00:00:00-04:00"
}
```

## 7.6 `GET /areas/{area_id}/map-layers`

用途：前端地图图层。

Query params：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `session_id` | string | 是 | 无 | 会话ID |
| `layer_types` | string | 否 | `choropleth,marker` | 逗号分隔 |
| `metric_names` | string | 否 | `crime_index,entertainment,convenience` | 逗号分隔 |

Response `data`：

```json
{
  "area_id": "QN0101",
  "layers": [
    {
      "layer_id": "map_01H...",
      "layer_type": "choropleth",
      "metric_name": "crime_index",
      "geojson": {
        "type": "FeatureCollection",
        "features": []
      },
      "style_hint": {
        "color_scale": "red",
        "value_field": "crime_index_100"
      },
      "data_quality": "cached",
      "updated_at": "2026-04-25T00:00:00-04:00",
      "expires_at": null
    }
  ]
}
```

规则：
- seed 区域优先返回预生成图层
- 非 seed 区域可按需生成并缓存
- 图层失败不影响 `/chat` 文本回答

## 7.7 `POST /transit/realtime`

用途：实时通勤卡片或用户主动查询。

Request：

```json
{
  "session_id": "sess_01H...",
  "origin": "Astoria",
  "destination": "NYU",
  "mode": "subway",
  "route_id": null,
  "station_or_origin": null,
  "departure_time": "now"
}
```

Response `data`：

```json
{
  "mode": "subway",
  "origin": {
    "label": "Astoria",
    "stop_id": "R01",
    "stop_name": "Astoria-Ditmars Blvd"
  },
  "destination": {
    "label": "NYU",
    "stop_id": null,
    "stop_name": null
  },
  "route": {
    "route_id": "N",
    "route_name": "N train"
  },
  "next_departures": [
    {
      "departure_time": "2026-04-25T12:38:00-04:00",
      "arrival_time": null,
      "delay_seconds": 0,
      "realtime": true
    }
  ],
  "walking_to_stop_minutes": 8,
  "waiting_minutes": 5,
  "in_vehicle_minutes": 24,
  "total_minutes": 37,
  "recommended_leave_at": "2026-04-25T12:30:00-04:00",
  "estimated_arrival_at": "2026-04-25T13:07:00-04:00",
  "realtime_used": true,
  "fallback_used": false,
  "data_quality": "realtime",
  "source": [
    {
      "name": "MTA GTFS-RT",
      "updated_at": "2026-04-25T12:29:30-04:00"
    }
  ]
}
```

## 7.8 `GET /sessions/{session_id}/recommendations`

用途：读取当前 session 推荐结果。

Response `data`：

```json
{
  "recommendations": [
    {
      "rank_no": 1,
      "area": {
        "area_id": "QN0101",
        "area_name": "Astoria",
        "borough": "Queens"
      },
      "total_score": 83.5,
      "score_breakdown": {
        "safety": 82,
        "commute": 78,
        "rent": 85,
        "convenience": 80,
        "entertainment": 72
      },
      "reasons": [
        "租金更接近你的预算",
        "地铁通勤较方便"
      ],
      "risks": [
        "部分房源数据不是实时库存"
      ],
      "generated_at": "2026-04-25T12:30:00-04:00"
    }
  ]
}
```

## 7.9 `GET /health`

Response：

```json
{
  "status": "ok",
  "service": "api-gateway",
  "timestamp": "2026-04-25T12:30:00-04:00"
}
```

## 7.10 `GET /ready`

Response：

```json
{
  "status": "ready",
  "dependencies": {
    "orchestrator-agent": "ok",
    "profile-agent": "ok",
    "postgres": "ok",
    "redis": "ok"
  }
}
```

## 7.11 `GET /debug/traces/{trace_id}`

仅 `DEBUG=true` 启用。

Response `data`：

```json
{
  "trace_id": "trace_01H...",
  "events": [
    {
      "step": "api_gateway.received",
      "service": "api-gateway",
      "status": "success",
      "latency_ms": 8,
      "timestamp": "2026-04-25T12:30:00-04:00"
    },
    {
      "step": "domain.sql_validation",
      "service": "mcp-safety",
      "status": "success",
      "latency_ms": 24,
      "metadata": {
        "sql_redacted": "SELECT offense_category, COUNT(*) FROM app_crime_incident_snapshot WHERE area_id = :area_id GROUP BY offense_category LIMIT 20",
        "attempt_count": 1
      }
    }
  ]
}
```

规则：
- 可返回脱敏 SQL
- 参数值必须脱敏或截断
- 不返回完整 Prompt
- 不返回 API Key

## 7.12 `GET /debug/dependencies`

仅 `DEBUG=true` 启用。

Response `data`：

```json
{
  "dependencies": [
    {
      "service": "orchestrator-agent",
      "status": "ok",
      "latency_ms": 12
    },
    {
      "service": "postgres",
      "status": "ok",
      "latency_ms": 5
    }
  ]
}
```

## 7.7 `GET /areas/{area_id}/weather`

用途：目标区域默认天气卡片。自然语言天气问答仍通过 `POST /chat` 进入 Orchestrator。

Query params：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `session_id` | string | 是 | 无 | 会话ID |
| `hours` | integer | 否 | `6` | 返回未来小时数，MVP 最大 12 |
| `target_time` | string | 否 | null | ISO datetime；如果提供则返回最接近该时刻的小时级预报 |

Response `data`：

```json
{
  "area": {
    "area_id": "QN0101",
    "area_name": "Astoria",
    "borough": "Queens"
  },
  "weather": {
    "mode": "hourly_summary",
    "target_time": null,
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
        "detailed_forecast": "Mostly sunny, with a high near 64.",
        "is_daytime": true
      }
    ]
  },
  "data_quality": "cached",
  "source": [
    {
      "name": "National Weather Service API",
      "type": "weather_api",
      "url": "https://api.weather.gov",
      "updated_at": "2026-04-25T12:50:00-04:00"
    }
  ],
  "updated_at": "2026-04-25T12:50:00-04:00",
  "expires_at": "2026-04-25T13:20:00-04:00"
}
```

## 8. 前端展示 Schema

### 8.1 Chat Message

```json
{
  "id": "msg_ui_01",
  "role": "assistant",
  "message_type": "answer",
  "content": "Astoria 的安全情况整体属于中等偏好。",
  "created_at": "2026-04-25T12:30:00-04:00",
  "cards": [],
  "sources": []
}
```

### 8.2 Metric Card

```json
{
  "card_type": "metric",
  "title": "安全概况",
  "subtitle": "近 30 天公开犯罪记录",
  "score_label": "中等",
  "metrics": [
    {
      "label": "犯罪记录数",
      "value": 42,
      "unit": "起"
    }
  ],
  "data_quality": "reference",
  "source": []
}
```

### 8.3 Source Item

```json
{
  "name": "NYPD Complaint Data",
  "type": "nyc_open_data",
  "url": "https://data.cityofnewyork.us/resource/qgea-i56i.json",
  "updated_at": "2026-04-25T00:00:00-04:00"
}
```

### 8.4 Display Refs

```json
{
  "map_layer_ids": ["map_01H..."],
  "display_result_ids": ["disp_01H..."]
}
```

前端处理：
- `map_layer_ids` 触发地图图层加载
- `display_result_ids` 后续可用于房源列表/表格接口

### 8.5 Weather Card

```json
{
  "card_type": "weather",
  "title": "Astoria 天气",
  "subtitle": "未来 6 小时",
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
  ],
  "data_quality": "cached",
  "source": [
    {
      "name": "National Weather Service API",
      "type": "weather_api",
      "url": "https://api.weather.gov",
      "updated_at": "2026-04-25T12:50:00-04:00"
    }
  ]
}
```

## 9. 后端内部 Orchestrator Schema

### 9.1 Understand Result

```json
{
  "source": "llm",
  "intents": [
    {
      "domain": "neighborhood",
      "task_type": "neighborhood.crime_query",
      "confidence": 0.91,
      "domain_user_query": "Astoria 最近偷窃多吗？"
    }
  ],
  "slots": {
    "target_area": {
      "value": "Astoria",
      "source": "user_explicit",
      "confidence": 0.95
    }
  },
  "weight_updates": {
    "safety": {
      "value": 0.45,
      "source": "user_explicit",
      "confidence": 0.9
    }
  },
  "missing_slots": [],
  "low_confidence_slots": [],
  "next_action": "call_agent",
  "direct_response_type": null
}
```

规则：
- 必须严格 JSON
- Pydantic 校验失败重试一次
- 仍失败走关键词 fallback
- Orchestrator 不输出 MCP/tool/SQL

## 10. A2A Envelope

```json
{
  "message_id": "msg_01H...",
  "trace_id": "trace_01H...",
  "session_id": "sess_01H...",
  "source_agent": "orchestrator-agent",
  "target_agent": "neighborhood-agent",
  "task_type": "neighborhood.crime_query",
  "intent": "get_crime_info",
  "status": "pending",
  "next_action": "call_agent",
  "payload": {
    "domain_user_query": "Astoria 最近偷窃多吗？",
    "slots": {},
    "domain_context": {
      "window_days": 30
    }
  },
  "slot_state": {
    "required_slots": ["target_area"],
    "filled_slots": {
      "target_area": "Astoria"
    },
    "missing_slots": [],
    "slot_confidence": {
      "target_area": 0.95
    },
    "follow_up_count": 0
  },
  "confidence": {
    "intent": 0.9,
    "overall": 0.86
  },
  "data_quality": {
    "source": "nypd_complaint_data",
    "freshness": "reference",
    "confidence": 0.82,
    "timestamp": "2026-04-25T12:30:00-04:00"
  },
  "error": null,
  "created_at": "2026-04-25T12:30:00-04:00"
}
```

## 11. Domain Agent Schema

### 11.1 Domain Task Input

Domain Task Input 只包含领域任务所需的最小上下文。完整 `profile_snapshot` 和完整 `conversation_summary` 只允许 Orchestrator/Profile Agent 使用，不能透传给 Domain Agent。

```json
{
  "trace_id": "trace_01H...",
  "session_id": "sess_01H...",
  "domain": "neighborhood",
  "task_type": "neighborhood.crime_query",
  "domain_user_query": "Astoria 最近偷窃多吗？",
  "slots": {
    "target_area": {
      "value": "Astoria",
      "source": "user_explicit",
      "confidence": 0.95
    }
  },
  "domain_context": {
    "window_days": 30,
    "currency": "USD"
  },
  "debug": false
}
```

### 11.2 Domain Agent Output

```json
{
  "status": "success",
  "task_type": "neighborhood.crime_query",
  "domain": "neighborhood",
  "analysis_result": {
    "result_type": "crime_count_by_type",
    "key_metrics": {
      "total_count": 42,
      "top_category": "PETIT LARCENY"
    },
    "rows": []
  },
  "display_refs": {
    "map_layer_id": "map_01H...",
    "display_result_id": null
  },
  "data_available": true,
  "source": [],
  "source_tables": ["app_crime_incident_snapshot"],
  "data_quality": "reference",
  "default_applied": [
    {
      "field": "window_days",
      "value": 30,
      "reason": "用户使用了'最近'，按默认近 30 天处理。"
    }
  ],
  "fallback_used": false,
  "clarification": null,
  "error": null,
  "trace": {
    "attempt_count": 1,
    "latency_ms": 320
  }
}
```

Domain Agent `status`：
- `success`
- `no_data`
- `unsupported_data_request`
- `clarification_required`
- `validation_failed`
- `dependency_failed`
- `error`

## 12. SQL Generation Schema

### 12.1 SQL Ready

```json
{
  "status": "sql_ready",
  "queries": [
    {
      "purpose": "analysis",
      "sql": "SELECT offense_category, COUNT(*) AS crime_count FROM app_crime_incident_snapshot WHERE area_id = :area_id GROUP BY offense_category LIMIT 20",
      "params": {
        "area_id": "QN0101"
      },
      "expected_result": "crime_count_by_type"
    }
  ],
  "default_applied": [],
  "reason_summary": "用户询问目标区域近期偷窃情况，查询犯罪分类统计。"
}
```

Query `purpose`：
- `analysis`
- `display`
- `map_layer`

### 12.2 Unsupported Data Request

```json
{
  "status": "unsupported_data_request",
  "queries": [],
  "unsupported_reason": "当前 schema 没有街道照明或夜间人流数据，无法判断某条街晚上是否明亮。",
  "missing_or_unavailable_fields": [
    "street_lighting",
    "nighttime_foot_traffic"
  ],
  "suggested_alternative": "可以基于公开犯罪记录和附近交通设施，提供夜间安全参考。"
}
```

## 13. MCP Schema

### 13.1 MCP Response Envelope

```json
{
  "status": "success",
  "tool": "execute_readonly_sql",
  "data": {},
  "source": [
    {
      "name": "app_crime_incident_snapshot",
      "type": "postgresql",
      "timestamp": "2026-04-25T12:30:00-04:00"
    }
  ],
  "timestamp": "2026-04-25T12:30:00-04:00",
  "confidence": 0.9,
  "data_quality": "reference",
  "error": null
}
```

### 13.2 `execute_readonly_sql` Request

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
    "app_crime_incident_snapshot": ["area_id", "offense_category", "occurred_at", "occurred_date", "geom"],
    "app_area_dimension": ["area_id", "area_name", "borough", "geom", "geom_geojson"]
  }
}
```

### 13.3 `execute_readonly_sql` Success Data

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

### 13.4 `execute_readonly_sql` No Data

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

### 13.5 SQL Validation Error

```json
{
  "status": "validation_error",
  "error": {
    "code": "SQL_VALIDATION_FAILED",
    "message": "SELECT * is not allowed.",
    "retryable": true,
    "details": {
      "rule": "no_select_star"
    }
  }
}
```

## 14. Data Sync API Schema

虽然前端 MVP 不一定直接使用 data-sync API，但 Debug/Admin 页面可以使用。

### 14.1 `GET /sync/status`

Response：

```json
{
  "jobs": [
    {
      "job_id": "sync_01H...",
      "job_name": "sync_nypd_crime",
      "status": "succeeded",
      "trigger_type": "bootstrap",
      "rows_fetched": 1000,
      "rows_written": 980,
      "api_calls_used": 1,
      "started_at": "2026-04-25T12:00:00-04:00",
      "finished_at": "2026-04-25T12:02:00-04:00",
      "error_code": null,
      "error_message": null
    }
  ]
}
```

### 14.2 `POST /sync/run/{job_name}`

Request：

```json
{
  "trigger_type": "manual",
  "target_scope": {
    "areas": ["Astoria", "Long Island City"],
    "date_range": {
      "start": "2026-03-25",
      "end": "2026-04-25"
    }
  },
  "dry_run": false
}
```

Response：

```json
{
  "job_id": "sync_01H...",
  "job_name": "sync_nypd_crime",
  "status": "running",
  "estimated_api_calls": 1
}
```

## 15. TypeScript 类型生成建议

前端建议维护：

```text
src/types/api.ts
src/types/profile.ts
src/types/chat.ts
src/types/map.ts
src/types/transit.ts
src/types/weather.ts
src/types/debug.ts
```

建议核心泛型：

```ts
export type ApiEnvelope<T> = {
  success: boolean;
  trace_id: string;
  session_id?: string | null;
  data: T | null;
  error: ApiError | null;
};

export type ApiError = {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
};
```

后端建议用 Pydantic model 与 TypeScript 类型一一对应。

## 16. 版本管理

MVP schema 版本：

```text
schema_version = "v0.1"
```

规则：
- 破坏性字段变更必须升级版本
- 新增 nullable 字段不视为破坏性变更
- 删除字段、改名、改 enum 必须同步前端
- API Gateway 可在 response header 增加 `X-Schema-Version: v0.1`

## 17. 实现优先级

建议先实现这些 schema：

1. `ApiEnvelope`
2. `ApiError`
3. `ProfileSnapshot`
4. `POST /sessions`
5. `POST /chat`
6. `DomainAgentOutput`
7. `SQLGenerationResult`
8. `MCP execute_readonly_sql`
9. `GET /areas/{area_id}/metrics`
10. `GET /areas/{area_id}/map-layers`
11. `GET /areas/{area_id}/weather`
12. `POST /transit/realtime`
13. `GET /debug/traces/{trace_id}`

原因：
- 前端最先需要 session、chat、profile
- 后端最先需要 Domain Agent 和 MCP SQL schema
- 地图和 debug 可随后接入
