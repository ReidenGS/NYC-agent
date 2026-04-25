# NYC Agent 后端技术框架（MVP）

## 1. 后端定位
后端采用轻量实现，但保留清晰的多服务边界。

目标：
- 一周内跑通完整业务闭环
- 明确展示 `A2A + MCP + FastAPI + PostGIS` 的工程能力
- 避免把所有逻辑塞进一个单体服务

运行方式：
- 使用 Docker Compose 管理多个独立服务
- 服务之间通过 HTTP、A2A、MCP 通信
- 开发阶段使用匿名 `session_id`
- 生产演进时扩展 JWT/OAuth、任务队列、监控与限流

## 2. 技术选型
核心技术：
- Python 3.11+
- FastAPI：API Gateway 与普通 HTTP 服务
- python-a2a：Agent-to-Agent 通信
- `python_a2a.mcp.FastMCP`：独立 MCP 工具服务
- PostgreSQL + PostGIS：业务数据、空间查询、区域归属
- Redis：实时通勤短缓存、天气短缓存、API 限频、临时结果缓存
- APScheduler：定时同步外部 API 数据
- 可配置 LLM Provider：默认 OpenAI，保留切换 Anthropic/Gemini/Ollama 的接口

## 3. 服务拆分
MVP 服务：
- `api-gateway`：前端入口、会话 API、用户请求转发
- `orchestrator-agent`：意图理解、任务拆分、A2A 调度、结果合并
- `housing-agent`：租金、房源、预算匹配
- `neighborhood-agent`：犯罪、安全、便利、娱乐、区域画像
- `transit-agent`：静态通勤、实时地铁/公交、下一班车
- `weather-agent`：目标区域当前天气、小时级天气预报、指定时刻天气问答
- `profile-agent`：槽位、权重、会话状态
- `mcp-housing`：RentCast、ZORI/HUD、房源查询工具
- `mcp-safety`：NYPD 犯罪数据、安全指标、安全地图图层工具
- `mcp-amenity`：便利设施分类、便利设施地图点位工具
- `mcp-entertainment`：娱乐设施分类、娱乐设施地图点位工具
- `mcp-transit`：MTA static GTFS、GTFS-RT、Bus Time 工具
- `mcp-weather`：National Weather Service API、天气短缓存工具
- `mcp-profile`：会话 profile、权重、推荐结果读写工具
- `postgres`：PostgreSQL + PostGIS
- `redis`：缓存与限频

说明：
- Agent 服务负责推理和协作
- MCP 服务负责工具化访问数据/API
- API Gateway 不直接写复杂业务逻辑

## 4. Docker Compose 拓扑
建议端口：
- `api-gateway`: `8000`
- `orchestrator-agent`: `8010`
- `housing-agent`: `8011`
- `neighborhood-agent`: `8012`
- `transit-agent`: `8013`
- `profile-agent`: `8014`
- `weather-agent`: `8015`
- `mcp-housing`: `8021`
- `mcp-safety`: `8022`
- `mcp-amenity`: `8023`
- `mcp-entertainment`: `8024`
- `mcp-transit`: `8025`
- `mcp-profile`: `8026`
- `mcp-weather`: `8027`
- `postgres`: `5432`
- `redis`: `6379`

MVP 可以先启动全部服务；如果调试压力大，优先保证：
- `api-gateway`
- `orchestrator-agent`
- `mcp-profile`
- `mcp-safety`
- `mcp-amenity`
- `mcp-entertainment`
- `mcp-housing`
- `mcp-transit`
- `mcp-weather`
- `postgres`
- `redis`

## 5. A2A Agent 协作逻辑
详细协议见：[NYC_Agent_A2A_Protocol.md](</Users/jackiewen/Documents/NYC agent/NYC_Agent_A2A_Protocol.md>)。

主链路：
1. 前端调用 `POST /chat`
2. `api-gateway` 转发给 `orchestrator-agent`
3. `orchestrator-agent` 抽取意图、槽位、权重
4. 如果缺少 `target_area`，返回追问
5. 如果是租金/房源问题，调用 `housing-agent`
6. 如果是犯罪/便利/娱乐问题，调用 `neighborhood-agent`
7. 如果是实时通勤问题，调用 `transit-agent`
8. 如果是天气问题，调用 `weather-agent`
9. 如果涉及权重/会话状态，调用 `profile-agent`
10. Orchestrator 合并答案并返回前端

Agent 职责：
- `orchestrator-agent`：只负责判断、调度、聚合，不直接访问外部数据
- `housing-agent`：调用 `mcp-housing`，处理租金、房源、执行包
- `neighborhood-agent`：调用 `mcp-safety`、`mcp-amenity`、`mcp-entertainment`，处理区域指标
- `transit-agent`：调用 `mcp-transit`，处理静态/实时通勤
- `weather-agent`：调用 `mcp-weather`，处理当前/小时级天气
- `profile-agent`：调用 `mcp-profile`，处理 session、slots、weights

## 6. MCP 服务与工具清单
详细设计见：[NYC_Agent_MCP_Design.md](</Users/jackiewen/Documents/NYC agent/NYC_Agent_MCP_Design.md>)。

MVP MCP 服务：
- `mcp-housing`
- `mcp-safety`
- `mcp-amenity`
- `mcp-entertainment`
- `mcp-transit`
- `mcp-weather`
- `mcp-profile`

Agent 层保持粗粒度：
- `neighborhood-agent` 同时调用 `mcp-safety`、`mcp-amenity`、`mcp-entertainment`
- 后续可演进为 `safety-agent`、`amenity-agent`、`entertainment-agent`

## 7. API Gateway 路由
API Gateway 采用薄网关设计，不保存业务状态，不直接访问数据库，不直接调用 MCP。

职责边界：
- 接收前端 HTTP 请求
- 创建或透传 `session_id`
- 生成并透传 `trace_id`
- 做中等强度请求校验
- 调用 `orchestrator-agent` 或必要的领域 Agent
- 返回统一响应 envelope
- 执行轻量 `session_id` 级限流

不负责：
- 不管理槽位、权重、推荐结果
- 不做业务级判断
- 不判断区域是否真实存在
- 不直接读写 PostgreSQL
- 不直接调用任何 MCP 服务

MVP 路由：
- `POST /sessions`
- `POST /chat`
- `GET /sessions/{id}/profile`
- `PATCH /sessions/{id}/profile`
- `GET /areas/{id}/metrics`
- `GET /areas/{id}/map-layers`
- `GET /areas/{id}/weather`
- `POST /transit/realtime`
- `GET /sessions/{id}/recommendations`
- `GET /health`
- `GET /ready`

Debug 路由（仅 `DEBUG=true` 时启用）：
- `GET /debug/traces/{trace_id}`
- `GET /debug/dependencies`

鉴权：
- MVP 使用匿名 `session_id`
- `session_id` 由前端首次访问时调用 `POST /sessions` 创建
- `POST /sessions` 由 API Gateway 转发给 `profile-agent / mcp-profile` 创建真实 session 记录
- 生产演进：JWT/OAuth + 用户账户 + 删除会话能力

### 7.1 Session 创建流程
`session_id` 是匿名会话编号，用于绑定多轮上下文、槽位、权重、推荐结果和 trace。

创建流程：
1. 前端首次打开页面时调用 `POST /sessions`
2. API Gateway 生成 `trace_id`
3. API Gateway 请求 `profile-agent` 创建 session
4. `profile-agent` 通过 `mcp-profile` 写入 PostgreSQL
5. API Gateway 返回 `session_id`

后续请求必须携带 `session_id`：
- `/chat`
- `/sessions/{id}/profile`
- `/areas/{id}/metrics`
- `/areas/{id}/map-layers`
- `/areas/{id}/weather`
- `/transit/realtime`
- `/sessions/{id}/recommendations`

### 7.2 `/chat` 响应模式
MVP 使用普通 JSON 一次性返回，不做 token streaming，不做工具调用过程流式展示。

规则：
- 前端提交一句自然语言
- Gateway 校验请求后转发给 `orchestrator-agent`
- `orchestrator-agent` 完成意图识别、追问判断、A2A 调度和结果合并
- Gateway 返回完整 JSON
- 通过 `trace_id` 和 debug 接口展示 Agent 调用链

后续增强：
- 可新增 `POST /chat/stream` 或 `GET /chat/stream`
- 使用 SSE 展示 intent 识别、Agent 调用、MCP 工具调用和最终回答

### 7.3 直连 API 策略
MVP 采用 `/chat + 少量直连 API`。

用途：
- `/chat`：自然语言问答主入口
- `/sessions/{id}/profile`：前端状态面板读取/更新槽位和权重
- `/areas/{id}/metrics`：区域指标卡片
- `/areas/{id}/map-layers`：地图图层
- `/areas/{id}/weather`：目标区域天气卡片
- `/transit/realtime`：实时通勤卡片或用户主动查询
- `/sessions/{id}/recommendations`：推荐结果读取

设计原则：
- Agent 负责自然语言、追问、推理和决策
- 直连 API 负责前端组件稳定刷新
- 直连 API 仍然通过领域 Agent 或 `profile-agent` 获取数据
- Gateway 不绕过 Agent 直接访问 MCP 或数据库

### 7.4 请求校验
API Gateway 做中等强度校验。

校验范围：
- JSON 格式
- 必填字段
- 字段类型
- 字符串长度
- 枚举值
- 分页参数
- 经纬度范围

不做：
- 不判断 `target_area` 是否真实存在
- 不判断预算是否合理
- 不处理自然语言意图纠错
- 不做业务冲突判断

业务级校验交给：
- `orchestrator-agent`
- 领域 Agent
- MCP 工具层

### 7.5 统一响应 Envelope
所有 Gateway 接口使用统一基础 envelope。

成功响应：
```json
{
  "success": true,
  "trace_id": "trace_01H...",
  "session_id": "sess_01H...",
  "data": {},
  "error": null
}
```

失败响应：
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

Gateway 错误码：
- `VALIDATION_ERROR`
- `RATE_LIMITED`
- `DEPENDENCY_UNAVAILABLE`
- `ORCHESTRATOR_TIMEOUT`
- `AGENT_ERROR`
- `INTERNAL_ERROR`

### 7.6 `/chat` Data 结构
`/chat` 返回回答文本，同时返回最新 `profile_snapshot`，方便前端立即刷新状态面板。

请求示例：
```json
{
  "session_id": "sess_01H...",
  "message": "我想看 Astoria，安全最重要",
  "debug": false
}
```

响应 `data` 示例：
```json
{
  "message_type": "answer",
  "answer": "Astoria 的安全情况整体中等偏好。近 30 天公开犯罪记录为 ...",
  "next_action": "respond_final",
  "profile_snapshot": {
    "target_area": "Astoria",
    "budget_monthly": null,
    "target_destination": null,
    "weights": {
      "safety": 0.45,
      "commute": 0.25,
      "rent": 0.15,
      "convenience": 0.1,
      "entertainment": 0.05
    },
    "missing_required_fields": []
  },
  "cards": [],
  "sources": [],
  "confidence": 0.86,
  "data_quality": "reference"
}
```

当缺少硬性必填槽位时：
```json
{
  "message_type": "follow_up",
  "answer": "你想了解纽约哪个区域？例如 Astoria、LIC、Williamsburg。",
  "next_action": "ask_follow_up",
  "profile_snapshot": {
    "target_area": null,
    "weights": {}
  },
  "missing_slots": ["target_area"]
}
```

### 7.7 Debug Trace 返回规则
`/chat` 默认不返回 Agent 调用链。

当请求中 `debug=true` 时，`data` 中可包含简短 `trace_summary`：
```json
{
  "trace_summary": [
    {
      "step": "orchestrator.intent_detected",
      "agent": "orchestrator-agent",
      "status": "success",
      "latency_ms": 120
    },
    {
      "step": "neighborhood.crime_query",
      "agent": "neighborhood-agent",
      "mcp": "mcp-safety",
      "status": "success",
      "latency_ms": 420
    }
  ]
}
```

安全规则：
- 默认不返回 `trace_summary`
- `trace_summary` 只展示服务级调用
- 不返回 API Key
- 不返回完整 Prompt
- 不返回敏感内部上下文
- 完整 trace 写入后端日志和 `app_a2a_trace_log`

### 7.8 Health 与 Readiness
`GET /health`：
- 只检查 API Gateway 自身是否存活
- 不检查依赖服务

`GET /ready`：
- 检查关键依赖是否可用
- 至少检查 `orchestrator-agent`
- 至少检查 `profile-agent`
- 至少检查 `postgres`
- 至少检查 `redis`

MCP 服务不由 Gateway 直接检查，因为 Gateway 不直接调用 MCP。更深层 MCP 健康状态由领域 Agent 或 Debug 接口检查。

### 7.9 限流策略
API Gateway 做轻量 `session_id` 级限流。

规则：
- 按 `session_id + endpoint` 限流
- 使用 Redis 计数
- MVP 不做复杂 IP 风控
- 超限返回统一错误 envelope

建议默认值：

| Endpoint | MVP 限流 |
|---|---|
| `/chat` | 20 次 / 分钟 / session |
| `/transit/realtime` | 10 次 / 分钟 / session |
| `/areas/{id}/map-layers` | 30 次 / 分钟 / session |
| `/sessions/{id}/profile` | 60 次 / 分钟 / session |

### 7.10 Debug 接口
最小 Debug 接口：
- `GET /debug/traces/{trace_id}`
- `GET /debug/dependencies`

启用规则：
- 仅在 `DEBUG=true` 时启用
- 默认生产关闭
- 仅用于本地开发、录屏和面试 Demo

`GET /debug/traces/{trace_id}`：
- 从 `app_a2a_trace_log` 读取调用链摘要
- 展示 Gateway、Orchestrator、领域 Agent、MCP 的调用顺序和耗时

`GET /debug/dependencies`：
- 展示 Gateway 可见依赖状态
- 包括 `orchestrator-agent`、`profile-agent`、`postgres`、`redis`
- 可选展示领域 Agent 健康状态
- 不直接暴露 API Key 或外部 API 原始响应

## 8. Orchestrator Agent 详细设计
`orchestrator-agent` 是后端 Agent 系统的大脑，负责把用户自然语言转成可执行的 Agent 调度计划。

职责：
- 接收 API Gateway 转发的 `/chat` 请求
- 读取当前 `profile_snapshot` 和 `conversation_summary`
- 执行自然语言理解
- 识别 intent、slot、权重变化
- 判断是否缺少必要信息
- 决定追问、直接回答、调用领域 Agent 或拒答
- 并行调度多个领域 Agent
- 合并领域 Agent 结果
- 生成最终自然语言回答
- 更新短 `conversation_summary`
- 写入精简决策 trace

不负责：
- 不直接调用 MCP
- 不直接访问外部 API
- 不直接写业务数据表
- 不编造工具结果中不存在的数据
- 不把完整 prompt 暴露给前端或 debug 接口

### 8.1 两段式 LLM 调用
Orchestrator 使用两段式 LLM 调用。

第一段：`Understand`
- intent 识别
- slot 抽取
- 权重解析
- 缺槽判断
- `next_action` 决策

第二段：`Respond`
- 基于领域 Agent / MCP 返回的真实数据生成自然语言回答
- 保留关键事实数字
- 不编造缺失数据
- 默认不向用户展示置信度

执行链路：
```text
User Message
 -> LLM Call 1: Understand
 -> 缺槽/低置信度：直接追问或确认
 -> 信息足够：A2A 调用 Domain Agent
 -> 收集 Agent 结果
 -> LLM Call 2: Respond
 -> 更新 summary 与 profile_snapshot
 -> 返回 API Gateway
```

### 8.2 Understand 严格 JSON Schema
`Understand` 阶段必须输出严格 JSON，后端使用 Pydantic 校验。

规则：
- LLM 只允许输出 JSON
- 不允许输出 Markdown
- 不允许用自然语言解释 JSON
- 校验失败时最多重试一次
- 重试仍失败则触发关键词 fallback parser

示例结构：
```json
{
  "source": "llm",
  "intents": [
    {
      "domain": "neighborhood",
      "task_type": "neighborhood.crime_query",
      "confidence": 0.91
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

### 8.3 两层 Intent
Orchestrator 使用两层 intent：
- `domain`
- `task_type`

示例：
```json
{
  "domain": "neighborhood",
  "task_type": "neighborhood.crime_query"
}
```

规则：
- `domain` 决定调用哪个领域 Agent
- `task_type` 决定 required slots 和业务处理路径
- 不支持的问题标记为 `domain=unknown`、`task_type=unknown`
- LLM 不允许直接选择 MCP 或 tool

Domain 映射：

| domain | target agent |
|---|---|
| `housing` | `housing-agent` |
| `neighborhood` | `neighborhood-agent` |
| `transit` | `transit-agent` |
| `weather` | `weather-agent` |
| `profile` | `profile-agent` |
| `recommendation` | `orchestrator-agent` 聚合多个领域 Agent |
| `system` | `orchestrator-agent` 直接回答 |
| `unknown` | 模板拒答或追问 |

### 8.4 多意图并行调度
Orchestrator 支持多意图问题。

例子：
```text
Astoria 安全吗？房租贵不贵？去 NYU 方便吗？
```

处理规则：
- 单意图：调用一个领域 Agent
- 多意图：并行调用多个领域 Agent
- 使用 `asyncio.gather` 或等价并发方式
- 某个 Agent 失败不阻塞其他成功结果
- 最终回答必须说明哪些部分成功、哪些部分失败或降级
- `trace_summary` 记录每个 Agent 调用状态和耗时

### 8.5 Slot 继承与来源标记
Orchestrator 支持从 `profile_snapshot` 继承上下文。

Slot 来源：
- `user_explicit`：用户当前消息明确给出
- `session_memory`：从历史 session profile 继承
- `agent_inferred`：Agent 根据上下文推断
- `default`：系统默认值
- `rule_fallback`：关键词 fallback parser 识别

例子：
```json
{
  "target_area": {
    "value": "Astoria",
    "source": "session_memory",
    "confidence": 0.9
  }
}
```

### 8.6 缺槽与低置信度处理
缺槽规则：
- required slots 非空时，不调用领域 Agent
- 设置 `next_action=ask_follow_up`
- 一次只追问一个最重要字段
- 硬性必填槽位未补齐时，不进入业务执行

低置信度关键槽位规则：
- 关键槽位包括 `target_area`、`origin`、`destination`、`station_or_origin`、`mode`
- 关键槽位置信度 `< 0.75` 时不调用领域 Agent
- 设置 `next_action=confirm_slots`
- 追问用户确认

示例：
```json
{
  "next_action": "confirm_slots",
  "confirmation_question": "你说的 Williamsburg 是 Brooklyn 的 Williamsburg 吗？",
  "low_confidence_slots": [
    {
      "name": "target_area",
      "value": "Williamsburg",
      "confidence": 0.62
    }
  ]
}
```

### 8.7 权重更新顺序
权重更新必须先于业务查询执行。

执行顺序：
1. `Understand` 阶段识别权重变化
2. Orchestrator 调用 `profile-agent` 更新权重
3. 获取最新 `profile_snapshot`
4. 使用最新权重调用领域 Agent
5. 当前回答立即体现新权重
6. `/chat` 返回更新后的 `profile_snapshot`

例子：
```text
用户：我想看 Astoria，安全最重要，房租也不能太贵。
```

执行：
```text
1. target_area = Astoria
2. weight_safety 上调
3. weight_rent 上调
4. 更新 profile
5. 再调用 neighborhood-agent / housing-agent
```

### 8.8 直接回答、拒答与自我认知
Orchestrator 可以直接回答系统能力/使用说明类问题。

可以直接回答的问题：
- “你能做什么？”
- “怎么设置权重？”
- “怎么比较两个区域？”
- “你能查实时地铁吗？”

系统外无关问题使用固定模板拒答，不调用领域 Agent、不调用 MCP。

拒答模板：
```text
我主要是一个纽约租房与生活区域决策助手，可以帮你比较区域安全、租金、通勤、便利设施和娱乐设施。如果你愿意，可以告诉我你想了解的纽约区域。
```

自我认知模板：
```text
我是一个纽约租房与生活区域决策助手，主要帮助刚到纽约的人理解不同区域的安全、租金、通勤、便利设施和娱乐设施，并根据你的偏好逐步缩小候选居住区域。
```

规则：
- 不说自己是 GPT、GPT-4、Claude、Gemini 等底层模型
- 不回答和系统能力完全无关的问题
- 不为了闲聊调用领域 Agent 或 MCP

### 8.9 Respond 事实约束
`Respond` 阶段允许解释和总结，但关键事实数字必须保留原值。

规则：
- MCP / Domain Agent 返回的关键数字不能擅自改写
- 可以补充自然语言解释
- 可以给出“中等偏高”“便利设施较多”等相对判断
- 判断必须基于真实工具结果
- 不允许把缺失数据补成确定事实
- 数据不完整时必须说明不完整
- 不默认向用户展示 `confidence`

用户可见回答必须包含：
- 直接结论
- 关键数据
- 与用户偏好的关系
- 下一步建议或可追问方向
- 数据来源
- 数据时间戳 / 更新时间

### 8.10 低质量数据与降级回答
低质量或缺失数据采用“有可靠备用源才回答，否则说明无法可靠判断”。

规则：
- 首选数据源可用：正常回答
- 首选数据源失败，但有可靠备用源：使用备用源回答，并说明数据类型
- 没有可靠备用源：不输出确定结论
- 数据过旧：必须标注更新时间，并提醒可能不是实时情况
- 只适合作参考的数据必须明确说“只能作为参考”

示例：
```text
我现在没有拿到 Astoria 的实时房源数据，所以不能可靠判断当前可租房源数量。可以先用 HUD/Zillow 的租金基准估计区域租金水平，但这不能代表实时房源库存。
```

### 8.11 Conversation Summary
Orchestrator 保存短 `conversation_summary`，不默认保存完整聊天记录。

保存内容：
- 用户关注过的区域
- 当前主要偏好
- 关键约束
- 最近推荐方向
- 对后续理解有帮助的上下文

不保存：
- 完整聊天原文
- 完整 Prompt
- API Key
- 原始外部 API 响应全文

更新规则：
- 每轮对话后增量更新 summary
- summary 由 `profile-agent / mcp-profile` 持久化
- trace 中可保存脱敏后的 `message_preview`

### 8.12 Prompt 模板拆分
Orchestrator prompt 拆成多个模板。

MVP 模板：
- `understand_prompt`
- `respond_prompt`
- `summary_update_prompt`
- `boundary_prompt`

`understand_prompt`：
- intent 分类
- slot 抽取
- 权重解析
- missing slot 判断
- `next_action` 决策
- 严格 JSON 输出

`respond_prompt`：
- 基于真实数据回答
- 保留关键事实数字
- 不编造
- 不默认展示置信度

`summary_update_prompt`：
- 更新短 `conversation_summary`
- 只保留对后续决策有用的信息
- 不保存完整聊天

`boundary_prompt`：
- 系统能力介绍
- 自我认知
- 系统外问题拒答模板

### 8.13 MCP 与 Tool 选择边界
`understand_prompt` 不允许 LLM 直接决定 MCP 或 tool。

LLM 只输出：
- `domain`
- `task_type`
- `slots`
- `weight_updates`
- `missing_slots`
- `next_action`

后端规则决定：
- 调哪个领域 Agent
- 哪些 task_type 可以并行
- required slots 是什么

领域 Agent 决定：
- 调哪个 MCP
- 调哪个 tool
- 如何降级

Orchestrator 的 `understand_prompt` 不能输出或控制：
- `target_mcp`
- `tool_name`
- SQL
- 外部 API URL
- API Key
- 任意代码

说明：这里限制的是 Orchestrator 的一级理解 prompt。`housing-agent` 和 `neighborhood-agent` 的领域 SQL prompt 可以生成只读 SQL，但必须经过 MCP SQL Validator 校验后才能执行。

### 8.14 关键词 Fallback Parser
当 LLM 不可用或结构化输出失败时，Orchestrator 使用最小关键词 fallback parser。

触发条件：
- LLM JSON 解析失败
- Pydantic 校验失败并重试后仍失败
- LLM 服务不可用

MVP 关键词映射：

| 关键词 | task_type |
|---|---|
| 安全、犯罪、治安 | `neighborhood.crime_query` |
| 房租、租金、贵不贵、多少钱 | `housing.rent_query` |
| 房源、公寓、listing | `housing.listing_search` |
| 地铁、公交、通勤、多久到 | `transit.commute_time` |
| 下一班、什么时候来、发车 | `transit.next_departure` |
| 超市、药店、便利、健身房 | `neighborhood.convenience_query` |
| 酒吧、餐厅、咖啡、娱乐、夜生活 | `neighborhood.entertainment_query` |
| 推荐、比较、住哪里 | `recommendation.generate` |

fallback 输出必须标注：
```json
{
  "source": "rule_fallback"
}
```

### 8.15 Orchestrator 决策落库
Orchestrator 落库精简决策记录，用于 debug、demo 和复盘。

保存内容：
- `trace_id`
- `session_id`
- `message_preview`
- `understand_result`
- `selected_intents`
- `missing_slots`
- `next_action`
- `called_agents`
- `final_status`
- `latency_ms`
- `error_code`
- `created_at`

不保存：
- 完整 Prompt
- API Key
- 原始外部 API 响应全文
- 敏感内部上下文

用途：
- Debug Panel 展示 Agent 决策链
- 面试 Demo 展示 Orchestrator 设计
- 统计 intent 识别失败率
- 统计缺槽追问次数
- 统计不同 Agent 调用耗时

## 9. Domain Agent 详细设计
Domain Agent 是领域执行层，负责把 Orchestrator 下发的结构化任务转成领域内可执行计划。

适用服务：
- `housing-agent`
- `neighborhood-agent`
- `transit-agent`
- `profile-agent`

总体边界：
- Domain Agent 接收 `domain_user_query + task_type + slots + profile_snapshot + conversation_summary`
- Domain Agent 不直接面对用户
- Domain Agent 不生成最终用户回答
- Domain Agent 返回统一结构化结果给 Orchestrator
- Orchestrator 负责最终自然语言回复

### 9.1 Domain Agent 输入
Orchestrator 调用 Domain Agent 时，必须传递领域相关原始表达，不能只传 `task_type` 和 slots。

输入示例：
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
  "profile_snapshot": {},
  "conversation_summary": "用户正在评估 Astoria，比较关注安全。",
  "debug": false
}
```

多意图问题中，Orchestrator 需要拆分并传递 domain-specific query：
- 给 `neighborhood-agent`：`Astoria 安全吗？`
- 给 `housing-agent`：`Astoria 房租贵不贵？`
- 给 `transit-agent`：`Astoria 去 NYU 通勤方便吗？`

### 9.2 SQL Generation 使用范围
SQL generation 只用于数据分析型 Agent：
- `housing-agent`
- `neighborhood-agent`

不用于：
- `transit-agent`
- `profile-agent`

原因：
- `transit-agent` 依赖 MTA API、GTFS-RT、Bus Time 和短缓存，不适合 SQL 生成
- `profile-agent` 涉及 session/profile 状态写入，必须使用固定读写接口

### 9.3 Controlled SQL Generation Mode
`housing-agent` 和 `neighborhood-agent` 使用 Controlled SQL Generation Mode。

流程：
```text
Domain Agent
 -> 根据 task_type 动态注入相关 schema
 -> LLM 基于 schema 生成只读 SQL 或 unsupported_data_request
 -> MCP SQL Validator 校验 SQL
 -> MCP 使用只读数据库账号执行 SQL
 -> SQL rows 返回 Domain Agent
 -> Domain Agent 做结构化归纳
 -> Orchestrator 生成最终回答
```

关键规则：
- Domain Agent 可以生成 SQL
- Domain Agent 不能直接执行 SQL
- MCP 不生成 SQL，只负责校验和执行
- MCP 不能无条件执行 Domain Agent 生成的 SQL
- 用户需求无法由当前 schema 支持时，Domain Agent 返回 `unsupported_data_request`，不调用 MCP

### 9.4 动态 Schema 注入
SQL schema 按 `task_type` 运行时动态注入。

示例：
- `neighborhood.crime_query`：只注入犯罪/区域相关表
- `neighborhood.convenience_query`：只注入便利设施/区域相关表
- `neighborhood.entertainment_query`：只注入娱乐设施/区域相关表
- `housing.rent_query`：只注入租金市场/租金基准/区域表
- `housing.listing_search`：只注入房源快照/区域表

不注入无关表：
- `app_session_profile`
- `app_a2a_trace_log`
- `app_transit_realtime_prediction`
- 当前 task_type 不需要的其他业务表

目的：
- 降低 token 成本
- 减少选错表风险
- 降低误查敏感表风险
- 让 SQL 生成更稳定

### 9.5 SQL Prompt 结构
SQL 生成 prompt 由三部分组成：
```text
shared_sql_safety_prompt
+ domain_schema_prompt
+ domain_business_rules_prompt
+ domain_user_query
```

共享 SQL 安全规范：
- 只允许生成 `SELECT`
- 禁止 `SELECT *`
- 必须显式列出字段
- 必须使用参数化用户输入
- 必须带 `LIMIT`
- 默认 `LIMIT <= 50`
- 禁止 DDL/DML
- 禁止多语句
- 禁止查询非注入 schema 表
- 禁止查询敏感表
- 不确定时返回 `unsupported_data_request`

领域规则示例：
- `housing-agent`：房源默认 `listing_status=active`，租金查询优先市场聚合表，再 fallback 到 benchmark
- `neighborhood-agent`：安全问题必须带时间窗口，POI 问题优先分类聚合表，地图点位查询必须限制数量

### 9.6 SQL 输出 JSON Schema
Domain Agent 的 LLM 输出必须是严格 JSON，后端用 Pydantic 校验。

成功输出：
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

无法支持输出：
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

### 9.7 SQL 能力边界
允许：
- 白名单表之间 `JOIN`
- 常用聚合函数：`COUNT`、`AVG`、`MIN`、`MAX`、`SUM`
- `GROUP BY`
- `ORDER BY`
- 有限明细查询
- 少量白名单 PostGIS 函数

PostGIS 白名单：
- `ST_Within`
- `ST_DWithin`
- `ST_Intersects`

限制：
- `ST_DWithin` 最大半径建议 `2000m`
- 空间查询必须带 `LIMIT`
- 优先使用已有 `area_id` 字段
- 高成本空间聚合暂不做

暂不允许：
- 窗口函数
- 递归查询
- 复杂 CTE 链路
- `PERCENTILE_CONT`
- 自定义函数
- 任意 PostGIS 函数

### 9.8 参数化要求
Domain Agent 生成 SQL 时，用户输入必须参数化。

允许：
```json
{
  "sql": "SELECT area_id, area_name FROM app_area_dimension WHERE area_name ILIKE :target_area LIMIT 5",
  "params": {
    "target_area": "Astoria"
  }
}
```

不建议：
```json
{
  "sql": "SELECT area_id, area_name FROM app_area_dimension WHERE area_name = 'Astoria' LIMIT 5",
  "params": {}
}
```

规则：
- 用户输入值不能直接拼进 SQL 字符串
- SQL 使用命名参数
- 表名、字段名只能来自动态注入 schema 白名单
- MCP Validator 检查 SQL 是否包含明显硬编码用户值
- MCP 使用 SQLAlchemy/Text 或等价参数绑定方式执行

### 9.9 MCP SQL Validator
MCP 执行 SQL 前必须校验。

校验规则：
- 只允许 `SELECT`
- 禁止 `SELECT *`
- 禁止多语句
- 禁止 DDL/DML
- 只允许访问当前 task_type 白名单表
- 只允许访问白名单字段
- 禁止访问 session/profile/trace/debug 敏感表
- 必须带 `LIMIT`
- `LIMIT <= 50`
- 明细查询必须限制字段
- 数据库连接使用只读账号
- 设置 `statement_timeout`，建议 `3s`

Validator 拒绝时返回：
```json
{
  "status": "validation_error",
  "error": {
    "code": "SQL_VALIDATION_FAILED",
    "message": "SELECT * is not allowed.",
    "retryable": true
  }
}
```

### 9.10 SQL 重试规则
MCP Validator 拒绝 SQL 后，Domain Agent 最多重试 `3` 次。

流程：
```text
Domain Agent 生成 SQL
 -> MCP Validator 校验
 -> 如果拒绝，返回 validation_error + reason
 -> Domain Agent 根据 reason 重新生成 SQL
 -> 最多重试 3 次
 -> 仍失败则返回 unsupported_or_failed 给 Orchestrator
```

规则：
- 每次重试记录 `attempt_index`
- 不能无限循环
- 每次重试必须基于 validator 明确错误原因修正
- 第 3 次仍失败后停止
- Orchestrator 向用户说明当前无法安全查询该问题
- trace 记录重试次数和最终失败原因

### 9.11 No Data 流程
SQL 成功执行但没有返回数据时，MCP 返回 `no_data`。

MCP 返回：
```json
{
  "status": "no_data",
  "tool": "execute_readonly_sql",
  "data": [],
  "message": "Query executed successfully, but no rows were found.",
  "source_tables": ["app_crime_incident_snapshot"],
  "timestamp": "2026-04-24T12:00:00-04:00",
  "error": null
}
```

Domain Agent 返回：
```json
{
  "status": "no_data",
  "analysis_result": null,
  "data_available": false,
  "missing_data_reason": "SQL 查询成功，但结果为空。",
  "suggested_alternative": "可以改查近 90 天，或查看全部犯罪类型总数。",
  "source_tables": ["app_crime_incident_snapshot"]
}
```

Orchestrator 回答原则：
- 不能说“现实中没有发生”
- 只能说“当前数据库中没有找到匹配数据”
- 可以建议扩大时间窗口或改查更宽泛指标

### 9.12 Query Purpose
Domain Agent 可以输出多个 SQL query，每个 query 必须标记用途。

用途：
- `analysis`：用于回答和打分
- `display`：用于卡片、表格、列表
- `map_layer`：用于地图点位/热力层

规则：
- 每个 query 独立通过 MCP Validator
- 某个 query 失败不一定影响其他 query
- 最终结果标注哪些用途成功、哪些失败

示例：
```json
{
  "status": "sql_ready",
  "queries": [
    {
      "purpose": "analysis",
      "sql": "SELECT offense_category, COUNT(*) AS crime_count FROM app_crime_incident_snapshot WHERE area_id = :area_id GROUP BY offense_category LIMIT 20",
      "params": {
        "area_id": "QN0101"
      }
    },
    {
      "purpose": "map_layer",
      "sql": "SELECT incident_id, offense_category, latitude, longitude FROM app_crime_incident_snapshot WHERE area_id = :area_id LIMIT 50",
      "params": {
        "area_id": "QN0101"
      }
    }
  ]
}
```

### 9.13 展示结果缓存
Domain Agent 不把所有展示型 rows 都返回给 Orchestrator。

规则：
- `analysis` 查询结果返回给 Orchestrator
- `display` 查询结果写入 Redis/PostgreSQL 缓存，返回 `display_result_id`
- `map_layer` 查询结果写入 `app_map_layer_cache` 或 Redis，返回 `map_layer_id`
- 前端通过直连 API 拉取展示型数据

返回示例：
```json
{
  "status": "success",
  "analysis_result": {
    "crime_count": 42,
    "top_categories": [
      {
        "crime_type": "PETIT LARCENY",
        "count": 18
      }
    ]
  },
  "display_refs": {
    "map_layer_id": "map_01H...",
    "display_result_id": "disp_01H..."
  },
  "source_tables": ["app_crime_incident_snapshot"]
}
```

### 9.14 业务默认值
Domain Agent prompt 包含业务默认值，并在输出中标记 `default_applied`。

默认值：

| 用户表达 | 默认解释 |
|---|---|
| “最近” | `window_days = 30` |
| “近期” | `window_days = 30` |
| “这几个月” | `window_days = 90` |
| “附近” | 默认目标区域边界内 |
| “周边” | 默认 `radius_meters = 1000` |
| “房源” | 默认 `listing_status = active` |
| “租金” | 默认按 `bedroom_type` 聚合 |
| “娱乐设施多吗” | 默认按 `poi_category` 分组统计 |
| “便利吗” | 默认按 convenience category 分组统计 |

Orchestrator 回答时可以说明：
```text
我按“最近 30 天”来理解你的问题。
```

### 9.15 领域内 Clarification
Domain Agent 允许在 domain/task_type 已明确，但领域内参数有歧义时返回 `clarification_required`。

适用场景：
- “严重犯罪”定义不明确
- “便宜房源”没有预算标准
- “附近”需要半径但用户问题对范围非常敏感
- “高端娱乐设施”没有明确分类标准

返回示例：
```json
{
  "status": "clarification_required",
  "clarification_reason": "用户提到'严重犯罪'，但当前 schema 可支持多个犯罪分类解释。",
  "clarification_question": "你说的严重犯罪是指抢劫、重罪袭击、入室盗窃，还是所有重罪类型？",
  "candidate_options": ["robbery", "felony_assault", "burglary", "all_felony"]
}
```

规则：
- Domain Agent 不直接问用户
- Orchestrator 统一把 clarification 转成用户追问
- 一级意图不明或硬性必填槽位缺失仍由 Orchestrator 处理

### 9.16 领域内 Fallback
Domain Agent 做有限领域内 fallback，并标记 `fallback_used`。

规则：
- 首选查询失败或 `no_data` 时，允许尝试有限备用查询
- 备用查询必须仍然属于当前业务问题
- 最多执行 1 次领域内 fallback
- 不能无限扩大范围
- 不能把不相关数据当作答案
- 必须说明 fallback 原因

示例：
- 房源明细无数据时 fallback 到区域租金市场表
- POI 分类聚合表无数据时 fallback 到 POI 快照点位统计
- 犯罪类型映射不确定时 fallback 到更宽泛的 NYPD 大类

### 9.17 LLM Failure Fallback
Domain Agent 只对宽泛问题做 LLM failure fallback。

LLM failure 包括：
- 模型服务不可用
- 输出不是合法 JSON
- JSON 不符合 schema
- 生成 SQL 连续 3 次未通过 MCP Validator

可 fallback 的宽泛问题：
- `Astoria 安全怎么样？`
- `Astoria 房租贵吗？`
- `Astoria 附近便利吗？`
- `Williamsburg 娱乐设施多吗？`

不可 fallback 的具体问题：
- `Astoria 晚上 10 点以后抢劫多吗？`
- `Astoria 过去 90 天偷窃数量是多少？`
- `LIC 1km 内有多少家 24 小时药店？`
- `Williamsburg 最近一个月 1BR 低于 2500 的 active listing 有几个？`

规则：
- 具体问题失败后不 fallback
- 返回“当前无法安全查询”
- 宽泛问题 fallback 必须标记 `fallback_used=true`
- Orchestrator 必须说明“这是降级后的概览结果”

### 9.18 SQL 结果归纳
SQL 结果返回后，Domain Agent 做结构化归纳，但不生成最终用户回答。

输出示例：
```json
{
  "status": "success",
  "result_type": "crime_count_by_type",
  "data_available": true,
  "key_metrics": {
    "total_count": 42,
    "top_category": "PETIT LARCENY"
  },
  "rows": [],
  "summary_text_template": "目标区域近 30 天共有 {total_count} 起匹配犯罪记录，其中最多的是 {top_category}。",
  "source_tables": ["app_crime_incident_snapshot"],
  "data_time_range": {
    "start": "2026-03-24",
    "end": "2026-04-24"
  }
}
```

Orchestrator 负责：
- 结合用户权重
- 结合多个 Domain Agent 结果
- 生成统一风格最终回答
- 决定下一步追问或建议

### 9.19 SQL Trace
Domain Agent 保存脱敏 SQL 和参数摘要到 trace。

保存：
- SQL 结构
- 参数摘要
- source tables
- validator 结果
- 重试次数
- 执行耗时

不保存：
- API Key
- 完整 Prompt
- 敏感内部上下文
- 未脱敏敏感参数

示例：
```json
{
  "trace_id": "trace_01H...",
  "agent": "neighborhood-agent",
  "task_type": "neighborhood.crime_query",
  "sql_redacted": "SELECT offense_category, COUNT(*) FROM app_crime_incident_snapshot WHERE area_id = :area_id GROUP BY offense_category LIMIT 20",
  "params_summary": {
    "area_id": "QN***"
  },
  "source_tables": ["app_crime_incident_snapshot"],
  "validation_status": "passed",
  "attempt_count": 1,
  "latency_ms": 220
}
```

### 9.20 Transit Agent 固定流程
`transit-agent` 不走 SQL generation。

固定流程：
1. 接收 Orchestrator 的结构化 task
2. 校验 slots：`origin`、`destination`、`mode`、`station_or_origin`
3. 缺少领域内必要信息时返回 `clarification_required`
4. 根据 `task_type` 调用固定 MCP tool
5. MCP 内部处理 MTA API、GTFS-RT、Bus Time 和 Redis 短缓存
6. `transit-agent` 归纳结构化结果
7. 返回 Orchestrator

固定映射：
- `transit.next_departure` -> `mcp-transit.get_next_departures`
- `transit.commute_time` -> `mcp-transit.get_realtime_commute` 或 static commute
- `transit.realtime_commute` -> `mcp-transit.get_realtime_commute`

### 9.21 Weather Agent 固定流程
`weather-agent` 不走 SQL generation。

固定流程：
1. 接收 Orchestrator 的结构化 task
2. 校验 slots：`target_area` 必填，`target_time` 可选
3. 如果缺少 `target_area`，返回 `clarification_required`
4. 根据 `task_type` 调用固定 MCP tool
5. MCP 内部处理 NWS `/points`、`forecastHourly` 和 Redis 短缓存
6. `weather-agent` 归纳结构化天气结果
7. 返回 Orchestrator

固定映射：
- `weather.current_query` -> `mcp-weather.get_area_weather_summary`
- `weather.forecast_query` -> `mcp-weather.get_weather_at_time`

规则：
- 默认查询当前到未来 6 小时
- 指定时刻查询时，返回最接近 `target_time` 的小时级 forecast period
- 天气不参与区域推荐打分，不更新五个推荐权重
- NWS 失败时返回 `dependency_failed`，不阻塞其他领域 Agent 成功结果

### 9.22 Profile Agent 固定流程
`profile-agent` 不走 SQL generation，不使用 LLM 自由写 profile。

固定 operations：
- `create_session`
- `get_profile`
- `update_slots`
- `update_weights`
- `save_conversation_summary`
- `save_recommendation`
- `save_trace_summary`
- `delete_session`，后续增强

规则：
- Orchestrator 负责抽取 slots / weights / summary
- `profile-agent` 负责校验、合并、冲突处理和持久化
- `mcp-profile` 负责实际读写 PostgreSQL
- `profile-agent` 不生成 SQL
- `profile-agent` 不直接回答用户

### 9.23 Domain Agent 统一 Envelope
所有 Domain Agent 使用统一基础 envelope，业务结果内容按领域变化。

基础结构：
```json
{
  "status": "success",
  "task_type": "neighborhood.crime_query",
  "domain": "neighborhood",
  "analysis_result": {},
  "display_refs": {},
  "data_available": true,
  "source": [],
  "source_tables": [],
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

状态枚举：
- `success`
- `no_data`
- `unsupported_data_request`
- `clarification_required`
- `validation_failed`
- `dependency_failed`
- `error`

规则：
- Orchestrator 只依赖统一 envelope 判断下一步
- `analysis_result` 可按领域自定义
- `display_refs` 存地图、房源列表、表格等展示数据引用
- 不直接生成最终用户回答

## 10. 数据与缓存
数据库：
- PostgreSQL + PostGIS
- 表结构以 `NYC_Agent_Data_Sources_API_SQL.md` 为准
- 空间相关逻辑优先使用 PostGIS，而不是在 Python 中手写地理判断

Redis 用途：
- MTA 实时通勤 `30-60秒`短缓存
- Overpass 查询限频
- 外部 API 请求去重
- 临时 Agent 中间结果缓存

APScheduler 用途：
- 同步 NYC Open Data
- 同步 RentCast 房源快照
- 同步/刷新 Overpass POI 分类
- 同步 MTA static GTFS 站点数据
- 清理过期实时通勤缓存和匿名日志

## 11. Data Sync Service 落地结构
`data-sync-service` 是独立数据管道服务，详细策略见：[NYC_Agent_Data_Sync_Design.md](</Users/jackiewen/Documents/NYC agent/NYC_Agent_Data_Sync_Design.md>)。

架构定位：
- 先于后端 Agent 落地
- 负责把外部数据稳定写入 PostgreSQL + PostGIS
- 不参与用户在线问答
- 不调用 LLM
- 不走 A2A
- 不作为 MCP 服务

### 11.1 代码目录
建议目录：

```text
services/data-sync-service/
  app/
    main.py
    api/
      routes_health.py
      routes_sync.py
    jobs/
      bootstrap.py
      sync_nta.py
      sync_nypd_crime.py
      sync_311.py
      sync_facilities.py
      sync_overpass.py
      sync_rentcast.py
      sync_zori_hud.py
      sync_mta_static.py
      aggregate_metrics.py
      build_map_layers.py
    clients/
      socrata_client.py
      overpass_client.py
      rentcast_client.py
      hud_client.py
      zori_client.py
      mta_static_client.py
    transforms/
      area_transform.py
      crime_transform.py
      poi_transform.py
      rental_transform.py
      transit_transform.py
    repositories/
      area_repo.py
      crime_repo.py
      poi_repo.py
      rental_repo.py
      transit_repo.py
      sync_log_repo.py
    spatial/
      geom_builder.py
      area_assignment.py
    scheduler.py
    settings.py
```

原则：
- `clients/` 只负责拉取外部数据
- `transforms/` 只负责字段清洗和标准化
- `repositories/` 只负责数据库写入
- `jobs/` 负责任务编排
- `spatial/` 负责 PostGIS 几何生成和空间归属 SQL
- 每个 job 可被 API 手动触发，也可被 APScheduler 调用

### 11.2 同步任务接口
MVP 接口：

```text
GET  /health
GET  /sync/jobs
GET  /sync/status
POST /sync/run/{job_name}
POST /sync/run-bootstrap
```

返回统一结构：
```json
{
  "success": true,
  "job_id": "sync_01H...",
  "job_name": "sync_nypd_crime",
  "status": "running",
  "message": "Job started."
}
```

规则：
- 手动触发立即创建 `app_data_sync_job_log`
- 长任务异步执行
- `/sync/status` 从 `app_data_sync_job_log` 读取最近状态
- RentCast 任务必须检查月度和单次 API 调用上限

### 11.3 Job 执行模板
所有同步任务遵循统一模板：

```text
1. create job log: running
2. load settings and quota
3. fetch source data
4. transform and validate fields
5. build geometry when coordinates exist
6. write business table
7. run spatial assignment if needed
8. run local aggregation
9. update map layer cache if needed
10. update job log: succeeded / partial / failed
```

失败处理：
- 可恢复错误记录 `partial`
- 不可恢复错误记录 `failed`
- 不把 API Key 或完整外部错误响应写入日志
- `rows_fetched / rows_written / api_calls_used` 必须落库

### 11.4 性能规则
数据同步性能规则：
- Socrata 使用分页拉取，默认 `SOCRATA_PAGE_SIZE=1000`
- 大批量写入使用批量 upsert，不逐行 commit
- PostGIS 空间归属放在数据库执行
- 空间归属前先生成 `geom`
- seed 区域同步时优先用 area filter / bbox 减少数据量
- Overpass 请求之间必须 sleep
- RentCast 不自动重试，不自动定时

数据库写入规则：
- 每个 job 使用短事务批次
- 单批建议 `500-2000` 行
- 写入后再跑聚合，避免边写边聚合
- GiST 索引用于空间查询
- 常用查询字段建立 B-tree 索引

### 11.5 面试讲解点
这部分可以在面试中描述为：

```text
I separated online agent serving from offline data ingestion. The data-sync-service handles API fetching, transformation, PostGIS geometry creation, spatial assignment, aggregation, map layer cache generation, and quota-aware sync logs. This makes the agent runtime stable because user queries only read prepared business tables.
```

## 12. SQL Validator 详细实现
SQL Validator 是 Domain Agent 生成 SQL 后的强制安全边界。

设计原则：
- Prompt 约束不是安全边界
- MCP Validator 才是最终执行边界
- Validator 通过才允许数据库执行
- 数据库账号必须是只读账号

### 12.1 技术选择
MVP 使用：
- `sqlglot`：解析 SQL AST
- `SQLAlchemy text()`：参数绑定执行
- Pydantic：校验 Domain Agent SQL JSON
- PostgreSQL read-only role：数据库权限限制

不建议只用正则：
- 正则难以可靠识别嵌套查询、别名、函数和多语句
- 正则可作为辅助检查，但不能作为唯一 Validator

### 12.2 Validator 输入
MCP 接收：

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

说明：
- `allowed_tables` 和 `allowed_columns` 由 task_type 的动态 schema 注入生成
- MCP 不相信 LLM 输出的白名单，MCP 端也必须按 `task_type` 重新计算/校验白名单
- 请求里的白名单可用于 trace，但最终以 MCP 本地配置为准

### 12.3 校验步骤
Validator 顺序：

1. Parse SQL
2. 确认只有一条语句
3. 确认语句类型是 `SELECT`
4. 禁止 `SELECT *`
5. 提取所有表名，检查是否在白名单
6. 提取所有列名，检查是否在白名单
7. 检查函数白名单
8. 检查是否存在 `LIMIT`
9. 检查 `LIMIT <= 50`
10. 检查用户输入是否使用命名参数
11. 检查是否访问敏感表
12. 检查 PostGIS 函数和半径限制
13. 通过后用只读数据库账号执行

敏感表永远禁止：
- `app_session_profile`
- `app_session_recommendation`
- `app_a2a_trace_log`
- `app_data_sync_job_log`
- 任何 debug / secret / config 表

### 12.4 允许与禁止
允许：
- `SELECT`
- 白名单表之间 `JOIN`
- `COUNT / AVG / MIN / MAX / SUM`
- `GROUP BY`
- `ORDER BY`
- `LIMIT`
- `ST_Within`
- `ST_DWithin`
- `ST_Intersects`

禁止：
- `SELECT *`
- 多语句
- `INSERT / UPDATE / DELETE`
- `DROP / ALTER / TRUNCATE`
- `UNION`，MVP 暂不开放
- 递归 CTE
- 窗口函数
- 自定义函数
- 任意 PostGIS 函数
- 无 `LIMIT` 明细查询

### 12.5 PostGIS 限制
PostGIS 白名单：
- `ST_Within`
- `ST_DWithin`
- `ST_Intersects`

规则：
- `ST_DWithin` 半径最大 `2000m`
- 空间查询必须带 `LIMIT`
- 优先使用 `area_id`
- 大范围空间聚合不进 MVP
- 地图点位结果最多返回 `50` 条，更多结果走预生成 `map_layer_id`

### 12.6 参数化检查
规则：
- 用户输入值必须出现在 `params`
- SQL 中使用 `:param_name`
- 不允许把用户输入直接拼入 SQL 字符串
- 表名和字段名不能来自用户输入

示例允许：
```sql
WHERE area_id = :area_id
```

示例拒绝：
```sql
WHERE area_name = 'Astoria'
```

说明：
- 对于 area_id 这类系统内部标准 ID，可以作为参数值
- MCP 仍然检查参数名是否被 SQL 使用
- 未使用参数或缺失参数都拒绝

### 12.7 执行安全
数据库执行层必须设置：

```sql
SET statement_timeout = '3s';
SET default_transaction_read_only = on;
```

数据库账号：
- 只授予业务查询表 `SELECT`
- 不授予 session/profile/trace/debug 表权限
- 不授予 DDL/DML 权限

执行结果：
- rows 为空：返回 `no_data`
- Validator 拒绝：返回 `SQL_VALIDATION_FAILED`
- SQL 超时：返回 `DB_TIMEOUT`
- DB 异常：返回 `DB_ERROR`

### 12.8 错误格式
Validator 错误：

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

Domain Agent 可基于 `message/details.rule` 最多重试 3 次。

### 12.9 性能策略
性能规则：
- Validator AST 解析必须在执行前完成
- `LIMIT` 是硬性要求
- 所有空间查询依赖 GiST 索引
- 高频聚合优先查预聚合表
- 地图层优先查 `app_map_layer_cache`
- SQL 执行超过 3 秒直接失败
- 失败不自动扩大查询范围

### 12.10 面试讲解点
这部分可以在面试中描述为：

```text
The domain agents can generate SQL for flexible analytical questions, but they never execute SQL directly. Every query goes through an MCP-level SQL validator based on sqlglot AST parsing, table and column allowlists, parameter checks, PostGIS function restrictions, LIMIT enforcement, read-only database roles, and statement timeouts.
```

## 13. 后端 Monorepo 代码组织
整个项目采用 monorepo，多个独立服务共享 schema、client、配置和日志模块。

### 13.1 顶层目录
建议目录：

```text
NYC agent/
  backend/
    services/
      api-gateway/
      orchestrator-agent/
      housing-agent/
      neighborhood-agent/
      transit-agent/
      weather-agent/
      profile-agent/
      mcp-housing/
      mcp-safety/
      mcp-amenity/
      mcp-entertainment/
      mcp-transit/
      mcp-weather/
      mcp-profile/
      data-sync-service/
    shared/
      schemas/
      clients/
      config/
      db/
      logging/
      tracing/
      prompts/
      sql_validation/
      geo/
    migrations/
    docker/
    scripts/
    tests/
  frontend/
  docs/
```

原则：
- 每个服务可独立启动
- 共享协议放 `shared/`
- 服务内部只保留自己的业务逻辑
- prompts 版本化保存
- SQL Validator 代码集中复用
- migrations 独立于服务，避免每个服务各自建表

### 13.2 shared 模块
`shared/schemas/`：
- Gateway request/response envelope
- A2A envelope
- Domain Agent envelope
- MCP envelope
- error code enums

`shared/clients/`：
- A2A client wrapper
- MCP client wrapper
- HTTP client with timeout/retry

`shared/config/`：
- `.env` 加载
- service URL 配置
- API key 配置
- feature flags

`shared/db/`：
- async SQLAlchemy engine
- session factory
- read-only DB helper
- migration helpers

`shared/logging/`：
- JSON structured logging
- trace_id 注入
- request_id/session_id 关联

`shared/tracing/`：
- trace event model
- trace writer
- latency timer

`shared/prompts/`：
- orchestrator prompts
- domain SQL prompts
- shared SQL safety prompt
- boundary templates

`shared/sql_validation/`：
- sqlglot parser wrapper
- allowlist config
- validator rules
- validator error model

`shared/geo/`：
- bbox helper
- GeoJSON conversion
- PostGIS helper SQL

### 13.3 服务统一结构
每个 FastAPI 服务使用统一结构：

```text
service-name/
  app/
    main.py
    routes/
    service/
    models/
    settings.py
  Dockerfile
  pyproject.toml
```

每个服务必须提供：
- `GET /health`
- `GET /ready`
- structured logs
- request timeout
- dependency config

Agent 服务额外提供：
- `/agent/info`
- `/debug/run`，仅 `DEBUG=true`

MCP 服务额外提供：
- `/tools`
- `/tools/{tool_name}/schema`

### 13.4 配置管理
配置分层：
- `.env.example`：所有 key 占位
- `.env.local`：本地开发
- Docker Compose env：服务间 URL
- service `settings.py`：Pydantic Settings 读取配置

规则：
- API Key 只从环境变量读取
- 不写入日志
- 不返回给 debug 接口
- RentCast 默认关闭自动同步
- NWS 不需要 API Key，但 `NWS_USER_AGENT` 必须配置，否则 `mcp-weather` 不进入 ready 状态
- DEBUG 默认关闭

### 13.5 稳定运行策略
运行稳定性要求：
- 所有外部 HTTP 调用必须设置 timeout
- 所有外部 API client 必须有明确错误类型
- 所有服务依赖用 `/ready` 检查
- 数据库 migration 先于服务启动
- Redis 不可用时，实时通勤可以降级但不能崩溃
- LLM 不可用时，Orchestrator 和 Domain Agent 返回可解释错误或有限 fallback
- MCP SQL Validator 拒绝时，不执行 SQL

### 13.6 Docker Compose 启动顺序
推荐启动顺序：

```text
postgres
redis
migrations
data-sync-service
mcp-profile
mcp-housing
mcp-safety
mcp-amenity
mcp-entertainment
mcp-transit
mcp-weather
profile-agent
housing-agent
neighborhood-agent
transit-agent
weather-agent
orchestrator-agent
api-gateway
frontend
```

规则：
- `postgres` 必须先健康
- migrations 成功后再启动业务服务
- `data-sync-service` 可独立运行 bootstrap
- MCP 服务启动时检查数据库连接
- Agent 服务启动时检查对应 MCP 可用
- Gateway `/ready` 检查 Orchestrator、Profile Agent、Postgres、Redis

### 13.7 测试策略
MVP 测试优先级：
1. SQL Validator 单元测试
2. data-sync transform 单元测试
3. MCP `execute_readonly_sql` 集成测试
4. Orchestrator 缺槽/追问测试
5. Domain Agent SQL JSON schema 测试
6. `/chat` 端到端 smoke test
7. bootstrap seed 数据可用性测试

必须覆盖：
- `SELECT *` 被拒绝
- 非白名单表被拒绝
- 无 `LIMIT` 被拒绝
- 超大 `LIMIT` 被拒绝
- DDL/DML 被拒绝
- no-data 正确返回
- RentCast 超额保护生效

### 13.8 面试讲解点
这部分可以在面试中描述为：

```text
The backend is organized as a monorepo of independent FastAPI services. I separated gateway, orchestration, domain agents, MCP tools, and data sync. Shared schemas, clients, prompts, SQL validation, logging, and tracing live in common modules, which keeps the services independent but consistent.
```

## 14. LLM 配置
LLM Provider 做成可配置：
- 默认：OpenAI
- 可选：Anthropic、Gemini、Ollama

建议接口：
- `LLM_PROVIDER=openai`
- `OPENAI_API_KEY=`
- `OPENAI_MODEL=`

使用原则：
- 槽位抽取和追问：小模型优先
- 最终解释和推荐理由：较强模型
- 工具结果必须优先于模型猜测
- 缺失数据时必须追问或标注不确定

## 15. 错误处理与降级
通用策略：
- 外部 API 失败时返回可解释错误
- 不编造数据
- 所有工具调用返回 `source/timestamp/confidence`

实时通勤降级：
- 优先使用 MTA 实时数据
- 失败时使用静态 GTFS 或常规通勤时间
- 明确标注“非实时”
- 不承诺下一班车实时准确性

天气数据降级：
- 优先使用 NWS hourly forecast
- NWS 失败时先返回 Redis 中未严重过期的缓存，并标注 `cached`
- 无缓存时说明天气服务暂时不可用
- 天气失败不阻塞租房、区域、安全、通勤等主链路回答

租房数据降级：
- 优先 RentCast 房源
- 无法获取实时房源时使用租金基准和历史/参考数据
- `data_quality` 必须标注 `realtime/reference/estimated/benchmark`

## 16. MVP 实现顺序
1. 建 PostgreSQL + PostGIS + Redis
2. 建 migration，创建业务表、PostGIS 字段、索引和 `app_data_sync_job_log`
3. 实现 `data-sync-service` 骨架、`/sync/run-bootstrap`、`/sync/status`
4. 同步 NTA、NYPD、Overpass/Facilities、少量 RentCast seed、MTA static
5. 跑空间归属、聚合任务和 seed 地图图层缓存
6. 用验证 SQL 确认 seed 区域数据可查
7. 实现 SQL Validator 和 `execute_readonly_sql`
8. 实现 `mcp-housing`、`mcp-safety`、`mcp-amenity`、`mcp-entertainment`
9. 实现 `housing-agent`、`neighborhood-agent` 的动态 schema 注入和 SQL generation pipeline
10. 实现 `mcp-profile`、`profile-agent` 和 `api-gateway /sessions`
11. 实现 `orchestrator-agent` 的意图识别、`target_area` 追问、权重更新、`domain_user_query` 拆分
12. 实现 `mcp-transit` 和 `transit-agent` 的实时下一班/下两班查询
13. 实现 `mcp-weather` 和 `weather-agent` 的目标区域天气查询
14. 接入 A2A 调度并完成 `/chat` 端到端闭环
15. 加错误处理、缓存、日志、测试和 README Demo 流程

## 17. 生产演进路线
MVP 后可演进：
- Redis Stream / Celery / RQ 替代 APScheduler 单机任务
- API Gateway 增加 JWT/OAuth、限流、审计
- MCP 服务拆分独立部署和水平扩容
- 增加 OpenTelemetry、Prometheus、Grafana
- 增加 CI/CD 与数据库 migration
- 增加 PostGIS 索引优化和地理查询缓存
