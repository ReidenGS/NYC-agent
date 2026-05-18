# NL-to-SQL Agent Migration Plan

本文档用于沉淀后续关于 `nl-to-sql-agent` 的讨论、设计决策、文档修改方案与代码迁移计划。  
所有后续修改方案优先写入本文档，再同步更新 `docs/`，最后进入代码实现。

## 1. 当前目标

将现有系统中负责自然语言到 SQL 计划生成的能力，逐步集中到一个新的 `nl-to-sql-agent`。

新的 `nl-to-sql-agent` 负责：

- 接收 orchestrator 已识别出的 `domain`、`task_type`、`slots`、`domain_user_query` 和执行上下文。
- 根据不同 intent 使用外部 skill 机制进行渐进式 prompt 披露。
- 生成只读 SQL plan。
- 调用对应 MCP 服务执行受控只读 SQL。
- 将 SQL 执行结果归一化为结构化结果返回 orchestrator。

新的 `nl-to-sql-agent` 不负责：

- 不做用户原始意图识别。
- 不做槽位追问。
- 不直接生成最终自然语言回复。
- 不管理 profile/session 状态。
- 不绕过 MCP SQL Validator。

最终自然语言回复仍由 `orchestrator-agent` 的 respond 阶段负责。

## 2. Agent 合并范围

本迁移只覆盖当前文档中明确属于 SQL generation 的数据分析型 agent。

应迁移的 SQL generation 职责：

- `housing-agent`
- `neighborhood-agent`

不应迁移的 agent：

- `profile-agent`
- `transit-agent`
- `weather-agent`

原因：

- `profile-agent` 负责匿名 session、slots、weights、conversation summary、last response refs 等状态管理，使用固定 `mcp-profile` 读写接口，不生成 SQL。
- `transit-agent` 负责整理 `mcp-transit` 固定工具调用参数，处理 MTA GTFS-RT、Bus Time、静态/实时通勤和 Redis 短缓存，不走 SQL generation。
- `weather-agent` 负责整理 `mcp-weather` 固定工具调用参数，处理 National Weather Service API、grid 映射、天气缓存和 fallback，不走 SQL generation。

因此，目标不是把所有 domain agent 合并为一个 agent，而是把 `housing-agent` 与 `neighborhood-agent` 的 SQL 生成与 SQL 执行编排职责迁移到 `nl-to-sql-agent`。

## 3. 第一阶段迁移范围

第一阶段只迁移 `neighborhood-agent` 中的以下能力：

- `neighborhood.entertainment_query`
- `neighborhood.convenience_query`

第一阶段暂不迁移：

- `neighborhood.crime_query`
- `area.metrics_query`
- `housing.rent_query`
- `housing.listing_search`
- `transit.*`
- `weather.*`
- `profile.*`

第一阶段目标链路：

```text
orchestrator-agent
  -> nl-to-sql-agent
       -> 外部 skill 渐进式 prompt 披露
       -> 生成 SQL plan
       -> 调用 mcp-amenity / mcp-entertainment 执行只读 SQL
       -> 返回结构化 rows + display refs
  -> orchestrator-agent respond 节点生成最终用户回答
```

其他未迁移 intent 暂时继续走 legacy agent。

## 4. 外部 Skill 机制

本迁移计划使用外部 skill 机制承载 SQL prompt，而不是继续将 SQL prompt 硬编码在业务代码中。

Phase 1 初版曾采用 domain 级 `references/neighborhood-sql.md` 迁移现有 prompt。根据后续讨论，当前实现已进入 Phase 1.1：按公共规则、intent 规则和数据表字段三层拆分，`nl-to-sql-agent` 根据 `task_type` 只注入本次任务需要的 reference。

### 4.1 当前 skill 结构

Phase 1.1 当前采用以下结构：

```text
nyc-nl-to-sql/
  SKILL.md
  references/
    common-sql-rules.md
    common-output-contract.md
    common-area-contract.md
    intent-neighborhood-convenience.md
    intent-neighborhood-entertainment.md
    table-app-area-dimension.md
    table-app-map-poi-snapshot.md
    table-app-area-convenience-category-daily.md
    table-app-area-entertainment-category-daily.md
```

其中：

- `SKILL.md` 只写 skill 的使用边界、加载规则和输出要求。
- `common-*.md` 承载只读 SQL 安全规则、输出契约和 area 使用规则。
- `intent-*.md` 承载不同 `task_type` 必须生成哪些 query、结果类型和点位规则。
- `table-*.md` 承载对应真实数据库表的允许字段、字段含义和常见过滤方式。
- `references/neighborhood-sql.md` 属于 Phase 1 初版遗留文件，当前 loader 不再使用；后续可在确认无回滚需求后删除。
- housing references 在 Phase 2 迁移 housing 时按同样三层结构加入。

### 4.2 当前渐进式披露粒度

当前按 `task_type` 披露 prompt，而不是一次性注入整个 neighborhood schema。

加载规则：

```text
task_type = neighborhood.entertainment_query
  -> common-sql-rules.md
  -> common-output-contract.md
  -> common-area-contract.md
  -> intent-neighborhood-entertainment.md
  -> table-app-area-dimension.md
  -> table-app-area-entertainment-category-daily.md
  -> table-app-map-poi-snapshot.md

task_type = neighborhood.convenience_query
  -> common-sql-rules.md
  -> common-output-contract.md
  -> common-area-contract.md
  -> intent-neighborhood-convenience.md
  -> table-app-area-dimension.md
  -> table-app-area-convenience-category-daily.md
  -> table-app-map-poi-snapshot.md

task_type = housing.rent_query
task_type = housing.listing_search
  -> Phase 2 再定义
```

这样做的目的：

- 公共规则仍可复用。
- 不同任务只看到自己需要的数据字段。
- 降低 token 成本和跨表误用概率。
- 保持 `nl-to-sql-agent` 服务边界、A2A 契约和 MCP 执行链路不变。
- MCP tool 由 LLM 在 SQL plan 中选择；代码只校验 tool registry、domain 和 target table。

### 4.3 后续拆分方向

后续迁移 crime、area metrics 和 housing 时，继续沿用当前三层结构：

- common SQL safety
- common output contract
- common area contract
- domain neighborhood / housing
- intent entertainment / convenience / crime / area metrics / rent / listing
- schema-specific references

新增 intent 或 table reference 必须保持兼容：拆分前后的 SQL plan 输出契约不应变化。

### 4.4 `nl-to-sql-agent` 代码侧职责

`nl-to-sql-agent` 代码侧保留：

- skill 选择逻辑
- skill 加载接口
- prompt 组装顺序
- SQL plan schema
- SQL 安全校验前置逻辑
- MCP tool registry、tools/call 执行与结果归一化逻辑

prompt 的领域规则、表结构说明、SQL 示例和 intent-specific 约束优先放入外部 skill reference。

代码中不再保留全局 `DATABASE_SCHEMA_STRING`，也不再向 planner prompt 注入通用 `database_schema` 变量；schema/字段信息只来自 `skill_loader.py` 按 `task_type` 选出的 reference 文件。

## 5. SQL 与地图点位关键约束

所有 SQL 必须遵守现有 MCP SQL Validator 边界：

- 只允许只读查询。
- 禁止 DDL、DML、多语句 SQL。
- 禁止绕过 MCP 执行 SQL。
- 必须使用参数化输入。
- 必须遵守表/字段白名单。
- 必须遵守 LIMIT 规则。
- SQL 失败或无数据时返回结构化状态，不编造现实结论。

第一阶段尤其要保证地图点位规则：

- 前端只认 `display_refs.map_points` 和 `display_refs.map_layer_ids`。
- 娱乐/便利点位必须来自 `app_map_poi_snapshot`。
- 点位结果必须包含 `latitude` 和 `longitude`。
- `target_area_id` 是下游查询主键，`target_area_name` 只用于展示。
- 不允许直接使用整句用户 query 做 area embedding 检索；区域规范化仍由 orchestrator 的 Area RAG 完成。

## 6. Orchestrator 职责保持不变

`orchestrator-agent` 仍负责：

- 用户原始意图识别。
- 槽位抽取。
- Area RAG 与 `target_area_id` 规范化。
- 缺槽判断和追问。
- A2A 调度。
- 聚合 agent 结果。
- 最终自然语言回复。
- profile 持久化触发。

`orchestrator-agent` 不应因为引入 `nl-to-sql-agent` 而直接生成 SQL 或直接调用 MCP。

## 7. 迁移阶段

### Phase 1: neighborhood entertainment / amenity

- 新增 `nl-to-sql-agent` 服务设计。
- 定义 orchestrator -> `nl-to-sql-agent` A2A 契约。
- 定义 `nl-to-sql-agent` -> MCP 执行与返回结构。
- 将 `neighborhood.entertainment_query` 和 `neighborhood.convenience_query` 路由到 `nl-to-sql-agent`。
- 保持其他 intent 继续走 legacy agent。

### Phase 1.2: `nl-to-sql-agent` MCP Client 化

- 保留 `skills/nyc-nl-to-sql` 作为 prompt source。
- `skill_loader.py` 继续根据 `task_type` 加载本地 skill references，完成渐进式 prompt 披露。
- 将 `nl-to-sql-agent` 的 MCP 执行从手写 HTTP `/tools/*` 调用迁移为 MCP Client `tools/call`。
- MCP Server 只负责 tools、SQL Validator、只读执行、表/字段白名单和错误归一化。
- Phase 1.2 不使用服务端 prompt 能力，不改变 orchestrator A2A 契约和 Phase 1 已支持的业务能力。

### Phase 2: housing SQL intent

- Phase 2.1 先迁移 `housing.rent_query`。
- Phase 2.2 再迁移 `housing.listing_search`。
- 暂不迁移或保留 `rent_comparison`、`market_freshness` 这类 housing 扩展结果类型。
- 收敛 `housing-agent` 逻辑，确认是否完全删除或保留兼容壳。

### Phase 3: neighborhood 剩余 SQL intent

- 迁移 `neighborhood.crime_query`。
- 迁移 `area.metrics_query`。
- 收敛 `neighborhood-agent` 逻辑，确认是否完全删除或保留兼容壳。

### Phase 4: 清理 legacy SQL agents

- 删除已完全替代的 SQL generation 逻辑。
- 清理 Docker Compose 服务、端口、文档、测试、健康检查和 debug 路由。
- 保留 `transit-agent`、`weather-agent`、`profile-agent` 的固定工具调用模式。

## 8. 需要更新的文档

后续正式改文档时，至少需要更新：

- `docs/NYC_Agent_Backend_Tech_Framework.md`
- `docs/NYC_Agent_A2A_Protocol.md`
- `docs/NYC_Agent_API_Schema_Contract.md`
- `docs/NYC_Agent_Prompt_Design.md`
- `docs/NYC_Agent_MCP_Design.md`

更新原则：

- 先记录目标架构。
- 再记录 Phase 1 兼容路径。
- 明确 transit/weather/profile 不属于 SQL agent 合并范围。
- 明确 `nl-to-sql-agent` 使用外部 skill 渐进式披露。
- 明确 orchestrator 仍是自然语言最终回复方。

## 9. 现有代码资产迁移清单

当前已确认的现有 prompt 资产：

- `shared/prompts/neighborhood/sql_plan_prompt.txt`
- `shared/prompts/housing/sql_plan_prompt.txt`

第一阶段已迁移：

- `shared/prompts/neighborhood/sql_plan_prompt.txt`
  -> 外部 skill 的公共规则、intent 规则和 table reference

当前 active reference：

- `references/common-sql-rules.md`
- `references/common-output-contract.md`
- `references/common-area-contract.md`
- `references/intent-neighborhood-entertainment.md`
- `references/intent-neighborhood-convenience.md`
- `references/table-app-area-dimension.md`
- `references/table-app-map-poi-snapshot.md`
- `references/table-app-area-entertainment-category-daily.md`
- `references/table-app-area-convenience-category-daily.md`

`references/neighborhood-sql.md` 是 Phase 1 初版遗留文件，当前实现不再加载。

Phase 2 再迁移：

- `shared/prompts/housing/sql_plan_prompt.txt`
  -> 外部 skill 的 housing common / intent / table references

现有服务代码中需要重点阅读和复用的文件：

- `services/neighborhood-agent/app/llm_planner.py`
- `services/neighborhood-agent/app/neighborhood_logic.py`
- `services/neighborhood-agent/app/main.py`
- `services/housing-agent/app/llm_planner.py`
- `services/housing-agent/app/housing_logic.py`
- `shared/nyc_agent_shared/prompt_loader.py`
- `shared/nyc_agent_shared/llm_client.py`
- `shared/nyc_agent_shared/mcp_protocol.py`
- `services/orchestrator-agent/app/nodes/plan_execute.py`
- `services/orchestrator-agent/app/a2a_adapter.py`

第一阶段不应重写 prompt 内容。  
第一阶段应优先保持 prompt 语义不变，只改变 prompt 的外部存放位置和加载方式。

## 10. 需要新增的文件与目录

### 10.1 外部 skill

新增外部 skill 目录，具体位置待实现前确认。候选位置：

```text
skills/nyc-nl-to-sql/
  SKILL.md
  references/
    common-sql-rules.md
    common-output-contract.md
    common-area-contract.md
    intent-neighborhood-convenience.md
    intent-neighborhood-entertainment.md
    table-app-area-dimension.md
    table-app-map-poi-snapshot.md
    table-app-area-convenience-category-daily.md
    table-app-area-entertainment-category-daily.md
```

如果最终决定使用 Codex `$CODEX_HOME/skills` 机制，则 skill 目录可能不放入项目仓库。  
但从项目可复现性考虑，建议先把 skill 作为项目资产放入仓库，再由运行环境配置加载路径。

### 10.2 新 agent 服务

新增服务目录：

```text
services/nl-to-sql-agent/
  Dockerfile
  requirements.txt
  app/
    __init__.py
    config.py
    main.py
    skill_loader.py
    llm_planner.py
    mcp_router.py
    result_normalizer.py
    schemas.py
```

职责：

- `skill_loader.py`：根据 `task_type` 读取外部 skill reference。
- `llm_planner.py`：拼接 prompt，调用 LLM，解析 SQL plan JSON。
- `mcp_router.py`：根据 SQL plan 中的 `mcp_tool` 选择 MCP 服务和工具，并校验 registry。
- `result_normalizer.py`：将 MCP rows 转成 orchestrator 可消费的结构化结果和 `display_refs`。
- `schemas.py`：定义 A2A payload、SQL plan、query result、error schema。

### 10.3 可选共享代码

如果现有 MCP client/helper 已经在 shared 中可复用，优先复用。  
如没有合适抽象，可新增：

```text
shared/nyc_agent_shared/skill_prompt_loader.py
shared/nyc_agent_shared/sql_plan_schema.py
```

新增共享代码必须服务于多 agent 复用，不能为了 Phase 1 过早抽象。

## 11. 需要修改的代码位置

### 11.1 `docker-compose.yml`

新增 `nl-to-sql-agent` 服务：

- 建议端口：`8016`
- 依赖环境变量：LLM provider/model/API key、skill 路径、MCP URLs
- 依赖服务：`mcp-amenity`、`mcp-entertainment`、后续 `mcp-safety`、`mcp-housing`

Phase 1 不删除 `neighborhood-agent`。

### 11.2 `services/orchestrator-agent`

修改 orchestrator 的 agent 路由逻辑：

- `neighborhood.entertainment_query` -> `nl-to-sql-agent`
- `neighborhood.convenience_query` -> `nl-to-sql-agent`
- 其他 `neighborhood.*` 暂时继续 -> `neighborhood-agent`
- `housing.*` 暂时继续 -> `housing-agent`
- `transit.*` 继续 -> `transit-agent`
- `weather.*` 继续 -> `weather-agent`
- `profile.*` 继续 -> `profile-agent`

重点文件：

- `services/orchestrator-agent/app/nodes/plan_execute.py`
- `services/orchestrator-agent/app/a2a_adapter.py`
- `services/orchestrator-agent/app/config.py`

### 11.3 `shared/nyc_agent_shared`

可能需要更新或复用：

- A2A schema / task type enum
- MCP request/response helper
- prompt loader
- LLM client

原则：

- 不让 orchestrator 直接知道 SQL plan 内部细节。
- LLM 可以在注入的 MCP tool catalog 内选择 `mcp_tool`；代码负责校验。
- 不把数据库连接引入 agent。

### 11.4 `services/neighborhood-agent`

Phase 1 不删除该服务。  
只在 orchestrator 改路由后，让 entertainment / convenience 不再默认进入该服务。

后续 neighborhood 剩余 intent 迁移完成后再考虑：

- 删除对应 SQL prompt 依赖。
- 删除被迁移的 handler。
- 或保留兼容壳直到所有调用方切换完成。

### 11.5 MCP 服务

Phase 1 不改变 MCP 的安全职责。

需要确认并复用：

- `services/mcp-amenity/app/sql_policy.py`
- `services/mcp-entertainment/app/sql_policy.py`
- `services/mcp-amenity/app/mcp_server.py`
- `services/mcp-entertainment/app/mcp_server.py`

如果 `nl-to-sql-agent` 生成的 SQL plan 与现有 MCP tool 入参不兼容，优先适配 `nl-to-sql-agent`，不要放宽 MCP Validator。

## 12. MCP 工具调用规则

Phase 1 当前实现是代码根据 `task_type` 直接选择 MCP 服务，并通过本地 skill references 组装 prompt、通过 HTTP `/tools/execute_readonly_sql` 执行 SQL。Phase 1.2 后调整为：prompt 仍由本地 skill 管理，LLM 根据注入的 MCP tool catalog 在 SQL plan 中选择 `mcp_tool`，工具执行迁移为 MCP Client `tools/call`。

目标结构：

```text
orchestrator-agent
  -> A2A
nl-to-sql-agent
  -> local skill references 生成 SQL prompt
  -> 注入 MCP SQL Tool Catalog
  -> LLM 生成 SQL plan，并为每条 query 选择 mcp_tool
  -> MCP Client tools/call
mcp-* server
  -> execute_readonly_sql
  -> SQL Validator
  -> readonly DB execution
```

Phase 1.2 初始 MCP SQL Tool Catalog：

```text
neighborhood.entertainment_query -> mcp-entertainment.tools/execute_readonly_sql
neighborhood.convenience_query   -> mcp-amenity.tools/execute_readonly_sql
```

后续 MCP SQL Tool Catalog：

```text
neighborhood.crime_query -> mcp-safety.tools/execute_readonly_sql
area.metrics_query       -> 待定，可能由 mcp-safety / mcp-amenity / mcp-entertainment 的只读 SQL tool 组合执行
housing.rent_query       -> mcp-housing.tools/execute_readonly_sql
housing.listing_search   -> mcp-housing.tools/execute_readonly_sql
```

LLM 可以决定：

- SQL plan 中包含几条 query。
- 每条 query 的 `target_table`、`purpose`、`sql`、`params`、`execute_when`。
- 每条 query 的 `mcp_tool`，但必须来自注入的 MCP SQL Tool Catalog。

LLM 不能决定：

- 调用 catalog 之外的 MCP tool。
- 是否绕过 MCP。
- 是否访问非白名单表。
- 是否执行写操作。
- 是否生成最终用户回复。
- 是否写入 profile。

MCP 仍负责：

- 暴露 executable tools。
- SQL Validator。
- 只读数据库访问。
- 表/字段白名单。
- 参数绑定。
- timeout。
- 错误码归一化。
- SQL 脱敏 trace。

当前代码状态：

- `mcp-*` 服务已经提供 FastMCP tool 注册，并且部分服务挂载 `/mcp`。
- `nl-to-sql-agent` 使用 `python_a2a.mcp.MCPClient` 调用 `/mcp/` 的 `tools/call`。
- legacy `housing-agent`、`neighborhood-agent` 当前仍主要通过 `httpx` 调用 `/tools/execute_readonly_sql`，Phase 1.2 不一次性重构 legacy agent。

## 13. A2A 契约草案

### 13.1 Orchestrator -> `nl-to-sql-agent`

请求 content 草案：

```json
{
  "task_type": "neighborhood.entertainment_query",
  "intent": "neighborhood.entertainment_query",
  "trace_id": "trace_xxx",
  "session_id": "sess_xxx",
  "source_agent": "orchestrator-agent",
  "target_agent": "nl-to-sql-agent",
  "payload": {
    "domain": "neighborhood",
    "domain_user_query": "Hell's Kitchen 附近有什么娱乐设施？",
    "slots": {
      "target_area_id": {
        "value": "MN0402",
        "source": "area_rag",
        "confidence": 0.95
      },
      "target_area_name": {
        "value": "Hell's Kitchen",
        "source": "area_rag",
        "confidence": 0.95
      }
    },
    "domain_context": {
      "result_limit": 20,
      "map_points_required": true
    }
  }
}
```

### 13.2 `nl-to-sql-agent` -> Orchestrator

响应 content 草案：

```json
{
  "task_type": "neighborhood.entertainment_query",
  "status": "success",
  "payload": {
    "domain": "neighborhood",
    "structured_results": {
      "summary": [],
      "details": []
    },
    "display_refs": {
      "map_points": [],
      "map_layer_ids": ["entertainment"]
    },
    "sources": []
  },
  "confidence": {
    "overall": 0.85
  },
  "data_quality": {
    "source": "mcp-entertainment",
    "freshness": "cached_or_snapshot",
    "confidence": 0.8
  },
  "error": null
}
```

原则：

- Orchestrator respond 阶段继续基于 agent 返回内容生成最终自然语言。
- 前端 API 契约尽量不变。
- `display_refs` 必须保持可被现有前端消费。
- 不向前端暴露未脱敏 SQL 或完整 prompt。

## 14. SQL Plan 输出草案

LLM 输出的 SQL plan 应是严格 JSON，不包含 Markdown。

草案：

```json
{
  "task_type": "neighborhood.entertainment_query",
  "queries": [
    {
      "name": "entertainment_category_summary",
      "purpose": "summary",
      "sql": "SELECT ... WHERE area_id = :target_area_id LIMIT 20",
      "params": {
        "target_area_id": "MN0402"
      },
      "expected_columns": ["category", "poi_count"]
    },
    {
      "name": "entertainment_poi_points",
      "purpose": "map_points",
      "sql": "SELECT ... latitude, longitude ... WHERE area_id = :target_area_id LIMIT 20",
      "params": {
        "target_area_id": "MN0402"
      },
      "expected_columns": ["name", "poi_type", "latitude", "longitude"]
    }
  ]
}
```

Phase 1 校验规则：

- `queries` 至少 1 条。
- 每条 query 必须有 `target_table`、`domain`、`purpose`、`sql`、`params`。
- `purpose=detail` 且查询 `app_map_poi_snapshot` 的 query 必须返回 `latitude`、`longitude`。
- SQL 必须通过基础只读检查和 MCP Validator。
- 不允许 SQL plan 自带 MCP 服务名作为真实路由依据。

## 15. 测试与验收范围

### 15.1 文档验收

- 根目录迁移文档完整记录目标架构、范围、排除项、Phase 1 边界。
- `docs/` 中不再把 transit/weather/profile 描述为 SQL generation 合并对象。
- `docs/` 中明确 `nl-to-sql-agent` 的职责和 MCP 路由边界。

### 15.2 Skill 验收

- 外部 skill 能被 `nl-to-sql-agent` 读取。
- `neighborhood.entertainment_query` 只加载公共规则、entertainment intent 和 entertainment/POI/area 表字段。
- `neighborhood.convenience_query` 只加载公共规则、convenience intent 和 convenience/POI/area 表字段。
- Planner prompt 不再包含硬编码全局 `DATABASE_SCHEMA_STRING`，也不再注入 `database_schema` 变量。
- `SKILL.md` 清楚声明不适用于 transit/weather/profile。

### 15.3 Agent 单元测试

至少覆盖：

- `neighborhood.entertainment_query` 加载 entertainment reference，且不加载 convenience category 表 reference。
- `neighborhood.convenience_query` 加载 convenience reference，且不加载 entertainment category 表 reference。
- `PLAN_PROMPT.input_variables` 不包含 `database_schema`。
- unsupported task type 返回结构化错误。
- LLM 输出非法 JSON 时返回 `LLM_PARSE_FAILED`。
- SQL plan 缺少 `latitude/longitude` 时返回 `SQL_VALIDATION_FAILED` 或内部 plan validation error。
- SQL plan 必须包含 `mcp_tool`，并由 router 校验 tool registry、domain 和 target table。

### 15.4 集成测试

至少覆盖：

- `/api/chat` 查询 entertainment，返回 `display_refs.map_points`。
- `/api/chat` 查询 convenience，返回 `display_refs.map_points`。
- Hell's Kitchen / `MN0402` 的 area id 不错配。
- legacy `neighborhood.crime_query` 仍走旧 `neighborhood-agent`。
- `transit.*`、`weather.*`、`profile.*` 路由不受影响。

### 15.5 本地验证

验证命令后续根据实际测试文件确定。  
至少应包含：

- Python 单元测试。
- API health check。
- 一次真实 `/api/chat` entertainment 请求。
- 一次真实 `/api/chat` convenience 请求。

## 16. 实施顺序

后续实际修改必须按以下顺序：

1. 更新本迁移文档。
2. 更新 `docs/` 正式文档。
3. 创建外部 skill 草案，并迁移 `neighborhood` SQL prompt。
4. 新增 `nl-to-sql-agent` 服务骨架。
5. 实现 skill loader、LLM planner、MCP router、result normalizer。
6. 修改 orchestrator Phase 1 路由。
7. 添加测试。
8. 本地运行验证。
9. 再评估是否进入 Phase 2。

## 17. 当前待确认问题

后续设计前仍需确认：

- 外部 skill 的实际存放位置：项目仓库内 `skills/nyc-nl-to-sql`，还是 `$CODEX_HOME/skills`。
- 已决定 Phase 1 使用项目仓库内 `skills/nyc-nl-to-sql`，容器内通过 `NL_TO_SQL_SKILL_ROOT` 加载。
- 已决定 Phase 1 直接从 orchestrator 路由 entertainment / convenience 到 `nl-to-sql-agent`，`neighborhood-agent` 保留作为 legacy 兼容服务。
- 已决定 Phase 1 返回结构保持 neighborhood SQL result 兼容：`payload.sql_plan`、`payload.executions`、`payload.neighborhood_result`。
- Phase 1 的验收用例和回归测试范围。

## 18. Phase 1.1 Prompt 拆分

Phase 1 初版 `references/neighborhood-sql.md` 是 domain 级 prompt，一次性包含便利、娱乐、POI 和共享区域表字段。Phase 1.1 将其拆为公共规则、intent 规则和 table schema 三层。

目标：

- 公共 SQL 规则复用。
- 不同 `task_type` 只注入自己需要的数据表字段。
- 降低 token 成本和跨表误用概率。
- 保持 SQL plan JSON 输出契约不变。
- 保持 MCP 路由仍由代码按 `task_type` 决定。

第一阶段拆分后的 skill 结构：

```text
skills/nyc-nl-to-sql/
  SKILL.md
  references/
    common-sql-rules.md
    common-output-contract.md
    common-area-contract.md
    intent-neighborhood-convenience.md
    intent-neighborhood-entertainment.md
    table-app-area-dimension.md
    table-app-map-poi-snapshot.md
    table-app-area-convenience-category-daily.md
    table-app-area-entertainment-category-daily.md
```

加载规则：

```text
neighborhood.convenience_query
  -> common-sql-rules.md
  -> common-output-contract.md
  -> common-area-contract.md
  -> intent-neighborhood-convenience.md
  -> table-app-area-dimension.md
  -> table-app-area-convenience-category-daily.md
  -> table-app-map-poi-snapshot.md

neighborhood.entertainment_query
  -> common-sql-rules.md
  -> common-output-contract.md
  -> common-area-contract.md
  -> intent-neighborhood-entertainment.md
  -> table-app-area-dimension.md
  -> table-app-area-entertainment-category-daily.md
  -> table-app-map-poi-snapshot.md
```

职责边界：

- `common-sql-rules.md`：只读 SQL、安全、LIMIT、参数化、LLM 只能提出 allowlist 内的 MCP tool。
- `common-output-contract.md`：SQL plan JSON schema 和字段要求。
- `common-area-contract.md`：`area_id` 使用、`area_name` 展示、不做 Area RAG。
- `intent-*.md`：每个任务必须生成哪些 query、query purpose、POI 坐标要求。
- `table-*.md`：表用途、allowed columns、字段含义、常见过滤/排序和禁用方式。

已完成代码变更：

- `services/nl-to-sql-agent/app/skill_loader.py` 按 `task_type` 选择 reference 文件。
- `services/nl-to-sql-agent/app/llm_planner.py` 移除了全局 `DATABASE_SCHEMA_STRING` 和 prompt 变量 `database_schema`。
- `tests/unit/test_nl_to_sql_agent_phase1.py` 覆盖 entertainment/convenience 的差异化 reference 加载，并断言 planner 不再需要 `database_schema`。

已核对真实数据库字段：

- `app_area_dimension`
- `app_map_poi_snapshot`
- `app_area_convenience_category_daily`
- `app_area_entertainment_category_daily`

当前 table reference 只保留 Phase 1 生成 SQL 需要的字段。真实表中存在但当前任务不需要的 geometry 字段没有注入 prompt，避免 LLM 误用。

Phase 1.1 不迁移 `neighborhood.crime_query`。犯罪相关 table prompt 等 Phase 2 再加入。

## 19. Phase 2 Housing 迁移计划

Phase 2 开始迁移 `housing-agent` 的 SQL generation 能力。迁移顺序已确认：

1. Phase 2.1 先迁移 `housing.rent_query`。
2. Phase 2.2 再迁移 `housing.listing_search`。

### 19.1 Phase 2.1 范围

Phase 2.1 只覆盖 `housing.rent_query` 中已经确认要保留的两类能力：

- `rent_range`：查询某区域、某户型或默认户型概览的租金范围。
- `budget_fit`：判断用户预算是否可能租到目标区域/户型，并使用预算内 active listing 数量辅助判断。

Phase 2.1 暂不迁移：

- `rent_comparison`：多区域租金对比。
- `market_freshness`：数据新鲜度查询。
- `housing.listing_search`：具体房源清单，放到 Phase 2.2。

暂不迁移项不作为 `nl-to-sql-agent` Phase 2.1 的目标能力。后续如要恢复，需要单独设计 intent prompt、结果结构和测试用例。

### 19.2 Phase 2.1 返回结构

Phase 2.1 必须保持兼容现有 `housing-agent` 返回结构，避免 orchestrator/frontend 同步大改。

返回 payload 继续使用：

```text
payload.sql_plan
payload.executions
payload.housing_result
payload.housing_result.derived_metrics
payload.housing_result.listing_candidates
```

`housing_result` 继续包含：

- `status`
- `domain = housing`
- `task_type = housing.rent_query`
- `housing_result_type`
- `data_available`
- `sql_results`
- `derived_metrics`
- `data_context`
- `listing_candidates`
- `source_tables`
- `default_applied`

`budget_fit` 判断规则沿用现有 `housing-agent`：

- `fit`
- `partial_fit`
- `over_budget`
- `unknown`

### 19.3 Phase 2.1 Skill 拆分

Housing prompt 拆分沿用 Phase 1.1 的方式：公共规则、intent 规则、table reference 三层。

新增或复用的 reference：

```text
skills/nyc-nl-to-sql/
  references/
    common-sql-rules.md
    common-output-contract.md
    common-area-contract.md
    intent-housing-rent.md
    table-app-area-dimension.md
    table-app-area-rental-market-daily.md
    table-app-area-rent-benchmark-monthly.md
    table-app-area-rental-listing-snapshot.md
```

`housing.rent_query` 加载规则：

```text
housing.rent_query
  -> common-sql-rules.md
  -> common-output-contract.md
  -> common-area-contract.md
  -> intent-housing-rent.md
  -> table-app-area-dimension.md
  -> table-app-area-rental-market-daily.md
  -> table-app-area-rent-benchmark-monthly.md
  -> table-app-area-rental-listing-snapshot.md
```

`table-app-area-rental-listing-snapshot.md` 在 Phase 2.1 只注入 `budget_fit` 所需字段，不注入默认不应暴露的联系人字段。联系人字段留到 Phase 2.2 设计 `listing_search` 时再明确规则。

### 19.4 Phase 2.1 SQL 行为

`housing.rent_query` 的 SQL plan 应支持：

- 查询 `app_area_rental_market_daily` 获取 `rent_min`、`rent_median`、`rent_max`、`listing_count`。
- market daily 无数据时 fallback 到 `app_area_rent_benchmark_monthly`。
- 用户提供 `budget_monthly` 且 `bedroom_type` 时，查询 `app_area_rental_listing_snapshot` 中预算内 active listing。
- 用户问整体租金水平但未给 `bedroom_type` 时，默认查询 `studio`、`1br`、`2br` 概览。
- 用户问预算是否够但未给 `bedroom_type` 时，返回 `clarification_required`，由 orchestrator 追问。

SQL plan 限制：

- 一次最多 3 条 SQL。
- `purpose` 只能是 `analysis`、`detail`、`fallback`。
- 必须只读 `SELECT`。
- 必须显式列字段，禁止 `SELECT *`。
- 必须参数化用户输入。
- 必须带 `LIMIT`。
- Phase 2 housing 不默认添加“最近 30 天”这类时间过滤；`LIMIT` / `listing_limit` 表示数据库结果数量窗口，不表示时间窗口。数据新鲜度只作为返回 metadata 或后续 `market_freshness` 任务处理。

### 19.5 MCP 工具调用与 fallback 决策

Phase 2.1 工具调用链路：

```text
housing.rent_query
  -> orchestrator-agent
  -> nl-to-sql-agent
  -> MCP Client calls mcp-housing.execute_readonly_sql
```

已确认不做自动 legacy fallback：

- `nl-to-sql-agent` 对 `housing.rent_query` 失败时，不自动回退到 legacy `housing-agent`。
- SQL validation、MCP execution 或结果归一化失败时，返回结构化错误。
- 这样可以避免同一个 intent 在两条路径上出现不一致行为，并让测试暴露迁移问题。

Phase 2.1 完成前：

- `housing.listing_search` 继续走 legacy `housing-agent`。
- `housing-agent` 服务继续保留。

### 19.6 Phase 2.2 `housing.listing_search`

Phase 2.2 迁移 `housing.listing_search`，目标是把“查具体房源清单”的 SQL generation + MCP execution 链路从 legacy `housing-agent` 迁到 `nl-to-sql-agent`。

Phase 2.2 覆盖：

- 查询某区域的具体 rental listings。
- 支持 `area_id`、`bedroom_type`、`budget_monthly`、`listing_limit`。
- 默认优先返回 active listings。
- 返回 listing 点位，供前端地图展示。
- 继续保持兼容现有 `housing-agent` 的 `housing_result` 结构。

Phase 2.2 不覆盖：

- 联系人电话/中介姓名查询。
- 主动刷新 RentCast 外部 API。
- 复杂排序偏好之外的自然语言筛选，例如采光、隔音、房东评价、虫害等当前 schema 不支持字段。
- 多区域 listing 对比。

#### 19.6.1 返回结构

Phase 2.2 继续使用：

```text
payload.sql_plan
payload.executions
payload.housing_result
payload.housing_result.listing_candidates
payload.housing_result.derived_metrics
```

`housing_result` 中：

- `task_type = housing.listing_search`
- `housing_result_type = listing_candidates`
- `listing_candidates` 放具体房源 rows。
- `derived_metrics.matching_listing_count` 使用返回的 listing 数量。
- `data_context.source_type = listing_snapshot`
- `data_context.not_realtime_inventory` 在 fallback 到非 active listing 时为 `true`。

前端地图依赖：

- `display_refs.map_points` 必须能从 `listing_candidates` 生成。
- listing rows 必须包含 `latitude`、`longitude`。
- 点位 id 使用 `listing_id`。

#### 19.6.2 Skill 拆分

新增 intent reference：

```text
skills/nyc-nl-to-sql/
  references/
    intent-housing-listing-search.md
```

`housing.listing_search` 加载规则：

```text
housing.listing_search
  -> common-sql-rules.md
  -> common-output-contract.md
  -> common-area-contract.md
  -> intent-housing-listing-search.md
  -> table-app-area-dimension.md
  -> table-app-area-rental-listing-snapshot.md
```

如 listing search 需要在无 active listing 时返回区域租金背景，可后续再注入 `table-app-area-rental-market-daily.md`；Phase 2.2 默认不注入 market table，避免把 listing search 混成 rent analysis。

#### 19.6.3 SQL 行为

Phase 2.2 的 primary query：

- `target_table = app_area_rental_listing_snapshot`
- `purpose = detail`
- `execute_when = always`
- `expected_result = listing_candidates`
- 默认过滤 `area_id = :area_id`
- 如果有 `bedroom_type`，过滤 `bedroom_type = :bedroom_type`
- 如果有 `budget_monthly`，过滤 `monthly_rent <= :budget_monthly`
- 默认过滤 `listing_status = :active_status`
- 默认排序 `monthly_rent ASC, last_seen_date DESC`
- 默认 `LIMIT 5`，最大 `LIMIT 10`
- 不默认添加 `last_seen_date >= 最近 30 天` 这类时间过滤；`listing_limit` 只控制返回房源数量。

必须返回字段：

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

默认禁止返回字段：

- `listing_agent_name`
- `listing_agent_phone`
- `raw_source`
- `geom`

#### 19.6.4 Active listing fallback

Phase 2.2 保留 legacy 行为：优先返回 `listing_status = active`。

如果 active listing 无数据，可以执行 fallback query 查询最近看到的 listing：

- fallback query 仍只查 `app_area_rental_listing_snapshot`。
- fallback query 不加 `listing_status = active`。
- fallback query 排序 `last_seen_date DESC, monthly_rent ASC NULLS LAST`。
- fallback 结果必须标记：
  - `availability = stale_or_unknown`
  - `not_realtime_inventory = true`
  - `data_quality = reference`
  - `fallback_used = true`

不允许把 fallback listing 描述成实时可租库存。

#### 19.6.5 槽位规则

`housing.listing_search` 必需：

- `target_area` / `area_id`

`bedroom_type` 规则：

- 如果用户明确问某户型房源，必须使用该 `bedroom_type`。
- 如果用户没有提供 `bedroom_type`，Phase 2.2 先返回 `clarification_required`，由 orchestrator 追问。
- 暂不默认混查所有户型，避免返回不符合用户预期的房源清单。

`budget_monthly` 规则：

- 如果用户提供预算，必须加入 `monthly_rent <= :budget_monthly`。
- 如果用户没有预算，可以返回该区域/户型 active listing，但最终回答要标注“未按预算筛选”。

`listing_limit` 规则：

- 用户未指定：5。
- 用户指定 1-10：使用用户指定值。
- 用户指定超过 10：截断为 10，并在 `default_applied` 或结果 metadata 中记录。

#### 19.6.6 MCP 路由与 legacy fallback

Phase 2.2 工具调用链路：

```text
housing.listing_search
  -> orchestrator-agent
  -> nl-to-sql-agent
  -> MCP Client calls mcp-housing.execute_readonly_sql
```

和 Phase 2.1 一致，不做自动 legacy fallback：

- `nl-to-sql-agent` 对 `housing.listing_search` 失败时，不自动回退到 legacy `housing-agent`。
- SQL validation、MCP execution 或结果归一化失败时，返回结构化错误。

Phase 2.2 完成后：

- `housing.rent_query` 和 `housing.listing_search` 都路由到 `nl-to-sql-agent`。
- `housing-agent` 可进入收敛评估：删除 SQL generation 逻辑、保留兼容壳，或在确认无调用方后删除服务。

#### 19.6.7 Phase 2.2 验收

单元测试至少覆盖：

- `housing.listing_search` 只加载 listing search 所需 reference。
- `housing.listing_search` 不加载 rent market / benchmark reference。
- `housing.listing_search` MCP 路由到 `mcp-housing`。
- orchestrator 将 `housing.listing_search` 路由到 `nl-to-sql-agent`。
- 缺少 `bedroom_type` 时返回 `clarification_required`。
- SQL plan 不返回 `listing_agent_name`、`listing_agent_phone`、`raw_source`、`geom`。
- detail query 必须包含 `latitude`、`longitude`。
- active listing 无数据时执行 fallback query，并标记 `not_realtime_inventory = true`。

集成测试至少覆盖：

- 具体房源问题返回兼容 `payload.housing_result.listing_candidates`。
- 有预算时 SQL 使用 `monthly_rent <= :budget_monthly`。
- 返回的 listing rows 可生成 `display_refs.map_points`。
- fallback listing 不被描述为实时库存。

Phase 2.2 之前不改 `listing_search` 路由。

### 19.7 Phase 2.1 验收

单元测试至少覆盖：

- `housing.rent_query` 只加载 housing rent 所需 reference。
- `housing.rent_query` 不加载 entertainment/convenience reference。
- `housing.rent_query` MCP 路由到 `mcp-housing`。
- orchestrator 将 `housing.rent_query` 路由到 `nl-to-sql-agent`。
- orchestrator 仍将 `housing.listing_search` 路由到 legacy `housing-agent`。
- `budget_fit` 缺少 `bedroom_type` 时返回 `clarification_required`。
- planner prompt 不注入全局 `DATABASE_SCHEMA_STRING` 或 `database_schema`。

集成测试至少覆盖：

- 租金范围问题返回兼容 `payload.housing_result.derived_metrics`。
- 预算是否够问题返回 `budget_fit`。
- fallback benchmark 路径保留 `benchmark_only` / `fallback_used` 标记。
- `housing.listing_search` 在 Phase 2.1 后仍可通过 legacy `housing-agent` 工作。
