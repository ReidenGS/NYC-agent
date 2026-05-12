# NYC Agent Codex (AI-First Project Brief)

这个 README 是给「人 + AI 代理」快速接手项目用的单文件说明。  
目标：看完本文件即可理解项目结构、运行方式、核心数据流和常见问题，不必先全量扫描 `docs/`。

## 1) 项目是什么

- 项目名称：NYC Agent
- 业务目标：做纽约租房与生活决策助手（房源、安全、便利、娱乐、天气、通勤）。
- 交互入口：前端聊天面板（Map + Chat + Profile 卡片）调用 API Gateway。
- 后端模式：多 Agent + MCP 工具服务 + 数据同步服务 + Postgres/Redis。

## 2) 当前技术栈（真实代码）

- 前端：React + Vite + TypeScript + MapLibre
- 网关：FastAPI (`backend/api-gateway`)
- 编排 Agent：`services/orchestrator-agent`（LangGraph 节点流）
- 领域 Agent：
  - `housing-agent`
  - `neighborhood-agent`
  - `transit-agent`
  - `weather-agent`
  - `profile-agent`
- MCP 服务：
  - `mcp-housing`
  - `mcp-safety`
  - `mcp-amenity`
  - `mcp-entertainment`
  - `mcp-transit`
  - `mcp-weather`
  - `mcp-profile`
- 数据同步：`services/data-sync-service`
- 数据库：Postgres + PostGIS
- 缓存/限流：Redis

## 3) 服务端口（本地 Docker）

- Frontend: `5173`（本地 dev server）
- API Gateway: `8000`
- Orchestrator: `8010`
- Housing Agent: `8011`
- Neighborhood Agent: `8012`
- Transit Agent: `8013`
- Profile Agent: `8014`
- Weather Agent: `8015`
- MCP Safety: `8024`
- MCP Transit: `8025`
- MCP Profile: `8026`
- MCP Weather: `8027`
- MCP Amenity: `8028`
- MCP Entertainment: `8029`
- Data Sync: `8030`
- MCP Housing: `8031`（容器内服务端口是 `8021`，宿主映射到 `8031`）
- Postgres: `5432`
- Redis: `6379`

## 4) 端到端请求主流程

1. 前端调用 `POST /api/chat` 到 API Gateway。
2. Gateway 转发到 orchestrator-agent。
3. Orchestrator 主要节点：
   - `backfill`
   - `understand`（LLM 提取 intent/slots）
   - `gate`（缺槽判断）
   - `plan_execute`（A2A 调度到领域 agent）
   - `respond`（组装用户回复）
   - `persist`（写 profile）
4. 领域 Agent 生成 SQL 计划（LLM）并通过对应 MCP 执行只读 SQL。
5. Orchestrator 聚合结果，返回 `answer + profile_snapshot + display_refs`。
6. 前端用 `display_refs.map_points` 和 `map_layer_ids` 渲染地图标注。

## 5) Area RAG 与槽位规则（关键）

- 正确链路：**LLM 先提取 target_area 文本 -> RAG 规范化到 canonical `area_id` -> 下发给 domain agents**。
- 不应直接用整句 query 做 area embedding 检索（会引入错配）。
- `target_area_id` 是下游查询的主键，`target_area_name` 只做展示。
- 任何 name/id 不一致都应在 orchestrator 纠正后再下发。

## 6) 地图点位规则（关键）

前端只认 `display_refs`：

- `display_refs.map_points`：实际 marker 坐标
- `display_refs.map_layer_ids`：要加载的图层 ID

对于娱乐/便利查询，后端必须返回 POI 坐标：

- 来源表：`app_map_poi_snapshot`
- 必须字段：`latitude`, `longitude`

否则前端无法在地图上标注娱乐设施位置。

## 7) 关键数据库表（最常用）

- `app_area_dimension`：区域维表（`area_id`, `area_name`, `borough`）
- `app_area_metrics_daily`：区域聚合指标（日粒度）
- `app_listing_snapshot`：房源快照（含租金、户型、坐标）
- `app_area_entertainment_category_daily`：娱乐分类统计
- `app_area_convenience_category_daily`：便利设施分类统计
- `app_map_poi_snapshot`：POI 点位（含 `poi_type`, `latitude`, `longitude`）
- `app_crime_incident_snapshot`：犯罪事件

## 8) 已验证的事实（避免重复排查）

- Hell's Kitchen 在库中存在，`area_id = MN0402`。
- `app_map_poi_snapshot` 存在娱乐 POI 坐标字段且有数据。
- 若聊天回复“有娱乐设施但地图没点”，通常不是数据缺失，而是：
  - area id 解析错配；或
  - neighborhood SQL 计划未产出带 `latitude/longitude` 的 detail 查询；或
  - 容器未重建导致本地修复代码未生效。

## 9) 本地运行（推荐）

1. 启动后端全栈：
   - `docker compose up -d`
2. 检查服务：
   - `docker compose ps`
   - `curl http://127.0.0.1:8000/api/health`
3. 启动前端：
   - `cd frontend`
   - `npm run dev`
4. 打开：
   - `http://127.0.0.1:5173`

## 10) 开发时最容易踩的坑

- 只 `docker compose restart` 不会带上本地代码改动（镜像未更新）。
  - 修改 Python 服务后应执行：
    - `docker compose build <service>`
    - `docker compose up -d <service>`
- API key 必须走环境变量（`.env`），不要硬编码到代码。
- 如果 map 点位异常，优先看 `/api/chat` 返回中的：
  - `profile_snapshot.target_area_id`
  - `display_refs.map_points`
  - `sources`

## 11) 建议 AI 代理优先阅读的代码路径

- 网关入口：`backend/api-gateway/app/api/routes.py`
- 编排主逻辑：`services/orchestrator-agent/app/nodes/*`
- area RAG：`services/orchestrator-agent/app/area_rag.py`
- neighborhood 执行：`services/neighborhood-agent/app/main.py`
- 地图渲染：`frontend/src/components/MapPanel.tsx`
- 前端会话页：`frontend/src/pages/Dashboard.tsx`

## 12) 文档索引（需要细节再看）

- `docs/NYC_Agent_Backend_Tech_Framework.md`
- `docs/NYC_Agent_Prompt_Design.md`
- `docs/NYC_Agent_API_Schema_Contract.md`
- `docs/NYC_Agent_A2A_Protocol.md`
- `docs/NYC_Agent_Data_Sources_API_SQL.md`
- `docs/AI_Agent_Business_Logic.md`

