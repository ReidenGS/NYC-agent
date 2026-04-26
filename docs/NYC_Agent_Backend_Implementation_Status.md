# NYC Agent 后端落地状态

本文记录当前已经落地的后端服务链路，方便后续 Codex / Claude 并行开发时对齐。

## 1. 当前已接入服务

| 服务 | 端口 | 职责 | 当前状态 |
| --- | --- | --- | --- |
| `api-gateway` | `8000` | 前端唯一 HTTP 入口，负责 session/chat/profile/debug API | 已接入远程 `orchestrator-agent`，失败时保留本地 mock fallback |
| `orchestrator-agent` | `8010` | 主 Agent，负责会话理解、缺槽追问、profile 读取/更新、后续 Domain Agent 调度入口 | 已实现最小链路：session、profile、chat、prompt debug |
| `housing-agent` | `8011` | 租房领域 Agent，负责生成 housing SQL plan、调用 MCP SQL、返回结构化租金/预算匹配结果 | 已接入 Orchestrator 的租金/预算问题 |
| `profile-agent` | `8014` | 用户画像状态 Agent，负责把 Orchestrator 的 profile 任务转成 MCP 工具调用 | 已实现 A2A `/a2a` 入口 |
| `mcp-sql` | `8020` | 通用只读 SQL MCP，按 domain 白名单校验并执行 SQL | 已支持 `housing/safety/amenity/entertainment` 表白名单，当前 housing 已使用 |
| `mcp-profile` | `8026` | Profile MCP 工具服务，负责 session/profile 的读写 | 已实现 MCP-style HTTP tool endpoint，当前为内存存储 |
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
MCP_SQL_URL_DOCKER=http://mcp-sql:8020
DATABASE_URL_SQL_DOCKER=postgresql+psycopg://nyc_agent:nyc_agent_password@postgres:5432/nyc_agent
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

## 4. 本地运行

启动完整基础链路：

```bash
cp .env.example .env
docker compose up -d postgres redis mcp-profile profile-agent mcp-sql housing-agent orchestrator-agent api-gateway
```

仅本机调试三个 Agent 服务时，可以使用：

```bash
PYTHONPATH=shared:services/mcp-profile .venv/bin/python -m uvicorn app.main:app --app-dir services/mcp-profile --host 127.0.0.1 --port 8026
PYTHONPATH=shared:services/profile-agent MCP_PROFILE_URL=http://127.0.0.1:8026 .venv/bin/python -m uvicorn app.main:app --app-dir services/profile-agent --host 127.0.0.1 --port 8014
PYTHONPATH=shared:services/mcp-sql DATABASE_URL_SQL=postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent .venv/bin/python -m uvicorn app.main:app --app-dir services/mcp-sql --host 127.0.0.1 --port 8020
PYTHONPATH=shared:services/housing-agent MCP_SQL_URL=http://127.0.0.1:8020 .venv/bin/python -m uvicorn app.main:app --app-dir services/housing-agent --host 127.0.0.1 --port 8011
PYTHONPATH=shared:services/orchestrator-agent PROFILE_AGENT_URL=http://127.0.0.1:8014 .venv/bin/python -m uvicorn app.main:app --app-dir services/orchestrator-agent --host 127.0.0.1 --port 8010
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

1. 接入 `safety-agent`、`amenity-agent`、`entertainment-agent`，共享 `mcp-sql` 校验与执行能力，但 prompt 和领域输出分开。
2. 接入 `transit-agent` 和 `weather-agent` 的固定 MCP 工具调用。
3. 把 `mcp-profile` 从内存存储替换为 Postgres/Redis 持久化，保持工具接口不变。
4. 在 `api-gateway /debug/dependencies` 中继续补齐各 Agent 和 MCP 的健康状态。
5. 将 `housing-agent` 当前确定性 SQL-plan 逻辑替换为 LLM SQL-plan 生成，并保留现有 validator 作为安全闸门。
