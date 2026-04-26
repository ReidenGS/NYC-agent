# NYC Agent 后端落地状态

本文记录当前已经落地的后端服务链路，方便后续 Codex / Claude 并行开发时对齐。

## 1. 当前已接入服务

| 服务 | 端口 | 职责 | 当前状态 |
| --- | --- | --- | --- |
| `api-gateway` | `8000` | 前端唯一 HTTP 入口，负责 session/chat/profile/debug API | 已接入远程 `orchestrator-agent`，失败时保留本地 mock fallback |
| `orchestrator-agent` | `8010` | 主 Agent，负责会话理解、缺槽追问、profile 读取/更新、后续 Domain Agent 调度入口 | 已实现最小链路：session、profile、chat、prompt debug |
| `housing-agent` | `8011` | 租房领域 Agent，负责生成 housing SQL plan、调用 MCP SQL、返回结构化租金/预算匹配结果 | 已接入 Orchestrator 的租金/预算问题；支持 GPT-4o SQL planner，可自动 fallback |
| `neighborhood-agent` | `8012` | 区域画像 Agent，负责安全、便利设施、娱乐设施和区域概览 SQL plan | 已接入 Orchestrator 的安全/便利/娱乐问题；支持 GPT-4o SQL planner，可自动 fallback |
| `transit-agent` | `8013` | 通勤领域 Agent，负责下一班车、实时/缓存通勤时间工具调用 | 已接入 Orchestrator 的地铁/公交/通勤问题 |
| `profile-agent` | `8014` | 用户画像状态 Agent，负责把 Orchestrator 的 profile 任务转成 MCP 工具调用 | 已实现 A2A `/a2a` 入口 |
| `weather-agent` | `8015` | 天气领域 Agent，负责当前天气和小时预报工具调用 | 已接入 Orchestrator 的天气问题 |
| `mcp-sql` | `8020` | 通用只读 SQL MCP，按 domain 白名单校验并执行 SQL | 已支持 `housing/safety/amenity/entertainment` 表白名单，当前 housing 已使用 |
| `mcp-transit` | `8025` | Transit 固定工具 MCP，读取站点维表、实时预测表和通勤缓存表 | 已实现站点匹配、下一班车查询、通勤缓存查询 |
| `mcp-profile` | `8026` | Profile MCP 工具服务，负责 session/profile 的读写 | 已实现 Postgres 优先持久化，数据库不可用时自动 memory fallback |
| `mcp-weather` | `8027` | Weather 固定工具 MCP，调用 National Weather Service API | 已实现当前天气和小时预报 |
| `data-sync-service` | `8030` | 数据同步与入库任务 | Claude 已完成主要同步任务，继续沿用同一 Postgres |
| `postgres` | `5432` | PostGIS 数据库 | 统一数据库，不要为新服务另起 DB |
| `redis` | `6379` | 缓存/短期状态预留 | 已在 compose 中存在 |

## 2. 当前服务调用链路

```text
Frontend
  -> api-gateway
    -> orchestrator-agent
      -> housing-agent
        -> mcp-sql
      -> neighborhood-agent
        -> mcp-sql
      -> transit-agent
        -> mcp-transit
      -> weather-agent
        -> mcp-weather
      -> profile-agent
        -> mcp-profile
```

当前 `api-gateway` 默认读取：

```env
USE_REMOTE_ORCHESTRATOR=true
ORCHESTRATOR_AGENT_URL=http://localhost:8010
```

在 Docker Compose 内部会使用：

```env
ORCHESTRATOR_AGENT_URL_DOCKER=http://orchestrator-agent:8010
PROFILE_AGENT_URL_DOCKER=http://profile-agent:8014
MCP_PROFILE_URL_DOCKER=http://mcp-profile:8026
HOUSING_AGENT_URL_DOCKER=http://housing-agent:8011
NEIGHBORHOOD_AGENT_URL_DOCKER=http://neighborhood-agent:8012
TRANSIT_AGENT_URL_DOCKER=http://transit-agent:8013
WEATHER_AGENT_URL_DOCKER=http://weather-agent:8015
MCP_SQL_URL_DOCKER=http://mcp-sql:8020
MCP_TRANSIT_URL_DOCKER=http://mcp-transit:8025
MCP_WEATHER_URL_DOCKER=http://mcp-weather:8027
DATABASE_URL_SQL_DOCKER=postgresql+psycopg://nyc_agent:nyc_agent_password@postgres:5432/nyc_agent
PROFILE_STORE_BACKEND=postgres
PROFILE_STATEMENT_TIMEOUT_MS=3000
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
USE_LLM_SQL_PLANNER=true
HOUSING_AGENT_SQL_MODEL=gpt-4o
NEIGHBORHOOD_AGENT_SQL_MODEL=gpt-4o
```

## 3. 已实现接口

### `orchestrator-agent`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 `profile-agent` 是否可用 |
| `GET` | `/debug/prompts` | 查看已加载 prompt |
| `POST` | `/sessions` | 创建 session 和 profile |
| `GET` | `/sessions/{session_id}/profile` | 查询 profile |
| `PATCH` | `/sessions/{session_id}/profile` | 更新 profile slots/weights |
| `POST` | `/chat` | 最小主 Agent 对话入口 |

### `profile-agent`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 `mcp-profile` 是否可用 |
| `GET` | `/debug/prompts` | 查看 profile prompt |
| `POST` | `/a2a` | 接收 Orchestrator 的 A2A 任务 |

### `housing-agent`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 `mcp-sql` 是否可用 |
| `GET` | `/debug/prompts` | 查看 housing prompt |
| `POST` | `/a2a` | 接收 Orchestrator 的 housing A2A 任务 |

当前支持：

| task_type | 能力 |
| --- | --- |
| `housing.rent_query` | 查询租金区间、预算匹配、benchmark fallback |
| `housing.listing_search` | 查询 active listing 候选房源 |

SQL planner 模式：

- `OPENAI_API_KEY` 有值且 `USE_LLM_SQL_PLANNER=true` 时，优先调用 GPT-4o 生成 SQL plan。
- LLM 输出必须是严格 JSON，并通过轻量 plan schema 校验。
- `mcp-sql` 仍是最终安全边界，会校验 SQL 白名单、LIMIT、敏感表和只读规则。
- LLM 请求失败、输出不合格、API key 为空时，自动 fallback 到 deterministic SQL plan。

### `neighborhood-agent`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 `mcp-sql` 是否可用 |
| `GET` | `/debug/prompts` | 查看 neighborhood prompt |
| `POST` | `/a2a` | 接收 Orchestrator 的 neighborhood A2A 任务 |

当前支持：

| task_type | 能力 |
| --- | --- |
| `neighborhood.crime_query` | 查询安全指标、犯罪类型分布、特定犯罪类型数量 |
| `neighborhood.convenience_query` | 查询便利设施分类数量和样例点位 |
| `neighborhood.entertainment_query` | 查询娱乐设施分类数量和样例点位 |
| `area.metrics_query` | 查询区域安全/便利/娱乐/交通概览指标 |

SQL planner 模式：

- `OPENAI_API_KEY` 有值且 `USE_LLM_SQL_PLANNER=true` 时，优先调用 GPT-4o 生成 SQL plan。
- LLM 输出必须是严格 JSON，并通过轻量 plan schema 校验。
- `mcp-sql` 仍是最终安全边界，会按 `safety/amenity/entertainment` domain 白名单执行校验。
- LLM 请求失败、输出不合格、API key 为空时，自动 fallback 到 deterministic SQL plan。

### `mcp-sql`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 Postgres 是否可用 |
| `GET` | `/schema/{domain}` | 查看 domain 白名单表和 SQL 规则 |
| `POST` | `/tools/execute_readonly_sql` | 校验并执行只读 SQL |

当前 SQL Validator 规则：

- 只允许 `SELECT` / `WITH`
- 禁止 `SELECT *`
- 禁止 DDL / DML / 多语句 / SQL 注释
- 强制 `LIMIT`
- `LIMIT <= 50`
- 按 `domain` 校验白名单表
- 禁止访问 session/profile/trace/debug 等敏感表
- 使用 SQLAlchemy 参数绑定执行
- 设置 `statement_timeout`

### `transit-agent`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 `mcp-transit` 是否可用 |
| `GET` | `/debug/prompts` | 查看 transit prompt |
| `POST` | `/a2a` | 接收 Orchestrator 的 transit A2A 任务 |

当前支持：

| task_type | 能力 |
| --- | --- |
| `transit.next_departure` | 根据 mode/route/stop/direction 查询下一班车 |
| `transit.commute_time` | 查询缓存通勤时间 |
| `transit.realtime_commute` | 查询实时/缓存通勤结果 |

### `mcp-transit`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 Postgres 是否可用 |
| `GET` | `/tools` | 查看可用工具 |
| `POST` | `/tools/resolve_station_or_stop` | 根据站名/模式匹配站点 |
| `POST` | `/tools/get_next_departures` | 查询实时预测表中的下一班车 |
| `POST` | `/tools/get_realtime_commute` | 查询短期通勤结果缓存 |

当前限制：

- 先读取现有 `app_transit_*` 表，不直接拉 MTA API。
- 如果实时预测表或缓存表为空，会返回 `no_data`，不会编造车次。
- 后续可以在 `mcp-transit` 内部补 GTFS-RT / Bus Time 拉取，不需要改 Agent A2A 协议。

### `weather-agent`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | 检查 `mcp-weather` 是否可用 |
| `GET` | `/debug/prompts` | 查看 weather prompt |
| `POST` | `/a2a` | 接收 Orchestrator 的 weather A2A 任务 |

当前支持：

| task_type | 能力 |
| --- | --- |
| `weather.current` | 查询当前/最近小时天气 |
| `weather.hourly_forecast` | 查询未来小时级天气 |

### `mcp-weather`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/ready` | NWS 按需调用状态 |
| `GET` | `/tools` | 查看可用工具 |
| `POST` | `/tools/get_current_weather` | 调用 NWS hourly forecast 返回最近小时天气 |
| `POST` | `/tools/get_hourly_forecast` | 调用 NWS hourly forecast 返回未来小时预报 |

当前限制：

- NWS 不需要 API key，但必须配置描述性 `NWS_USER_AGENT`。
- 当前用 seed 区域坐标解析天气；后续可改为从 `app_area_dimension` 计算 centroid。
- 天气失败不阻塞租房/通勤/区域画像核心回答。

### `mcp-profile`

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/tools` | 查看可用工具 |
| `POST` | `/tools/create_session` | 创建 session/profile |
| `POST` | `/tools/get_snapshot` | 获取 profile 快照 |
| `POST` | `/tools/patch_slots` | 更新目标区域、预算、通勤、偏好等 slots |
| `POST` | `/tools/update_weights` | 更新并归一化权重 |
| `POST` | `/tools/update_comparison_areas` | 更新对比区域 |
| `POST` | `/tools/save_conversation_summary` | 保存短会话摘要 |
| `POST` | `/tools/save_last_response_refs` | 保存上一轮回复引用 |
| `POST` | `/tools/delete_session` | 删除 session |

当前存储策略：

- 默认 `PROFILE_STORE_BACKEND=postgres`，读写 `app_session_profile`。
- `preferences`、`comparison_areas`、`conversation_summary`、`last_response_refs` 存入 `slots_json`。
- `target_area_id`、预算、通勤目的地、权重等核心字段写入结构化列。
- 如果 Postgres 不可用，服务自动使用内存 fallback，保证本地开发链路不阻塞。

## 4. 本地运行

启动完整基础链路：

```bash
cp .env.example .env
docker compose up -d postgres redis mcp-profile profile-agent mcp-sql housing-agent neighborhood-agent mcp-transit transit-agent mcp-weather weather-agent orchestrator-agent api-gateway
```

仅本机调试三个 Agent 服务时，可以使用：

```bash
PYTHONPATH=shared:services/mcp-profile .venv/bin/python -m uvicorn app.main:app --app-dir services/mcp-profile --host 127.0.0.1 --port 8026
PYTHONPATH=shared:services/profile-agent MCP_PROFILE_URL=http://127.0.0.1:8026 .venv/bin/python -m uvicorn app.main:app --app-dir services/profile-agent --host 127.0.0.1 --port 8014
PYTHONPATH=shared:services/mcp-sql DATABASE_URL_SQL=postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent .venv/bin/python -m uvicorn app.main:app --app-dir services/mcp-sql --host 127.0.0.1 --port 8020
PYTHONPATH=shared:services/housing-agent MCP_SQL_URL=http://127.0.0.1:8020 .venv/bin/python -m uvicorn app.main:app --app-dir services/housing-agent --host 127.0.0.1 --port 8011
PYTHONPATH=shared:services/neighborhood-agent MCP_SQL_URL=http://127.0.0.1:8020 .venv/bin/python -m uvicorn app.main:app --app-dir services/neighborhood-agent --host 127.0.0.1 --port 8012
PYTHONPATH=shared:services/mcp-transit DATABASE_URL_SYNC=postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent .venv/bin/python -m uvicorn app.main:app --app-dir services/mcp-transit --host 127.0.0.1 --port 8025
PYTHONPATH=shared:services/transit-agent MCP_TRANSIT_URL=http://127.0.0.1:8025 .venv/bin/python -m uvicorn app.main:app --app-dir services/transit-agent --host 127.0.0.1 --port 8013
PYTHONPATH=shared:services/mcp-weather .venv/bin/python -m uvicorn app.main:app --app-dir services/mcp-weather --host 127.0.0.1 --port 8027
PYTHONPATH=shared:services/weather-agent MCP_WEATHER_URL=http://127.0.0.1:8027 .venv/bin/python -m uvicorn app.main:app --app-dir services/weather-agent --host 127.0.0.1 --port 8015
PYTHONPATH=shared:services/orchestrator-agent PROFILE_AGENT_URL=http://127.0.0.1:8014 HOUSING_AGENT_URL=http://127.0.0.1:8011 NEIGHBORHOOD_AGENT_URL=http://127.0.0.1:8012 TRANSIT_AGENT_URL=http://127.0.0.1:8013 WEATHER_AGENT_URL=http://127.0.0.1:8015 .venv/bin/python -m uvicorn app.main:app --app-dir services/orchestrator-agent --host 127.0.0.1 --port 8010
```

## 5. 已验证内容

当前已通过：

```bash
python3 -m compileall -q shared services/mcp-profile/app services/profile-agent/app services/orchestrator-agent/app backend/api-gateway/app
docker compose config
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/api-gateway .venv/bin/python -m pytest -q -p no:cacheprovider backend/api-gateway/tests
```

本地烟测已确认：

```text
mcp-profile /health -> ok
profile-agent /ready -> ok
orchestrator-agent /ready -> ok
POST /sessions -> success
POST /chat("Astoria 的 1b 我的预算 3000 能租到吗？") -> success
profile.target_area.area_name = Astoria
profile.budget.max = 3000
```

## 6. 下一步开发边界

后续继续落地时建议按这个顺序：

1. 在 `mcp-transit` 内部补 MTA GTFS-RT / Bus Time 拉取和短缓存。
2. 把 `mcp-weather` 的 seed 坐标解析替换为从 `app_area_dimension` 计算 centroid。
3. 为 `housing-agent` / `neighborhood-agent` 增加 LLM planner 的 mock 单元测试，覆盖 JSON 解析失败和 validator 拒绝后的 fallback。
4. 如果简历展示需要显式 MCP 拆分，可在 `mcp-sql` 外再加 `mcp-safety`、`mcp-amenity`、`mcp-entertainment` 薄封装服务，内部仍复用同一 SQL Validator。
