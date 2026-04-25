# NYC Agent A2A 协议设计（MVP）

## 1. 目标
本文件定义 Agent-to-Agent 的消息协议、槽位校验、追问循环、错误处理和调用追踪。

适用服务：
- `orchestrator-agent`
- `housing-agent`
- `neighborhood-agent`
- `transit-agent`
- `weather-agent`
- `profile-agent`

实现方式：
- Agent 协作使用 `python-a2a`
- 每个 Agent 服务额外提供 FastAPI 管理接口，如 `/health`、`/agent/info`、`/debug/run`
- 普通问答同步返回
- 耗时任务异步返回 `task_id`

## 2. 统一 A2A Envelope
MVP 采用统一 envelope，但 `payload` 允许各 Agent 自定义。

```json
{
  "message_id": "msg_01H...",
  "trace_id": "trace_01H...",
  "session_id": "sess_01H...",
  "source_agent": "orchestrator-agent",
  "target_agent": "housing-agent",
  "task_type": "housing.rent_query",
  "intent": "get_rent_info",
  "status": "pending",
  "next_action": "call_agent",
  "payload": {},
  "slot_state": {
    "required_slots": ["target_area"],
    "filled_slots": {
      "target_area": "Greenpoint"
    },
    "missing_slots": [],
    "slot_confidence": {
      "target_area": 0.91
    },
    "follow_up_count": 0
  },
  "context": {
    "user_text": "Greenpoint 房租大概多少？",
    "domain_user_query": "Greenpoint 房租大概多少？",
    "conversation_summary": "",
    "weights": {
      "safety": 0.3,
      "commute": 0.3,
      "rent": 0.2,
      "convenience": 0.1,
      "entertainment": 0.1
    }
  },
  "confidence": {
    "intent": 0.9,
    "overall": 0.86
  },
  "data_quality": {
    "source": "rentcast_listings",
    "freshness": "realtime",
    "confidence": 0.82,
    "timestamp": "2026-04-24T12:00:00-04:00"
  },
  "error": null,
  "created_at": "2026-04-24T12:00:00-04:00"
}
```

## 3. Slot 校验与追问循环
缺槽逻辑采用双层校验：
- `orchestrator-agent`：负责主槽位抽取、必填项判断、追问循环
- 领域 Agent：收到任务后做二次校验，缺字段则返回 `missing_slots`
- MCP：默认只接收完整参数，不负责自然语言追问

执行规则：
1. Orchestrator 先识别 `intent`
2. 根据 intent 查询 `required_slots`
3. 如果 `missing_slots` 非空，设置 `next_action=ask_follow_up`
4. 不调用领域 Agent，不调用 MCP
5. 用户回答后重新抽取槽位
6. 循环直到 `missing_slots=[]`
7. 槽位齐全后才进入 `call_agent`

追问轮次：
- 一般缺失信息最多连续追问 3 轮
- 硬性必填槽位未补齐时，不进入业务执行
- 超过 3 轮后，Agent 可以换问法或给用户示例

## 4. Intent 与 Required Slots
MVP 先支持以下 intent：

| intent | task_type | required_slots | 说明 |
|---|---|---|---|
| `housing.rent_query` | `housing.rent_query` | `target_area` | 查询区域租金区间和房源概况 |
| `housing.listing_search` | `housing.listing_search` | `target_area` | 查询房源清单；预算/户型可选 |
| `neighborhood.crime_query` | `neighborhood.crime_query` | `target_area` | 查询犯罪数量/安全概况 |
| `neighborhood.entertainment_query` | `neighborhood.entertainment_query` | `target_area` | 查询娱乐设施分类和数量 |
| `neighborhood.convenience_query` | `neighborhood.convenience_query` | `target_area` | 查询便利设施分类和数量 |
| `area.metrics_query` | `area.metrics_query` | `target_area` | 查询区域综合指标 |
| `profile.update_weights` | `profile.update_weights` | `session_id` | 更新用户权重 |
| `transit.next_departure` | `transit.next_departure` | `mode`, `station_or_origin` | 查询某站/某地下一班车 |
| `transit.commute_time` | `transit.commute_time` | `origin`, `destination`, `mode` | 查询从 A 到 B 坐地铁/公交多久 |
| `transit.realtime_commute` | `transit.realtime_commute` | `origin`, `destination`, `mode` | 查询实时通勤和推荐出发时间 |
| `weather.current_query` | `weather.current_query` | `target_area` | 查询目标区域当前到未来数小时天气 |
| `weather.forecast_query` | `weather.forecast_query` | `target_area` | 查询目标区域指定时刻天气，`target_time` 可选 |
| `recommendation.generate` | `recommendation.generate` | `target_area` | 生成区域推荐/对比 |

交通方式规则：
- 用户没说交通方式：追问地铁还是公交
- 用户说“都可以”：同时查地铁和公交，返回更合理的一种
- 用户明确地铁/公交：只查对应方式

天气规则：
- 用户没说区域但 session 已有 `target_area`：继承 session 区域
- 用户没说区域且 session 没有 `target_area`：追问目标区域
- 用户没说时间：默认查询当前到未来 6 小时
- 用户说指定时间：Orchestrator 抽取 `target_time` 并传给 `weather-agent`
- 天气不更新推荐权重，不触发推荐打分

## 5. next_action 枚举
允许值：
- `ask_follow_up`：缺槽，需要追问
- `confirm_slots`：关键槽位刚抽取完，需要回显确认
- `update_profile`：只更新权重/偏好，不查询业务数据
- `call_agent`：槽位齐全，调用领域 Agent
- `call_mcp`：领域 Agent 调用 MCP
- `respond_final`：可以直接回复用户
- `run_async_task`：进入异步任务
- `fallback`：数据源失败，走降级
- `error`：不可恢复错误

## 6. 同步与异步
同步任务：
- 单点犯罪查询
- 娱乐/便利分类查询
- 租金概况
- 权重更新
- 实时下一班车
- 当前/指定时刻天气查询

异步任务：
- 完整推荐
- 批量区域对比
- 地图图层预计算
- 较慢的数据聚合

异步任务返回：
```json
{
  "task_id": "task_01H...",
  "status": "running",
  "poll_url": "/tasks/task_01H..."
}
```

## 7. 并发策略
A2A 调用采用混合并发：
- 单意图：串行调用一个领域 Agent
- 多意图：Orchestrator 使用并行调用，如 `asyncio.gather`
- 任一领域 Agent 失败，不影响其他成功结果
- 聚合结果时保留每个 Agent 的 `source/timestamp/confidence/data_quality`

例子：
用户问：“Greenpoint 安不安全，房租多少，通勤到 NYU 方便吗？”
- 并行调用 `neighborhood-agent`
- 并行调用 `housing-agent`
- 并行调用 `transit-agent`
- Orchestrator 合并结果后返回

## 8. 标准错误结构
所有 Agent 错误统一返回：

```json
{
  "status": "failed",
  "error": {
    "code": "MISSING_REQUIRED_SLOT",
    "message": "Missing target_area",
    "retryable": true,
    "fallback_available": false,
    "details": {}
  }
}
```

错误码：
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

## 9. Trace 与落库
每次用户请求必须生成 `trace_id`。

Trace 贯穿：
- `api-gateway`
- `orchestrator-agent`
- 领域 Agent
- MCP 服务
- 数据库/外部 API 调用

建议新增表：

```sql
CREATE TABLE IF NOT EXISTS app_a2a_trace_log (
  trace_log_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  session_id TEXT NULL,
  source_agent TEXT NOT NULL,
  target_agent TEXT NULL,
  task_type TEXT NULL,
  intent TEXT NULL,
  next_action TEXT NULL,
  status TEXT NOT NULL,
  latency_ms INTEGER NULL,
  error_code TEXT NULL,
  request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

用途：
- Demo 展示 multi-agent trace
- 调试领域 Agent 和 MCP 调用链
- 统计工具调用成功率、失败率、平均时延

## 10. 领域 Agent 输出规范
领域 Agent 返回必须包含：
- `analysis_result`：结构化业务分析结果
- `display_refs`：地图、列表、卡片等展示型数据引用
- `source`
- `source_tables`
- `timestamp`
- `confidence`
- `data_quality`
- `default_applied`
- `fallback_used`
- `clarification`
- `error`

示例：
```json
{
  "status": "success",
  "domain": "housing",
  "task_type": "housing.rent_query",
  "analysis_result": {
    "area_id": "BK0101",
    "rent_median": 3200,
    "listing_count": 42
  },
  "display_refs": {},
  "data_available": true,
  "source": "rentcast_listings",
  "source_tables": ["app_area_rental_market_daily"],
  "timestamp": "2026-04-24T12:00:00-04:00",
  "confidence": 0.84,
  "data_quality": "reference",
  "default_applied": [],
  "fallback_used": false,
  "clarification": null,
  "error": null,
  "trace": {
    "attempt_count": 1,
    "latency_ms": 320
  }
}
```

领域 Agent 状态枚举：
- `success`
- `no_data`
- `unsupported_data_request`
- `clarification_required`
- `validation_failed`
- `dependency_failed`
- `error`

调用领域 Agent 时，Orchestrator 必须传递 `domain_user_query`。  
`domain_user_query` 是从用户原始问题中拆出的领域相关子问题，用于领域 Agent 生成 SQL 或固定工具调用参数。

例如用户问：
```text
Astoria 安全吗？房租贵不贵？
```

传给 `neighborhood-agent`：
```json
{
  "task_type": "neighborhood.crime_query",
  "domain_user_query": "Astoria 安全吗？",
  "slots": {
    "target_area": "Astoria"
  }
}
```

传给 `housing-agent`：
```json
{
  "task_type": "housing.rent_query",
  "domain_user_query": "Astoria 房租贵不贵？",
  "slots": {
    "target_area": "Astoria"
  }
}
```
