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
- Agent 协作使用 `python-a2a`，server 端用 `python_a2a.A2AServer`（Flask-native），client 端用 `python_a2a.A2AClient`
- 每个 Agent 服务在同一个 Flask app 上额外挂载管理接口，如 `/health`、`/agent/info`、`/debug/run`
- 普通问答同步返回
- 耗时任务异步返回 `task_id`

## 2. python-a2a 三个核心类型

A2A 协议在 python-a2a 实现里通过三个类承载：

| 类型 | 用途 | 在本项目里 |
|---|---|---|
| `AgentCard` | Agent 身份与能力卡，外部通过 `/agent.json` 发现 agent | 6 个 agent 启动时各自构造一份，详见 §2.1 |
| `Message` | 同步通信的标准载体，包含 `role + content` | 普通问答的请求/响应都用它，详见 §2.2 |
| `Task` | 异步任务状态机，覆盖 submitted → working → completed/failed/canceled/input_required | 长耗时操作（推荐生成、批量对比）走它，详见 §2.3 |

### 2.1 AgentCard 设计
每个 agent 启动时实例化一份 `AgentCard`，传给 `A2AServer(agent_card=...)`，A2AServer 自动暴露 `GET /agent.json` 给外部发现：

```python
from python_a2a import AgentCard, AgentSkill, A2AServer

card = AgentCard(
    name="housing-agent",
    description="纽约租房 / 房源 / 预算匹配",
    url="http://housing-agent:8011",
    version="1.0.0",
    skills=[
        AgentSkill(name="housing.rent_query",       description="查询某区域户型的租金区间"),
        AgentSkill(name="housing.listing_search",   description="筛选符合预算和户型的真实房源"),
    ],
    capabilities={"streaming": False, "async_tasks": False},
    default_input_modes=["text"],
    default_output_modes=["text", "data"],
)
agent = HousingAgentServer(agent_card=card)
```

6 个 agent 的 AgentCard 由各自定义 `name / description / skills` 列表（与 §4 的 task_type 对齐）；`url` 用容器内部 hostname。

### 2.2 Message.content 字段约定
`Message` 类本身只有 `role + content + parent_message_id + conversation_id` 四个顶层字段。本项目的业务上下文统一塞进 `content` 这个 dict，字段约定如下：

```json
{
  "role": "user",
  "content": {
    "task_type": "housing.rent_query",
    "intent": "get_rent_info",
    "trace_id": "trace_01H...",
    "session_id": "sess_01H...",
    "source_agent": "orchestrator-agent",
    "target_agent": "housing-agent",
    "next_action": "call_agent",
    "payload": { "...domain-specific..." },
    "slot_state": {
      "required_slots": ["target_area"],
      "filled_slots": {"target_area": "Greenpoint"},
      "missing_slots": [],
      "slot_confidence": {"target_area": 0.91},
      "follow_up_count": 0
    },
    "context": {
      "user_text": "Greenpoint 房租大概多少？",
      "domain_user_query": "Greenpoint 房租大概多少？",
      "conversation_summary": "",
      "weights": {"safety": 0.3, "commute": 0.3, "rent": 0.2, "convenience": 0.1, "entertainment": 0.1}
    }
  },
  "parent_message_id": null,
  "conversation_id": "sess_01H..."
}
```

响应 Message：
```json
{
  "role": "agent",
  "content": {
    "task_type": "housing.rent_query",
    "status": "success",
    "payload": { "rent_min": 2400, "rent_median": 2900, "rent_max": 3500, "...": "..." },
    "confidence": {"intent": 0.9, "overall": 0.86},
    "data_quality": {
      "source": "rentcast_listings",
      "freshness": "realtime",
      "confidence": 0.82,
      "timestamp": "2026-04-28T12:00:00-04:00"
    },
    "error": null
  },
  "parent_message_id": "<incoming msg id>",
  "conversation_id": "sess_01H..."
}
```

字段语义约定：
- `task_type`：sub-agent 入口分发的依据，与 §4 列表对齐
- `payload`：领域 agent 自由 schema，详见 `NYC_Agent_API_Schema_Contract.md`
- `slot_state` / `context`：仅 Orchestrator → Domain Agent 方向使用；Domain Agent 不需要回填这些
- `data_quality` / `confidence` / `error`：仅 Domain Agent → Orchestrator 方向回传

`role` 必须是 `MessageRole.USER`（请求）或 `MessageRole.AGENT`（响应），由 python-a2a 枚举约束。

#### Pass-through 原则
**Orchestrator 不假设 Domain Agent `content` 内部字段结构**。Domain Agent 返回的整个 `Message.content` dict 直接序列化（JSON）后传给 Orchestrator 的 respond LLM，由 LLM 自己从 dict 里挑相关字段写答案。

理由：
- 不是所有 agent 响应都有 `payload`（例如 `clarification_required` 只有 `clarification` 文本）
- `data_quality` / `confidence` / `error` / `status` 等顶层字段对 LLM 同样有用（BL §15 要求回答中带数据来源 + 时间窗口 + 不确定声明）
- Orchestrator 只看 `status` 决定路由（success / clarification_required / failed），其它字段一律 pass-through，避免每个 agent 类型写一个特殊 extractor

新加 agent 或 agent 在 `content` 里多放一个新字段时，orchestrator 不需要改代码——LLM 自然能看见。

### 2.3 Task 状态机使用
Task 用于**确实耗时**的工作（>5s 或会话需要结果但 client 不想阻塞）。MVP 阶段绝大部分查询走 Message 同步；Task 留接口给以下场景：
- 完整推荐报告生成
- 批量区域对比
- 地图图层预计算
- 较慢的数据聚合

Task 状态机：
```
submitted ──> working ──> completed
                ├──> failed
                ├──> canceled
                └──> input_required   (需要用户补充信息)
```

Client 端：
```python
from python_a2a import A2AClient

client = A2AClient(endpoint_url="http://orchestrator-agent:8010")
task = client.send_task_async({"task_type": "decision.full_recommendation", ...})
# task.id 形如 "task_01H..."

# 轮询
result = client.get_task(task.id)
while result.state == "working":
    time.sleep(2)
    result = client.get_task(task.id)
```

A2AServer 自动注册 `POST /tasks/send` 和 `GET /tasks/{id}`，无需手写。Server 端 override `handle_task(task)` 即可：
```python
class HousingAgentServer(A2AServer):
    def handle_task(self, task):
        # 长任务跑完后填 task.result，框架自动转 completed
        task.result = compute_recommendation(task.input)
        return task
```

MVP 先实现同步 Message，Task 只占接口、不深入实现细节。

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

`target_area` 规则：
- `target_area` 是住房、区域画像、天气和推荐类 intent 的硬性必填。
- 站点级或地址级实时交通 intent 不强制要求 `target_area`；例如用户明确给出站点、origin、destination 和 mode 时，可以直接执行 `transit.next_departure` / `transit.realtime_commute`。
- 如果交通问题只说“从我的目标区域出发”但没有具体 origin，则可以使用会话中的 `target_area`；会话中也没有时再追问。

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
同步用 `Message`（详见 §2.2）：
- 单点犯罪查询
- 娱乐/便利分类查询
- 租金概况
- 权重更新
- 实时下一班车
- 当前/指定时刻天气查询

异步用 `Task`（详见 §2.3）：
- 完整推荐
- 批量区域对比
- 地图图层预计算
- 较慢的数据聚合

Task 创建后由 client 通过 `GET /tasks/{id}` 轮询；状态机 `submitted → working → completed/failed/canceled/input_required`。

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
错误响应仍然包在 `Message`（同步）或 `Task.error`（异步）里。`Message.content` 顶层 `status` + `error` 字段约定如下：

```json
{
  "role": "agent",
  "content": {
    "task_type": "housing.rent_query",
    "status": "failed",
    "error": {
      "code": "MISSING_REQUIRED_SLOT",
      "message": "Missing target_area",
      "retryable": true,
      "fallback_available": false,
      "details": {}
    }
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
