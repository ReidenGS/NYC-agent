# NYC Agent 数据源确认（API + Python + SQL）

## 1. 目标
本文件只做一件事：确认哪些数据源可以被 Python 直接通过 API 获取，并可稳定写入 SQL。

当前约束：
- 1 周上线
- 单人开发
- 总预算 < 10 美元

结论：优先使用 `NYC Open Data (Socrata)` + `NYS Open Data (Socrata)` + `OSM Overpass` + `Zillow Research`。

## 1A. API Key 配置占位（后续直接放入 `.env`）

```bash
# Socrata App Token：NYC Open Data 和 NYS Open Data 可共用；公开数据不强制，但建议配置。
# 获取网站：https://data.cityofnewyork.us/ 或 https://data.ny.gov/
# 文档：https://dev.socrata.com/docs/app-tokens.html
SOCRATA_APP_TOKEN=

# RentCast API Key：用于真实租房房源、租金估价、市场数据。
# 获取网站：https://app.rentcast.io/app/api
# 文档：https://developers.rentcast.io/reference/getting-started-guide
RENTCAST_API_KEY=

# HUD USER API Token：用于 HUD FMR 租金基准，作为备选基准源。
# 获取网站：https://www.huduser.gov/portal/dataset/fmr-api.html
HUD_USER_API_TOKEN=

# MTA Bus Time API Key：实时公交需要；MVP 若支持公交实时到站，需要配置。
# 获取网站：https://bustime.mta.info/wiki/Developers/Index
# GTFS-RT 文档：https://bustime.mta.info/wiki/Developers/GTFSRt
MTA_BUS_TIME_API_KEY=

# MTA Subway GTFS Realtime：公开 feed 通常不需要 key；保留占位方便后续接入代理/第三方服务。
# 获取网站：https://www.mta.info/developers
# 说明：MTA 地铁 GTFS-RT feed 通常不需要 API key；如果后续使用第三方代理服务，再填该服务的 key。
MTA_SUBWAY_GTFS_RT_API_KEY=

# MapTiler API Key：用于前端轻量底图瓦片；如果改用 Protomaps/PMTiles 自托管，可不填。
# 获取网站：https://cloud.maptiler.com/account/keys/
# 文档：https://docs.maptiler.com/cloud/api/authentication-key/
MAPTILER_API_KEY=

# National Weather Service：不需要 API key，但必须设置 User-Agent 标识应用和联系方式。
# API 文档：https://www.weather.gov/documentation/services-web-api
# OpenAPI：https://api.weather.gov/openapi.json
# 示例格式：NYC-Agent-Demo/0.1 (your_email@example.com)
NWS_USER_AGENT=

# Zillow Research Data 不需要 API key，入口：https://www.zillow.com/research/data/
# Overpass API 不需要 API key，文档：https://wiki.openstreetmap.org/wiki/Overpass_API
```

Python 读取约定：
- Socrata 请求头：`X-App-Token: ${SOCRATA_APP_TOKEN}`（可选）
- RentCast 请求头：`X-Api-Key: ${RENTCAST_API_KEY}`（必填）
- HUD FMR 请求使用：`${HUD_USER_API_TOKEN}`（接入 HUD FMR 时必填）
- NWS 请求头：`User-Agent: ${NWS_USER_AGENT}`（必填，不是 API key）

### 1A.1 API 费用确认表
价格信息按 2026-04-25 可查官方页面整理，后续落地前需要再以官网为准。

| API / 数据源 | 是否需要 Key | 是否收费 | 免费额度 / 收费标准 | 说明 |
|---|---:|---:|---|---|
| Socrata / NYC Open Data / NYS Open Data | 建议配置 | 免费 | 未看到按量收费；App Token 用于更高限流池 | 公开数据可无 token 读取，但 token 可降低共享 IP 限流风险 |
| RentCast API | 需要 | 有免费额度，超出收费 | Developer: $0/月，50 calls/月，额外 $0.20/request；Foundation: $74/月，1,000 calls/月，额外 $0.06/request；Growth: $199/月，5,000 calls/月，额外 $0.03/request；Scale: $449/月，25,000 calls/月，额外 $0.015/request | 房源/租金主源，必须严格缓存和控制调用次数 |
| HUD USER FMR API | 需要 | 未看到收费 | API Terms 显示调用限制为 60 queries/min | 用于政府口径租金基准；需要账号和 token |
| MTA Bus Time API | 需要 | 免费 | 官方说明 real-time developer API 可免费使用 | 用于公交实时到站；需要申请 key |
| MTA Subway GTFS-RT | 通常不需要 | 免费 | 未看到收费 | 用于地铁实时 feed；按 MTA developer 资源使用 |
| MapTiler Cloud | 需要 | 有免费额度，超出需付费 | Free: $0，5k sessions/月，100k requests/月，超额不可用；Flex: $25/月，25k sessions/月，500k requests/月，超额 $2/1k sessions、$0.10/1k requests；Unlimited: $295/月，300k sessions/月，5M requests/月，超额 $1.5/1k sessions、$0.08/1k requests | 推荐 MVP 底图；前端地图加载会消耗 session/request |
| National Weather Service API | 不需要 key；需要 User-Agent | 免费 | 官方说明为开放数据免费使用；存在合理限流但不公开具体阈值 | 用于当前/小时级天气预报；必须缓存，避免无意义高频请求 |
| Zillow Research Data | 不需要 | 免费 | 公开 CSV 下载 | 用于租金基准 fallback，不是实时 API |
| Overpass API | 不需要 | 免费公共服务 | 无商业 SLA；需要遵守公平使用，控制范围/频率/缓存 | 用于娱乐/便利 POI；不能高频滥用 |
| Protomaps PMTiles | 不需要 | 数据/工具可免费使用，托管可能有成本 | 可自托管 PMTiles；云存储/CDN 费用自理 | MapTiler 的无 key 备选，部署复杂度更高 |
| OSM Public Tiles | 不需要 | 免费公共服务 | 需遵守 OSM Tile Usage Policy，不适合高频生产使用 | 只建议本地开发或临时 demo |

## 2. API 可用数据源（可直接接入）

### 2.1 犯罪数据（必选）
- 名称：NYPD Complaint Data Historic
- 数据集 ID：`qgea-i56i`
- API：`https://data.cityofnewyork.us/resource/qgea-i56i.json`
- API Token：读取公开数据不强制需要；建议申请 Socrata App Token 以降低限流风险
- 环境变量占位：`SOCRATA_APP_TOKEN=`
- 获取 Token / 文档：
  - Socrata App Token 文档：`https://dev.socrata.com/docs/app-tokens.html`
  - Socrata Token 生成说明：`https://support.socrata.com/hc/en-us/articles/210138558-Generating-App-Tokens-and-API-Keys`
  - NYC Open Data 账号入口：`https://data.cityofnewyork.us/`
- 典型用途：按区域聚合犯罪数量、按时间窗口统计
- 备注：Data.gov 显示 Last Modified `2025-04-15`

### 2.2 311 体感数据（必选）
- 名称：311 Service Requests from 2020 to Present
- 数据集 ID：`erm2-nwe9`
- API：`https://data.cityofnewyork.us/resource/erm2-nwe9.json`
- API Token：读取公开数据不强制需要；建议复用 Socrata App Token
- 环境变量占位：`SOCRATA_APP_TOKEN=`
- 获取 Token / 文档：
  - Socrata App Token 文档：`https://dev.socrata.com/docs/app-tokens.html`
  - NYC Open Data 账号入口：`https://data.cityofnewyork.us/`
- 典型用途：噪音、卫生、鼠患等“居住体感”指标
- 备注：Data.gov 显示 Last Modified `2026-04-13`（日更）

### 2.3 区域边界（推荐）
- 名称：2020 Neighborhood Tabulation Areas (NTAs)
- 数据集 ID：`9nt8-h7nd`
- API：`https://data.cityofnewyork.us/resource/9nt8-h7nd.json`
- API Token：读取公开数据不强制需要；建议复用 Socrata App Token
- 环境变量占位：`SOCRATA_APP_TOKEN=`
- 获取 Token / 文档：
  - Socrata App Token 文档：`https://dev.socrata.com/docs/app-tokens.html`
  - NYC Open Data 账号入口：`https://data.cityofnewyork.us/`
- 典型用途：统一区域维度（NTA）

### 2.4 公共设施（便利设施）
- 名称：Facilities Database
- 数据集 ID：`67g2-p84d`（表格）/ `2fpa-bnsx`（地理导出）
- API：
  - `https://data.cityofnewyork.us/resource/67g2-p84d.json`
  - `https://data.cityofnewyork.us/api/geospatial/2fpa-bnsx?method=export&format=GeoJSON`
- API Token：读取公开数据不强制需要；建议复用 Socrata App Token
- 环境变量占位：`SOCRATA_APP_TOKEN=`
- 获取 Token / 文档：
  - Socrata App Token 文档：`https://dev.socrata.com/docs/app-tokens.html`
  - NYC Open Data 账号入口：`https://data.cityofnewyork.us/`
- 典型用途：公园、学校、图书馆等设施统计

### 2.5 交通站点（推荐）
- 名称：MTA Subway Stations
- 数据集 ID：`39hk-dx4f`（NYS Open Data）
- API：`https://data.ny.gov/resource/39hk-dx4f.json`
- API Token：读取 NYS Open Data 的公开 Socrata 数据不强制需要；建议申请/复用 Socrata App Token
- 环境变量占位：`SOCRATA_APP_TOKEN=`
- 获取 Token / 文档：
  - Socrata App Token 文档：`https://dev.socrata.com/docs/app-tokens.html`
  - NYS Open Data 入口：`https://data.ny.gov/`
  - MTA Developer Resources：`https://www.mta.info/developers`
- 备注：若后续接入实时公交 Bus Time API，需要单独申请 MTA Bus Time developer API key
- 环境变量占位：`MTA_BUS_TIME_API_KEY=`
- Bus Time Key 入口：`https://bustime.mta.info/wiki/Developers/GTFSRt`
- 典型用途：站点密度、线路覆盖

### 2.5A MTA 实时通勤数据（MVP 新增）
- 名称：MTA GTFS Realtime / Bus Time
- 地铁实时数据：MTA Developer Resources 提供 GTFS-RT feeds
- 地铁开发文档：`https://www.mta.info/developers`
- 公交实时数据：MTA Bus Time GTFS-RT
- 公交 Trip Updates：`https://gtfsrt.prod.obanyc.com/tripUpdates?key=<YOUR_KEY>`
- 公交 Vehicle Positions：`https://gtfsrt.prod.obanyc.com/vehiclePositions?key=<YOUR_KEY>`
- 公交 Alerts：`https://gtfsrt.prod.obanyc.com/alerts?key=<YOUR_KEY>`
- API Key：
  - 地铁 GTFS-RT：通常不需要 key
  - 公交 Bus Time：需要 `MTA_BUS_TIME_API_KEY=`
- 典型用途：下一班/下两班车、实时到站、实时服务状态、出发时间规划

### 2.6 娱乐设施 POI（推荐）
- 名称：OpenStreetMap Overpass
- API：`https://overpass-api.de/api/interpreter`
- API Key：不需要 API key
- 文档入口：`https://wiki.openstreetmap.org/wiki/Overpass_API`
- 使用约束：公共服务需要控制请求频率、范围和并发；MVP 应做缓存
- 典型用途：酒吧、影院、夜生活点位数量/密度

### 2.7 RentCast 租房/房源数据（推荐，用户已有 API）
- 名称：RentCast Property Data API
- API Key：需要 `X-Api-Key` 请求头；用户已有 RentCast API 可优先使用
- 环境变量占位：`RENTCAST_API_KEY=`
- API Dashboard：`https://app.rentcast.io/app/api`
- 开发文档：`https://developers.rentcast.io/reference/getting-started-guide`
- 长租房源列表 API：`https://api.rentcast.io/v1/listings/rental/long-term`
- 单条长租房源 API：`https://api.rentcast.io/v1/listings/rental/long-term/{id}`
- 租金估价 API：`https://api.rentcast.io/v1/avm/rent/long-term`
- 市场数据 API：`https://api.rentcast.io/v1/markets`
- 已确认可用字段/参数：
  - 查询参数：`city`、`state`、`zipCode`、`latitude`、`longitude`、`radius`、`bedrooms`、`propertyType`、`price`、`status`、`limit`、`offset`
  - 房源响应字段示例：`id`、`formattedAddress`、`city`、`state`、`zipCode`、`latitude`、`longitude`、`propertyType`、`bedrooms`、`bathrooms`、`squareFootage`、`status`、`price`、`listedDate`、`lastSeenDate`、`daysOnMarket`、`listingAgent`
- 典型用途：真实房源清单、房源数量、租金区间、按户型聚合、执行包候选房源

### 2.8 租金基准（推荐）
- 名称：Zillow Research Data（ZORI）
- 入口：`https://www.zillow.com/research/data/`
- API Key：不需要 API key；这是公开 CSV 下载，不是实时 API
- 官方说明：Zillow Research Data 页面说明 CSV 路径可能变化，并按月更新
- 典型用途：市场租金基准/趋势（非实时房源）

备选基准源：
- 名称：HUD Fair Market Rents (FMR)
- API/入口：`https://www.huduser.gov/portal/dataset/fmr-api.html`
- API Key：需要 HUD USER API token
- 环境变量占位：`HUD_USER_API_TOKEN=`
- 典型用途：政府口径的年度租金基准（gross rent），适合做参考下限/合规对照，不等同于实时市场价

### 2.9 地图底图与可视化图层（推荐）
底图和业务图层分开处理。

推荐 MVP 底图：
- 名称：MapTiler Cloud + MapLibre GL JS
- 获取 Key：`https://cloud.maptiler.com/account/keys/`
- API 文档：`https://docs.maptiler.com/cloud/api/authentication-key/`
- 环境变量占位：`MAPTILER_API_KEY=`
- 用途：前端轻量显示道路、水域、地名等底图

无 key 备选：
- 名称：Protomaps PMTiles + MapLibre GL JS
- 文档：`https://docs.protomaps.com/pmtiles/maplibre`
- 用途：自托管或静态托管 basemap tiles，适合不想依赖第三方 key 的版本
- 代价：需要处理 PMTiles 文件、style、glyphs、sprite 等资源

开发期备选：
- 名称：OpenStreetMap public tiles + Leaflet
- 文档：`https://operations.osmfoundation.org/policies/tiles/`
- 用途：本地 demo 可用
- 注意：不适合作为高频生产瓦片源，必须遵守 OSM tile usage policy

业务图层数据：
- 区域变色图层：空间计算来自 `app_area_dimension.geom`，前端 GeoJSON 可来自 `app_area_dimension.geom_geojson`
- 娱乐/便利点位图层：来自 Overpass 或 Facilities 的经纬度
- 犯罪热力图：来自 NYPD `qgea-i56i.latitude/longitude` 聚合后输出，不建议前端直接加载全量原始点

### 2.10 天气数据（推荐，轻量生活辅助）
- 名称：National Weather Service API
- Base URL：`https://api.weather.gov`
- API Key：不需要
- 必填请求头：`User-Agent: ${NWS_USER_AGENT}`
- 环境变量占位：`NWS_USER_AGENT=`
- 官方文档：`https://www.weather.gov/documentation/services-web-api`
- OpenAPI：`https://api.weather.gov/openapi.json`
- 典型调用链：
  1. 用目标区域中心点调用 `GET https://api.weather.gov/points/{latitude},{longitude}`
  2. 从响应 `properties.forecastHourly` 取得小时级 forecast URL
  3. 请求 forecastHourly，读取 `properties.periods`
- 可获得字段：
  - `number`
  - `name`
  - `startTime`
  - `endTime`
  - `isDaytime`
  - `temperature`
  - `temperatureUnit`
  - `temperatureTrend`
  - `probabilityOfPrecipitation.value`
  - `windSpeed`
  - `windDirection`
  - `shortForecast`
  - `detailedForecast`
- 典型用途：
  - 默认显示目标区域当前到未来 6 小时天气
  - 回答“今晚会不会下雨”“明早冷不冷”等指定时刻天气问题
- 缓存策略：
  - `/points/{lat},{lon}` 网格映射缓存 7 天
  - `forecastHourly` 响应缓存 30-60 分钟
- 说明：
  - 天气不进入长期推荐打分
  - 天气不需要入长期 SQL 表，MVP 用 Redis 短缓存即可
  - 如果后续想做天气查询审计，可增加匿名查询日志表

## 3. 高风险数据源（MVP 不依赖）

### 3.1 Zillow Rentals 实时房源
- 官方说明：Rentals Feed Integrations 需审核，测试流程约 `4-6 周`
- 申请入口：`https://www.zillowgroup.com/developers/api/rentals/rentals-feed-integrations/`
- 结论：不适合 1 周 MVP 前置

### 3.2 StreetEasy 实时房源 API
- 未发现通用开发者公开读取 API 文档
- 结论：按合作接入处理，MVP 不强依赖

## 3A. API / Token 获取入口汇总

| 数据源 | 是否必须申请 API key/token | 获取入口 | MVP 建议 |
|---|---:|---|---|
| NYC Open Data / Socrata | 否，建议申请 App Token | `https://dev.socrata.com/docs/app-tokens.html` | 申请一个 `SOCRATA_APP_TOKEN`，犯罪/311/NTA/设施共用 |
| NYS Open Data / Socrata | 否，建议申请 App Token | `https://data.ny.gov/` | 交通站点可先无 token，稳定后复用 token |
| MTA Developer | 静态站点不需要；实时公交需要 | `https://www.mta.info/developers` | MVP 不接实时公交，先不申请 |
| MTA Bus Time | 实时公交需要 key | `https://bustime.mta.info/wiki/Developers/GTFSRt` | 后续扩展再申请 |
| MTA Subway GTFS-RT | 通常不需要 key | `https://www.mta.info/developers` | 地铁实时下一班车可优先接入 |
| National Weather Service API | 不需要 key；需要 User-Agent | `https://www.weather.gov/documentation/services-web-api` | 用于天气卡片和天气问答，配置 `NWS_USER_AGENT` 即可 |
| Overpass API | 不需要 | `https://wiki.openstreetmap.org/wiki/Overpass_API` | 必须做缓存和限频 |
| MapTiler Cloud | 需要 key | `https://cloud.maptiler.com/account/keys/` | 推荐作为 MVP 前端底图 |
| Protomaps PMTiles | 不需要 API key | `https://docs.protomaps.com/pmtiles/maplibre` | 无 key 备选，部署比 MapTiler 稍复杂 |
| RentCast API | 需要 `X-Api-Key` | `https://app.rentcast.io/app/api` | 用户已有 API，作为房源与租金主源 |
| Zillow Research Data | 不需要 | `https://www.zillow.com/research/data/` | 用 CSV 下载作为租金基线 |
| HUD FMR API | 需要 HUD USER token | `https://www.huduser.gov/portal/dataset/fmr-api.html` | 作为政府口径租金基准备选 |
| Zillow Rentals Feed | 需要审核 | `https://www.zillowgroup.com/developers/api/rentals/rentals-feed-integrations/` | 不作为 MVP 依赖 |

## 4. Python 拉取与入库建议

### 4.1 Python 请求建议
- `requests` + 重试（指数退避）
- Socrata 使用 `$limit/$offset` 分页
- 建议配置 `X-App-Token`（降低限流风险）
- RentCast 使用 `X-Api-Key`，从环境变量 `RENTCAST_API_KEY` 读取
- HUD FMR 使用 `HUD_USER_API_TOKEN`，仅接入 HUD 基准时读取

### 4.2 增量更新策略
- 每个源维护 `last_sync_at`
- 优先按源数据时间字段增量拉取
- 原始表统一保留：`source`、`source_record_id`、`ingested_at`、`raw_json`

### 4.3 SQL 分层（推荐）
- `ods_*`：仅用于离线同步和排查（可选）
- `app_*`：Agent 在线查询直接使用的业务表（MVP 必做）

## 5. 字段映射（已按真实样本核验）
核验方式：2026-04-23 对以下 endpoint 直接拉取 `$limit=1` 样本。

### 5.1 qgea-i56i（NYPD）
- 主键：`cmplnt_num`
- 时间：`cmplnt_fr_dt`、`rpt_dt`
- 指标：`ofns_desc`、`pd_desc`、`law_cat_cd`、`boro_nm`
- 空间：`latitude`、`longitude`

### 5.2 erm2-nwe9（311）
- 主键：`unique_key`
- 时间：`created_date`、`closed_date`
- 指标：`complaint_type`、`descriptor`、`agency`
- 区域：`borough`、`incident_zip`
- 空间：`latitude`、`longitude`（注意：部分记录可能为空）

### 5.3 9nt8-h7nd（NTA）
- 主键：`nta2020`
- 名称：`ntaname`、`boroname`
- 区域属性：`ntatype`、`cdta2020`
- 几何：`the_geom`

### 5.4 67g2-p84d（Facilities）
- 主键：`uid`
- 指标：`facgroup`、`facsubgrp`、`factype`
- 区域：`nta2020`、`boro`
- 空间：`latitude`、`longitude`
- 已核验可用 `facgroup` 示例：`PARKS AND PLAZAS`、`LIBRARIES`、`SCHOOLS (K-12)`、`HEALTH CARE`、`CULTURAL INSTITUTIONS`、`TRANSPORTATION`

### 5.5 39hk-dx4f（MTA Stations）
- 主键候选：`gtfs_stop_id`（推荐）
- 属性：`stop_name`、`daytime_routes`、`borough`、`structure`
- 空间：`gtfs_latitude`、`gtfs_longitude`（或 `georeference`）

### 5.6 RentCast 长租房源（`/listings/rental/long-term`）
- 主键：`id`
- 地址/区域：`formattedAddress`、`city`、`state`、`zipCode`
- 空间：`latitude`、`longitude`
- 房源属性：`propertyType`、`bedrooms`、`bathrooms`、`squareFootage`
- 租金/状态：`price`、`status`、`listedDate`、`lastSeenDate`、`daysOnMarket`
- 联系信息：`listingAgent.name`、`listingAgent.phone`（字段可能为空，不能作为必填）

### 5.7 租金基准源
- RentCast Market Data：按 zip code 获取市场租金、户型拆分、历史趋势（需要 RentCast API）
- Zillow ZORI：公开 CSV，提供市场租金指数/典型租金，粒度包含 zip/city/metro 等
- HUD FMR：政府口径 Fair Market Rent，按年度/地区/卧室数提供 gross rent 基准

## 6. 最小可执行 SQL 表结构（业务表，非原始表）

说明：以下是“Agent 直接可用”的最小业务表，不是原始落地表。  
这些表由离线任务从 API 数据聚合生成，保证能支撑你当前业务逻辑：
- 问某区域犯罪/娱乐/交通/租金 -> 直接查区域指标
- 问某区域某类犯罪数量/犯罪类型分布 -> 查询犯罪事件明细快照表
- 问某区域具体有哪些娱乐/便利分类 -> 查询分类明细表
- 问某区域租金/房源概况 -> 查询租房信息表
- 用户动态设置权重 -> 写会话偏好
- 输出推荐收敛 -> 写推荐结果

```sql
-- PostGIS 扩展：支持区域边界、点位归属、附近查询和空间索引。
CREATE EXTENSION IF NOT EXISTS postgis;

-- 1) 区域维表：统一目标地区主键（target_area 对应 area_id）
-- 作用：存放 Agent 可识别的“地区字典”，是所有指标和推荐的基础维度。
CREATE TABLE IF NOT EXISTS app_area_dimension (
  area_id TEXT PRIMARY KEY,                   -- 地区唯一ID（NTA编码），如 BK0101
  area_name TEXT NOT NULL,                    -- 地区名称，如 Greenpoint
  borough TEXT NOT NULL,                      -- 所属行政区（Manhattan/Brooklyn/Queens/Bronx/Staten Island）
  area_type TEXT NULL,                        -- 地区类型代码（住宅区/特殊区等，来自 NTAType）
  geom_geojson JSONB NULL,                    -- 地区几何边界 GeoJSON，用于前端地图高亮和 GeoJSON 输出
  geom GEOMETRY(MULTIPOLYGON, 4326) NULL,     -- PostGIS 区域边界，用于空间归属、相交和附近查询
  updated_at TIMESTAMP NOT NULL DEFAULT NOW() -- 本行最后更新时间
);

-- 2) 区域指标表：问答主查询表（犯罪/娱乐/交通/租金/便利）
-- 作用：Agent 回答“这个区犯罪多少、娱乐多不多、交通如何”时直接查询本表。
-- 注意：娱乐/便利总量来自后面的分类明细表聚合，分类展示时不要只依赖本表。
CREATE TABLE IF NOT EXISTS app_area_metrics_daily (
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID（外键）
  metric_date DATE NOT NULL,                                    -- 指标统计日期（这一天对应的快照）
  crime_count_30d INTEGER NOT NULL DEFAULT 0,                   -- 近30天犯罪事件数量
  crime_index_100 NUMERIC(6,2) NULL,                            -- 犯罪强度指数（0-100，值越高表示风险越高）
  entertainment_poi_count INTEGER NOT NULL DEFAULT 0,           -- 娱乐设施点位数量（酒吧/影院/夜生活等）
  convenience_facility_count INTEGER NOT NULL DEFAULT 0,        -- 便利设施数量（学校/图书馆/公园等）
  transit_station_count INTEGER NOT NULL DEFAULT 0,             -- 交通站点数量（地铁站等）
  complaint_noise_30d INTEGER NOT NULL DEFAULT 0,               -- 近30天噪音相关311投诉数量
  rent_index_value NUMERIC(10,2) NULL,                          -- 租金指数或租金基线值（用于租金对比）
  source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,           -- 数据来源快照（每个指标的 source/timestamp）
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 本行最后更新时间
  PRIMARY KEY (area_id, metric_date)
);

-- 3) 犯罪事件明细快照表：支撑“偷窃/抢劫/夜间犯罪/犯罪类型分布”等动态安全查询。
-- 作用：保存 NYPD 公开犯罪事件的最小可用字段，供 Domain Agent 生成只读 SQL 查询。
CREATE TABLE IF NOT EXISTS app_crime_incident_snapshot (
  incident_id TEXT PRIMARY KEY,                                  -- 犯罪事件ID，来自 NYPD cmplnt_num
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id),  -- 地区ID（由经纬度空间归属到 NTA）
  occurred_at TIMESTAMP NULL,                                    -- 事件发生时间，由 cmplnt_fr_dt + cmplnt_fr_tm 合成
  occurred_date DATE NULL,                                       -- 事件发生日期，来自 cmplnt_fr_dt
  occurred_hour INTEGER NULL,                                    -- 事件发生小时，由 cmplnt_fr_tm 派生，用于夜间/分时段查询
  borough TEXT NULL,                                             -- 行政区，来自 boro_nm
  offense_category TEXT NULL,                                    -- 犯罪大类，来自 ofns_desc 标准化，如 PETIT LARCENY/ROBBERY
  offense_description TEXT NULL,                                 -- 犯罪描述，来自 ofns_desc 或 pd_desc
  law_category TEXT NULL,                                        -- 法律严重程度，来自 law_cat_cd，如 FELONY/MISDEMEANOR/VIOLATION
  latitude DOUBLE PRECISION NULL,                                -- 纬度，来自 latitude
  longitude DOUBLE PRECISION NULL,                               -- 经度，来自 longitude
  geom GEOMETRY(POINT, 4326) NULL,                                -- PostGIS 点位，由 longitude/latitude 生成，用于空间归属和热力图
  source TEXT NOT NULL DEFAULT 'nypd_complaint_data',            -- 数据来源，MVP 来自 NYC Open Data qgea-i56i
  source_record_id TEXT NOT NULL,                                -- 源记录ID，来自 cmplnt_num
  raw_source JSONB NOT NULL DEFAULT '{}'::jsonb,                 -- 源字段快照，保留字段漂移时的回溯能力
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()                    -- 本行最后更新时间
);

-- 4) 娱乐设施分类表：支撑“这个区有多少酒吧/影院/夜生活设施”等细分回答。
-- 作用：保存每个地区每天的娱乐类 POI 分类数量，方便前端做蓝点/分类柱状图。
CREATE TABLE IF NOT EXISTS app_area_entertainment_category_daily (
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID（外键）
  metric_date DATE NOT NULL,                                    -- 指标统计日期
  category_code TEXT NOT NULL,                                  -- 标准化分类编码，如 bar/cinema/nightclub
  category_name TEXT NOT NULL,                                  -- 展示名称，如 酒吧/电影院/夜店
  poi_count INTEGER NOT NULL DEFAULT 0,                         -- 该分类设施数量
  source TEXT NOT NULL DEFAULT 'overpass',                      -- 数据来源，MVP 主要来自 Overpass
  source_key TEXT NOT NULL,                                     -- 源数据分类字段，如 OSM tags.amenity
  source_value TEXT NOT NULL,                                   -- 源数据分类值，如 bar/cinema/nightclub
  source_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,            -- 完整映射规则，如 {"tags.amenity":"bar"}
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 本行最后更新时间
  PRIMARY KEY (area_id, metric_date, category_code, source, source_key, source_value)
);

-- 5) 便利设施分类表：支撑“这个区有多少超市/公园/学校/图书馆”等细分回答。
-- 作用：保存每个地区每天的生活便利类设施分类数量，方便前端展示分类结构。
CREATE TABLE IF NOT EXISTS app_area_convenience_category_daily (
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID（外键）
  metric_date DATE NOT NULL,                                    -- 指标统计日期
  category_code TEXT NOT NULL,                                  -- 标准化分类编码，如 supermarket/park/library/school
  category_name TEXT NOT NULL,                                  -- 展示名称，如 超市/公园/图书馆/学校
  facility_count INTEGER NOT NULL DEFAULT 0,                    -- 该分类设施数量
  source TEXT NOT NULL,                                         -- 数据来源，如 overpass 或 67g2-p84d
  source_key TEXT NOT NULL,                                     -- 源数据分类字段，如 facgroup 或 OSM tags.shop
  source_value TEXT NOT NULL,                                   -- 源数据分类值，如 LIBRARIES 或 supermarket
  source_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,            -- 完整映射规则，如 {"facgroup":"LIBRARIES"}
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 本行最后更新时间
  PRIMARY KEY (area_id, metric_date, category_code, source, source_key, source_value)
);

-- 6) 地图点位快照表：支撑地图上展示具体设施点、娱乐蓝点、便利设施点。
-- 作用：保存可在前端显示的大致点位；字段必须来自带经纬度的源数据或明确派生。
CREATE TABLE IF NOT EXISTS app_map_poi_snapshot (
  poi_id TEXT PRIMARY KEY,                                      -- 点位ID，来自源数据ID或 source+坐标+分类 生成哈希
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID（由经纬度空间归属到 NTA）
  poi_type TEXT NOT NULL,                                       -- 点位大类：entertainment/convenience/safety/transit/rental
  category_code TEXT NOT NULL,                                  -- 分类编码，如 bar/supermarket/crime
  category_name TEXT NOT NULL,                                  -- 展示名称，如 酒吧/超市/犯罪事件
  name TEXT NULL,                                               -- 点位名称，来自 OSM tags.name、Facilities facname，可能为空
  latitude DOUBLE PRECISION NOT NULL,                           -- 纬度，来自源数据 latitude/lat/stop_lat
  longitude DOUBLE PRECISION NOT NULL,                          -- 经度，来自源数据 longitude/lon/stop_lon
  geom GEOMETRY(POINT, 4326) NULL,                               -- PostGIS 点位，由 longitude/latitude 生成，用于地图和附近查询
  intensity NUMERIC(8,4) NOT NULL DEFAULT 1.0,                  -- 热力/点位权重，系统派生；普通点为 1
  source TEXT NOT NULL,                                         -- 数据来源：overpass/67g2-p84d/qgea-i56i/39hk-dx4f/rentcast
  source_key TEXT NULL,                                         -- 源分类字段，如 tags.amenity/facgroup/ofns_desc
  source_value TEXT NULL,                                       -- 源分类值，如 bar/LIBRARIES/DANGEROUS DRUGS
  source_record_id TEXT NULL,                                   -- 源记录ID，如 OSM element id、Facilities uid、NYPD cmplnt_num
  source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,           -- 源字段快照，便于追溯字段来源
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()                   -- 本行最后更新时间
);

-- 7) 地图图层缓存表：支撑前端快速加载 GeoJSON 图层，避免每次实时拼装。
-- 作用：缓存 choropleth/heatmap/marker 图层结果，供 `/areas/{id}/map-layers` 返回。
CREATE TABLE IF NOT EXISTS app_map_layer_cache (
  layer_id TEXT PRIMARY KEY,                                    -- 图层ID，建议 area_id + layer_type + metric_date 生成
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID
  layer_type TEXT NOT NULL,                                     -- 图层类型：choropleth/heatmap/marker/cluster
  metric_name TEXT NOT NULL,                                    -- 指标名：crime_index/entertainment/convenience/rent/transit
  metric_date DATE NOT NULL,                                    -- 指标日期
  geojson JSONB NOT NULL,                                       -- 前端可直接使用的 GeoJSON FeatureCollection
  style_hint JSONB NOT NULL DEFAULT '{}'::jsonb,                -- 前端样式建议，如颜色阶梯、点颜色、半径
  source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,           -- 图层使用的数据源和时间戳
  expires_at TIMESTAMP NULL,                                    -- 过期时间；静态图层可为空，实时图层设置 TTL
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 本行最后更新时间
  UNIQUE (area_id, layer_type, metric_name, metric_date)
);

-- 8) 区域房源明细快照表：支撑“房源清单、看房顺序、中介联系话术”等执行输出。
-- 作用：保存 RentCast 返回的长租房源明细。后续执行包必须从这张表取候选房源。
CREATE TABLE IF NOT EXISTS app_area_rental_listing_snapshot (
  listing_id TEXT PRIMARY KEY,                                  -- RentCast 房源ID，来自 id
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID（由经纬度空间归属到 NTA）
  snapshot_date DATE NOT NULL,                                  -- 抓取/快照日期
  formatted_address TEXT NOT NULL,                              -- 完整地址，来自 formattedAddress
  city TEXT NULL,                                               -- 城市，来自 city
  state TEXT NULL,                                              -- 州，来自 state
  zip_code TEXT NULL,                                           -- ZIP，来自 zipCode
  latitude DOUBLE PRECISION NULL,                               -- 纬度，来自 latitude
  longitude DOUBLE PRECISION NULL,                              -- 经度，来自 longitude
  geom GEOMETRY(POINT, 4326) NULL,                               -- PostGIS 房源点位，由 longitude/latitude 生成，用于地图和区域归属
  property_type TEXT NULL,                                      -- 房屋类型，来自 propertyType
  bedroom_type TEXT NOT NULL DEFAULT 'unknown',                 -- 标准化户型，由 bedrooms 转换：0=studio,1=1br,2=2br
  bedrooms NUMERIC(4,1) NULL,                                   -- 卧室数，来自 bedrooms
  bathrooms NUMERIC(4,1) NULL,                                  -- 卫生间数，来自 bathrooms
  square_footage INTEGER NULL,                                  -- 面积，来自 squareFootage
  monthly_rent NUMERIC(10,2) NULL,                              -- 月租，来自 price
  listing_status TEXT NULL,                                     -- 房源状态，来自 status
  listed_date TIMESTAMP NULL,                                   -- 上架时间，来自 listedDate
  last_seen_date TIMESTAMP NULL,                                -- 最近一次看到该房源的时间，来自 lastSeenDate
  days_on_market INTEGER NULL,                                  -- 在市场上的天数，来自 daysOnMarket
  listing_agent_name TEXT NULL,                                 -- 中介/联系人姓名，来自 listingAgent.name（可能为空）
  listing_agent_phone TEXT NULL,                                -- 中介/联系人电话，来自 listingAgent.phone（可能为空）
  source TEXT NOT NULL DEFAULT 'rentcast_listings',             -- 数据来源
  raw_source JSONB NOT NULL DEFAULT '{}'::jsonb,                -- 源数据快照，保留字段漂移时的回溯能力
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()                   -- 本行最后更新时间
);

-- 9) 区域租房聚合表：支撑“这个区租金区间是多少、房源多不多、适不适合我的预算”等回答。
-- 作用：按地区+户型聚合房源明细，也可接入 RentCast Market Data/ZORI/HUD FMR 的基准结果。
CREATE TABLE IF NOT EXISTS app_area_rental_market_daily (
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID（外键）
  metric_date DATE NOT NULL,                                    -- 指标统计日期
  bedroom_type TEXT NOT NULL,                                   -- 户型，如 studio/1br/2br/shared/unknown
  listing_type TEXT NOT NULL DEFAULT 'rental',                  -- 房源类型，MVP 固定 rental
  rent_min NUMERIC(10,2) NULL,                                  -- 该地区该户型观察到的最低月租
  rent_median NUMERIC(10,2) NULL,                               -- 该地区该户型月租中位数
  rent_max NUMERIC(10,2) NULL,                                  -- 该地区该户型观察到的最高月租
  listing_count INTEGER NOT NULL DEFAULT 0,                     -- 可用房源/样本数量
  data_quality TEXT NOT NULL DEFAULT 'reference',               -- 数据质量：realtime/reference/estimated
  source TEXT NOT NULL,                                         -- 数据来源，如 zori/manual_snapshot/partner_api
  source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,           -- 来源快照和更新时间
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 本行最后更新时间
  PRIMARY KEY (area_id, metric_date, bedroom_type, listing_type, source)
);

-- 10) 区域租金基准表：支撑“当前房源租金是否高于市场基准”等判断。
-- 作用：保存 ZORI/HUD FMR/RentCast Market Data 等基准源，和实时房源聚合分开管理。
CREATE TABLE IF NOT EXISTS app_area_rent_benchmark_monthly (
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id), -- 地区ID（由 ZIP/城市/经纬度映射到 NTA）
  benchmark_month DATE NOT NULL,                                -- 基准月份（统一取每月第一天）
  bedroom_type TEXT NOT NULL DEFAULT 'all',                     -- 户型，如 all/studio/1br/2br/3br
  benchmark_rent NUMERIC(10,2) NULL,                            -- 基准租金值
  benchmark_type TEXT NOT NULL,                                 -- 基准类型：zori/hud_fmr/rentcast_market
  benchmark_geo_type TEXT NOT NULL,                             -- 原始地理粒度：zip/city/metro/county
  benchmark_geo_id TEXT NOT NULL,                               -- 原始地理ID，如 ZIP code 或 Zillow RegionID
  data_quality TEXT NOT NULL DEFAULT 'benchmark',               -- 数据质量标记：benchmark/reference/official
  source TEXT NOT NULL,                                         -- 数据来源：zori/hud_fmr/rentcast_markets
  source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,           -- 原始字段和更新时间
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 本行最后更新时间
  PRIMARY KEY (area_id, benchmark_month, bedroom_type, benchmark_type, benchmark_geo_id)
);

-- 11) 交通站点维表：支撑“从目标区域/地址找到最近合理站点”。
-- 作用：由 GTFS static stops.txt 或 MTA Subway Stations 数据生成，公交/地铁统一成站点字典。
CREATE TABLE IF NOT EXISTS app_transit_stop_dimension (
  stop_id TEXT PRIMARY KEY,                                     -- 站点ID，来自 GTFS static stops.stop_id 或 MTA Bus stop id
  stop_name TEXT NOT NULL,                                      -- 站点名称，来自 GTFS static stops.stop_name
  mode TEXT NOT NULL,                                           -- 交通方式：subway/bus
  latitude DOUBLE PRECISION NOT NULL,                           -- 纬度，来自 GTFS static stops.stop_lat
  longitude DOUBLE PRECISION NOT NULL,                          -- 经度，来自 GTFS static stops.stop_lon
  geom GEOMETRY(POINT, 4326) NULL,                               -- PostGIS 站点点位，由 longitude/latitude 生成，用于最近站点查询
  parent_station_id TEXT NULL,                                  -- 父站ID，来自 GTFS static stops.parent_station（如存在）
  wheelchair_boarding TEXT NULL,                                -- 无障碍信息，来自 GTFS static stops.wheelchair_boarding（如存在）
  source TEXT NOT NULL,                                         -- 数据来源：mta_static_gtfs/mta_subway_stations/bus_static_gtfs
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()                   -- 本行最后更新时间
);

-- 12) 实时发车预测表：支撑“某站某线路下一班/下两班什么时候来”。
-- 作用：把 GTFS-RT TripUpdate/StopTimeUpdate 或 Bus Time TripUpdates 解析成 Agent 可直接查询的预测记录。
CREATE TABLE IF NOT EXISTS app_transit_realtime_prediction (
  prediction_id TEXT PRIMARY KEY,                               -- 预测ID，建议由 source + trip_id + stop_id + arrival/departure 时间生成哈希
  mode TEXT NOT NULL,                                           -- 交通方式：subway/bus
  stop_id TEXT NOT NULL REFERENCES app_transit_stop_dimension(stop_id), -- 站点ID，来自 StopTimeUpdate.stop_id
  route_id TEXT NOT NULL,                                       -- 线路ID，来自 TripDescriptor.route_id 或 GTFS route_id
  trip_id TEXT NULL,                                            -- 行程ID，来自 TripDescriptor.trip_id（可能为空）
  direction_id TEXT NULL,                                       -- 方向ID，来自 TripDescriptor.direction_id 或静态 GTFS trips.direction_id
  stop_sequence INTEGER NULL,                                   -- 站序，来自 StopTimeUpdate.stop_sequence（可能为空）
  arrival_time TIMESTAMP NULL,                                  -- 预计到达时间，来自 StopTimeUpdate.arrival.time
  departure_time TIMESTAMP NULL,                                -- 预计出发时间，来自 StopTimeUpdate.departure.time
  delay_seconds INTEGER NULL,                                   -- 延误秒数，来自 StopTimeEvent.delay（若 feed 提供）
  schedule_relationship TEXT NULL,                              -- 计划关系，来自 StopTimeUpdate.schedule_relationship
  prediction_rank INTEGER NULL,                                 -- 同站同线排序后的第几班，系统派生
  source TEXT NOT NULL,                                         -- 数据来源：mta_subway_gtfs_rt/mta_bus_time_gtfs_rt
  feed_timestamp TIMESTAMP NULL,                                -- GTFS-RT FeedHeader.timestamp，表示 feed 生成时间
  fetched_at TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 系统实际请求 API 的时间
  expires_at TIMESTAMP NOT NULL,                                -- 短缓存过期时间，通常 fetched_at + 30-60 秒
  raw_source JSONB NOT NULL DEFAULT '{}'::jsonb                 -- 原始 TripUpdate/StopTimeUpdate 片段
);

-- 13) 实时通勤结果缓存表：支撑“从某地到某地，现在怎么走”的 30-60 秒结果复用。
-- 作用：缓存已组装好的路线结果，包含步行到站、等车、乘车、到达时间。
CREATE TABLE IF NOT EXISTS app_transit_trip_result_cache (
  cache_key TEXT PRIMARY KEY,                                    -- 缓存键：origin + destination + mode + route/stop 组合哈希
  session_id TEXT NULL,                                          -- 会话ID，可为空
  origin_text TEXT NULL,                                         -- 用户输入的出发点文本
  destination_text TEXT NULL,                                    -- 用户输入的目的地文本
  mode TEXT NOT NULL,                                            -- 返回的交通方式：subway/bus
  origin_stop_id TEXT NULL REFERENCES app_transit_stop_dimension(stop_id), -- 实际使用的出发站
  destination_stop_id TEXT NULL REFERENCES app_transit_stop_dimension(stop_id), -- 实际使用的到达站（如能确定）
  route_id TEXT NULL,                                            -- 使用线路
  walking_to_stop_minutes INTEGER NULL,                          -- 步行到站时间，系统由距离/地图服务派生
  waiting_minutes INTEGER NULL,                                  -- 等车时间，系统由当前时间和 departure_time 派生
  in_vehicle_minutes INTEGER NULL,                               -- 车上时间，静态 GTFS/路线估算派生
  total_minutes INTEGER NULL,                                    -- 总通勤时间，步行+等车+乘车+到站步行
  recommended_leave_at TIMESTAMP NULL,                           -- 推荐出门时间，系统派生
  estimated_arrival_at TIMESTAMP NULL,                           -- 预计到达时间，系统派生
  next_departures JSONB NOT NULL DEFAULT '[]'::jsonb,            -- 下一班/下两班车，来自 app_transit_realtime_prediction
  realtime_used BOOLEAN NOT NULL DEFAULT FALSE,                  -- 是否使用实时数据
  fallback_used BOOLEAN NOT NULL DEFAULT FALSE,                  -- 是否使用静态/常规通勤降级
  source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,            -- 使用的数据源快照和时间戳
  fetched_at TIMESTAMP NOT NULL DEFAULT NOW(),                   -- 本结果生成时间
  expires_at TIMESTAMP NOT NULL                                  -- 缓存过期时间，通常 fetched_at + 30-60 秒
);

-- 14) 实时通勤匿名查询日志表：支撑 Demo 指标、常查路线分析、工具调用成功率统计。
-- 作用：不保存个人身份信息，只保存路线、模式、耗时、是否命中缓存等匿名分析字段。
CREATE TABLE IF NOT EXISTS app_transit_query_log (
  query_id TEXT PRIMARY KEY,                                    -- 查询日志ID
  session_id TEXT NULL,                                         -- 会话ID，可匿名化
  query_time TIMESTAMP NOT NULL DEFAULT NOW(),                  -- 查询发生时间
  origin_text TEXT NULL,                                        -- 用户输入中的出发点文本
  destination_text TEXT NULL,                                   -- 用户输入中的目的地文本
  mode_requested TEXT NULL,                                     -- 用户要求的方式：subway/bus/either/unknown
  mode_returned TEXT NULL,                                      -- 最终返回方式：subway/bus/fallback
  origin_stop_id TEXT NULL,                                     -- 实际使用的出发站点ID
  route_id TEXT NULL,                                          -- 实际查询线路
  cache_hit BOOLEAN NOT NULL DEFAULT FALSE,                     -- 是否命中短缓存
  realtime_success BOOLEAN NOT NULL DEFAULT FALSE,              -- 是否成功拿到实时数据
  fallback_used BOOLEAN NOT NULL DEFAULT FALSE,                 -- 是否使用静态/常规通勤降级
  response_latency_ms INTEGER NULL,                            -- 后端处理耗时
  result_summary JSONB NOT NULL DEFAULT '{}'::jsonb             -- 返回摘要：下一班、步行时间、总通勤等
);

-- 15) 会话偏好表：支撑“必填项状态 + 权重状态面板 + 追问收敛”
-- 作用：保存用户当前会话的约束、权重和槽位状态，保证多轮对话一致。
CREATE TABLE IF NOT EXISTS app_session_profile (
  session_id TEXT PRIMARY KEY,                                      -- 会话唯一ID（前后端用于关联同一轮咨询）
  target_area_id TEXT NULL REFERENCES app_area_dimension(area_id),  -- 目标地区ID（唯一硬性必填）
  budget_min NUMERIC(10,2) NULL,                                    -- 预算下限（美元/月）
  budget_max NUMERIC(10,2) NULL,                                    -- 预算上限（美元/月）
  target_destination TEXT NULL,                                     -- 通勤目的地（学校/公司/地标）
  max_commute_minutes INTEGER NULL,                                 -- 可接受最大单程通勤时长（分钟）
  lease_term_months INTEGER NULL,                                   -- 租期（月）
  move_in_date DATE NULL,                                           -- 期望入住日期
  weight_safety NUMERIC(5,2) NOT NULL DEFAULT 0.30,                -- 安全维度权重
  weight_commute NUMERIC(5,2) NOT NULL DEFAULT 0.30,               -- 通勤维度权重
  weight_rent NUMERIC(5,2) NOT NULL DEFAULT 0.20,                  -- 租金维度权重
  weight_convenience NUMERIC(5,2) NOT NULL DEFAULT 0.10,           -- 便利设施维度权重
  weight_entertainment NUMERIC(5,2) NOT NULL DEFAULT 0.10,         -- 娱乐设施维度权重
  weights_source TEXT NOT NULL DEFAULT 'default',                  -- 权重来源（default/user/inferred）
  slots_json JSONB NOT NULL DEFAULT '{}'::jsonb,                   -- 槽位抽取结果（值+置信度+文本片段）
  missing_required JSONB NOT NULL DEFAULT '[]'::jsonb,             -- 当前缺失的必填项列表
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()                      -- 本会话配置最后更新时间
);

-- 16) 推荐结果表：支撑“收敛到1-2区 + 解释”
-- 作用：记录每次推荐结果，方便展示、复盘和A/B对比。
CREATE TABLE IF NOT EXISTS app_session_recommendation (
  session_id TEXT NOT NULL REFERENCES app_session_profile(session_id), -- 所属会话ID
  generated_at TIMESTAMP NOT NULL DEFAULT NOW(),                       -- 该次推荐生成时间
  rank_no INTEGER NOT NULL,                                            -- 排名（1,2,3...）
  area_id TEXT NOT NULL REFERENCES app_area_dimension(area_id),        -- 推荐地区ID
  total_score NUMERIC(6,2) NOT NULL,                                   -- 综合得分
  score_breakdown JSONB NOT NULL,                                      -- 各维度分数明细
  reasons JSONB NOT NULL,                                              -- 推荐理由列表
  risks JSONB NOT NULL,                                                -- 风险提示列表
  PRIMARY KEY (session_id, generated_at, rank_no)
);

-- 17) 数据同步任务日志表：支撑 data-sync-service 状态查询、失败排查和 API 额度控制。
-- 作用：记录每次外部数据同步、聚合、地图图层生成任务的执行结果。
CREATE TABLE IF NOT EXISTS app_data_sync_job_log (
  job_id TEXT PRIMARY KEY,                                      -- 同步任务执行ID，建议 job_name + started_at 生成
  job_name TEXT NOT NULL,                                      -- 任务名，如 sync_nypd_crime/sync_overpass_poi/run_bootstrap
  status TEXT NOT NULL,                                        -- 状态：running/succeeded/failed/partial
  trigger_type TEXT NOT NULL,                                  -- 触发方式：manual/scheduled/bootstrap
  target_scope JSONB NOT NULL DEFAULT '{}'::jsonb,             -- 同步范围，如 seed areas、date range、source name
  started_at TIMESTAMP NOT NULL DEFAULT NOW(),                 -- 任务开始时间
  finished_at TIMESTAMP NULL,                                  -- 任务结束时间
  rows_fetched INTEGER NOT NULL DEFAULT 0,                     -- 从外部源拉取的记录数
  rows_written INTEGER NOT NULL DEFAULT 0,                     -- 写入/更新数据库的记录数
  api_calls_used INTEGER NOT NULL DEFAULT 0,                   -- 本任务消耗的外部 API 调用次数
  error_code TEXT NULL,                                        -- 错误码，如 API_TIMEOUT/RATE_LIMITED/DB_ERROR
  error_message TEXT NULL,                                     -- 错误摘要，不保存 API Key 或敏感响应
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb                  -- 扩展信息，如重试次数、聚合耗时、跳过原因
);

-- PostGIS 与常用查询索引：保证空间归属、区域查询、时间窗口查询性能。
CREATE INDEX IF NOT EXISTS idx_area_dimension_geom
  ON app_area_dimension USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_crime_incident_geom
  ON app_crime_incident_snapshot USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_crime_incident_area_date
  ON app_crime_incident_snapshot (area_id, occurred_date);
CREATE INDEX IF NOT EXISTS idx_crime_incident_area_category
  ON app_crime_incident_snapshot (area_id, offense_category);

CREATE INDEX IF NOT EXISTS idx_map_poi_geom
  ON app_map_poi_snapshot USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_map_poi_area_type_category
  ON app_map_poi_snapshot (area_id, poi_type, category_code);

CREATE INDEX IF NOT EXISTS idx_rental_listing_geom
  ON app_area_rental_listing_snapshot USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_rental_listing_area_status_price
  ON app_area_rental_listing_snapshot (area_id, listing_status, monthly_rent);

CREATE INDEX IF NOT EXISTS idx_transit_stop_geom
  ON app_transit_stop_dimension USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_transit_stop_mode
  ON app_transit_stop_dimension (mode);

CREATE INDEX IF NOT EXISTS idx_data_sync_job_name_started
  ON app_data_sync_job_log (job_name, started_at DESC);
```

### 6.1 指标来源字段对照（防止“列不存在”）
1. `crime_count_30d`：`qgea-i56i.cmplnt_fr_dt` + `latitude/longitude` 空间归属到 `nta2020`
2. `app_crime_incident_snapshot`：来自 `qgea-i56i.cmplnt_num/cmplnt_fr_dt/cmplnt_fr_tm/ofns_desc/pd_desc/law_cat_cd/boro_nm/latitude/longitude`，用于犯罪类型、时间段和明细查询
3. `complaint_noise_30d`：`erm2-nwe9.created_date` + `complaint_type/descriptor` + 坐标归属
4. `entertainment_poi_count`：由 `app_area_entertainment_category_daily.poi_count` 按地区/日期求和
5. `convenience_facility_count`：由 `app_area_convenience_category_daily.facility_count` 按地区/日期求和
6. `app_map_poi_snapshot`：来自 Overpass tags、Facilities 经纬度、NYPD 经纬度、MTA/RentCast 经纬度；用于点位和热力图
7. `app_map_layer_cache`：由 `app_area_dimension.geom/geom_geojson`、`app_area_metrics_daily`、`app_map_poi_snapshot` 生成 GeoJSON；用于前端轻量加载
8. `transit_station_count`：`39hk-dx4f.gtfs_latitude/gtfs_longitude` 空间归属
9. `area_id/area_name`：`9nt8-h7nd.nta2020/ntaname`
10. `rent_index_value`：ZORI 区域映射结果（外部下载数据经 area 映射后入库）
11. `app_area_rental_listing_snapshot`：来自 RentCast `/listings/rental/long-term`；字段来自 `id/formattedAddress/zipCode/latitude/longitude/propertyType/bedrooms/bathrooms/squareFootage/status/price/listedDate/lastSeenDate/daysOnMarket/listingAgent`
12. `app_area_rental_market_daily`：优先由 `app_area_rental_listing_snapshot.monthly_rent` 聚合得到；若用 RentCast `/markets`、ZORI 或 HUD FMR，则 `source` 和 `data_quality` 必须标明不是实时房源
13. `app_area_rent_benchmark_monthly`：来自 RentCast `/markets`、ZORI 或 HUD FMR；用于基准对照，不替代真实房源清单
14. `app_transit_stop_dimension`：来自 GTFS static `stops.txt` 或 MTA 站点数据；字段来自 `stop_id/stop_name/stop_lat/stop_lon/parent_station/wheelchair_boarding`
15. `app_transit_realtime_prediction`：来自 GTFS-RT `TripUpdate/StopTimeUpdate` 或 Bus Time `TripUpdates`；字段来自 `trip_id/route_id/direction_id/stop_id/stop_sequence/arrival/departure/delay/schedule_relationship`
16. `app_transit_trip_result_cache`：由实时预测、站点维表、步行时间和静态通勤估算组合派生；用于 30-60 秒结果缓存
17. `app_transit_query_log`：来自用户实时通勤查询过程；只保存匿名路线和调用结果，不保存个人身份信息
18. `weather.current_query / weather.forecast_query`：来自 NWS `/points/{lat},{lon}` 和 `forecastHourly`；MVP 不建长期业务表，使用 Redis 缓存返回结构化 forecast periods

### 6.1C 地图可视化字段来源校验

| 业务字段 | 首选来源 | 源字段/接口 | 是否可直接得到 |
|---|---|---|---|
| `area_id` | NTA | `9nt8-h7nd.nta2020` | 是 |
| `geom_geojson` | NTA | `9nt8-h7nd.the_geom` 或 GeoJSON export | 是 |
| `geom` | NTA | `9nt8-h7nd.the_geom` 转 `GEOMETRY(MULTIPOLYGON, 4326)` | 是，需转换 |
| `crime_index_100` | 聚合字段 | `qgea-i56i.latitude/longitude + cmplnt_fr_dt` 聚合 | 是，需计算 |
| `poi latitude/longitude` | Overpass / Facilities | OSM element lat/lon 或 `67g2-p84d.latitude/longitude` | 是 |
| `poi geom` | 派生字段 | `longitude/latitude` 转 `GEOMETRY(POINT, 4326)` | 是，需计算 |
| `poi category` | Overpass / Facilities | `tags.amenity/tags.shop/facgroup/facsubgrp` | 是 |
| `heatmap intensity` | 派生字段 | count/rate/index 标准化 | 是，需计算 |
| `geojson` | 派生字段 | PostGIS 查询结果转 FeatureCollection | 是，需计算 |
| `style_hint` | 派生字段 | 指标类型 + 数值范围 | 是，需计算 |

### 6.1D 犯罪事件明细字段来源校验

| 业务字段 | 首选来源 | 源字段/接口 | 是否可直接得到 |
|---|---|---|---|
| `incident_id` | NYPD Complaint Data | `cmplnt_num` | 是 |
| `occurred_date` | NYPD Complaint Data | `cmplnt_fr_dt` | 是 |
| `occurred_at` | NYPD Complaint Data | `cmplnt_fr_dt + cmplnt_fr_tm` | 是，需合成 |
| `occurred_hour` | NYPD Complaint Data | `cmplnt_fr_tm` | 是，需解析 |
| `borough` | NYPD Complaint Data | `boro_nm` | 是 |
| `offense_category` | NYPD Complaint Data | `ofns_desc` | 是，需标准化大小写/空值 |
| `offense_description` | NYPD Complaint Data | `ofns_desc` 或 `pd_desc` | 是 |
| `law_category` | NYPD Complaint Data | `law_cat_cd` | 是 |
| `latitude/longitude` | NYPD Complaint Data | `latitude/longitude` | 是，部分记录可能为空 |
| `geom` | 派生字段 | `longitude/latitude` 转 `GEOMETRY(POINT, 4326)` | 是，需计算 |
| `area_id` | NTA 空间归属 | `latitude/longitude + app_area_dimension.geom` | 是，需计算 |

说明：如果 NYPD 记录缺少经纬度，则不能可靠归属到 NTA；该记录不应进入 `app_crime_incident_snapshot` 的区域级查询，或必须标记为空间归属失败。

### 6.1B 实时通勤表字段来源校验

| 业务字段 | 首选来源 | 源字段/接口 | 是否可直接得到 |
|---|---|---|---|
| `stop_id` | GTFS static / Bus static | `stops.stop_id` | 是 |
| `stop_name` | GTFS static / Bus static | `stops.stop_name` | 是 |
| `latitude/longitude` | GTFS static / Bus static | `stops.stop_lat/stops.stop_lon` | 是 |
| `geom` | 派生字段 | `stop_lon/stop_lat` 转 `GEOMETRY(POINT, 4326)` | 是，需计算 |
| `route_id` | GTFS-RT TripUpdate | `TripDescriptor.route_id` 或静态 GTFS route_id | 是 |
| `trip_id` | GTFS-RT TripUpdate | `TripDescriptor.trip_id` | 是，可能为空 |
| `direction_id` | GTFS-RT / Static GTFS | `TripDescriptor.direction_id` 或 `trips.direction_id` | 是，可能需静态表补齐 |
| `stop_sequence` | GTFS-RT StopTimeUpdate | `StopTimeUpdate.stop_sequence` | 是，可能为空 |
| `arrival_time` | GTFS-RT StopTimeUpdate | `StopTimeUpdate.arrival.time` | 是，若 feed 提供 |
| `departure_time` | GTFS-RT StopTimeUpdate | `StopTimeUpdate.departure.time` | 是，若 feed 提供 |
| `delay_seconds` | GTFS-RT StopTimeEvent | `arrival.delay` 或 `departure.delay` | 是，若 feed 提供 |
| `schedule_relationship` | GTFS-RT StopTimeUpdate | `schedule_relationship` | 是 |
| `prediction_rank` | 派生字段 | 同站同线按时间排序 | 是，需计算 |
| `walking_to_stop_minutes` | 派生字段 | 距离/地图服务估算 | 是，需计算 |
| `waiting_minutes` | 派生字段 | `departure_time - now()` | 是，需计算 |
| `in_vehicle_minutes` | 静态 GTFS/路线估算 | `stop_times` 或路线服务 | 是，需计算 |
| `total_minutes` | 派生字段 | 步行+等车+乘车+到站步行 | 是，需计算 |
| `recommended_leave_at` | 派生字段 | `departure_time - walking_to_stop_minutes` | 是，需计算 |
| `estimated_arrival_at` | 派生字段 | 当前时间 + `total_minutes` | 是，需计算 |

### 6.1A 租房表字段来源校验

| 业务字段 | 首选来源 | 源字段/接口 | 是否可直接得到 |
|---|---|---|---|
| `listing_id` | RentCast Listings | `id` | 是 |
| `formatted_address` | RentCast Listings | `formattedAddress` | 是 |
| `zip_code` | RentCast Listings | `zipCode` | 是 |
| `latitude/longitude` | RentCast Listings | `latitude/longitude` | 是 |
| `geom` | 派生字段 | `longitude/latitude` 转 `GEOMETRY(POINT, 4326)` | 是，需计算 |
| `property_type` | RentCast Listings | `propertyType` | 是 |
| `bedrooms/bathrooms` | RentCast Listings | `bedrooms/bathrooms` | 是 |
| `bedroom_type` | 派生字段 | 由 `bedrooms` 转换 | 是，需转换 |
| `square_footage` | RentCast Listings | `squareFootage` | 是 |
| `monthly_rent` | RentCast Listings | `price` | 是 |
| `listing_status` | RentCast Listings | `status` | 是 |
| `listed_date` | RentCast Listings | `listedDate` | 是 |
| `last_seen_date` | RentCast Listings | `lastSeenDate` | 是 |
| `days_on_market` | RentCast Listings | `daysOnMarket` | 是 |
| `listing_agent_name/phone` | RentCast Listings | `listingAgent.name/phone` | 可能为空，不能做必填 |
| `rent_min/median/max` | 聚合字段 | `monthly_rent` 分组聚合 | 是，需聚合 |
| `listing_count` | 聚合字段 | 房源条数 count | 是，需聚合 |
| `benchmark_rent` | ZORI/HUD/RentCast Markets | 对应基准源字段 | 是，需按源映射 |

### 6.2 分类映射表（只使用源数据可得到的字段）

娱乐设施分类来自 Overpass。Overpass 返回的是 OSM element 的 `tags` 对象，因此分类规则必须绑定到 `tags.<key>=<value>`：

| category_code | category_name | source | source_key | source_value | 可获得性 |
|---|---|---|---|---|---|
| `bar` | 酒吧 | `overpass` | `tags.amenity` | `bar` | 可由 OSM tags 得到 |
| `pub` | 酒馆 | `overpass` | `tags.amenity` | `pub` | 可由 OSM tags 得到 |
| `nightclub` | 夜店 | `overpass` | `tags.amenity` | `nightclub` | 可由 OSM tags 得到 |
| `cinema` | 电影院 | `overpass` | `tags.amenity` | `cinema` | 可由 OSM tags 得到 |
| `theatre` | 剧院 | `overpass` | `tags.amenity` | `theatre` | 可由 OSM tags 得到 |
| `restaurant` | 餐厅 | `overpass` | `tags.amenity` | `restaurant` | 可由 OSM tags 得到；是否计入娱乐总分需业务决定 |

便利设施分类分两类来源。优先用 NYC Facilities 已核验字段；Facilities 没有的类别才用 Overpass：

| category_code | category_name | source | source_key | source_value | 可获得性 |
|---|---|---|---|---|---|
| `park` | 公园/广场 | `67g2-p84d` | `facgroup` | `PARKS AND PLAZAS` | 已从真实 API 样本/聚合值核验 |
| `library` | 图书馆 | `67g2-p84d` | `facgroup` | `LIBRARIES` | 已从真实 API 样本/聚合值核验 |
| `school_k12` | K-12 学校 | `67g2-p84d` | `facgroup` | `SCHOOLS (K-12)` | 已从真实 API 样本/聚合值核验 |
| `health_care` | 医疗设施 | `67g2-p84d` | `facgroup` | `HEALTH CARE` | 已从真实 API 样本/聚合值核验 |
| `cultural` | 文化机构 | `67g2-p84d` | `facgroup` | `CULTURAL INSTITUTIONS` | 已从真实 API 样本/聚合值核验 |
| `supermarket` | 超市 | `overpass` | `tags.shop` | `supermarket` | 可由 OSM tags 得到 |
| `convenience_store` | 便利店 | `overpass` | `tags.shop` | `convenience` | 可由 OSM tags 得到 |
| `gym` | 健身房 | `overpass` | `tags.leisure` | `fitness_centre` | 可由 OSM tags 得到 |
| `pharmacy` | 药店 | `overpass` | `tags.amenity` | `pharmacy` | 可由 OSM tags 得到 |

入库规则：如果某个分类无法从 `source_key/source_value` 中匹配到源数据，就不能写入分类表，也不能展示给用户。

## 7. MVP 数据栈（最终建议）
- `qgea-i56i`（犯罪）
- `erm2-nwe9`（311）
- `9nt8-h7nd`（区域）
- `67g2-p84d / 2fpa-bnsx`（设施）
- `39hk-dx4f`（交通站点）
- `Overpass API`（娱乐 POI）
- `RentCast /listings/rental/long-term`（真实租房房源）
- `RentCast /markets`（租金市场统计，若 API 配额允许）
- `ZORI`（公开租金基准 fallback）
- `HUD FMR`（政府口径租金基准备选）
- `National Weather Service API`（当前/小时级天气预报）
- `MapTiler Cloud + MapLibre GL JS`（推荐前端底图）
- `Protomaps PMTiles`（无 key 底图备选）

## 8. 开发前核验清单（业务表版）
1. 每个 API 跑通样本请求（100-1000 条）
2. 核验主键字段（不存在则生成稳定哈希）
3. 核验时间字段（支持增量）
4. 核验空间字段（支持区域聚合），并确认 PostGIS `geom` 字段和 GiST 索引可用
5. 核验 `app_area_metrics_daily` 每个指标都能由已确认字段计算出来
6. 核验 `app_crime_incident_snapshot` 字段能从 NYPD `qgea-i56i` 得到，并能支持犯罪类型/时间窗口/时间段查询
7. 核验 `app_area_rental_listing_snapshot` 字段能从 RentCast listing response 得到
8. 核验 `app_area_rental_market_daily` 能由房源明细聚合出 `rent_min/rent_median/rent_max/listing_count`
9. 核验 `app_area_rent_benchmark_monthly` 至少能接入一个基准源（RentCast Markets、ZORI 或 HUD FMR）
10. 核验 `app_map_poi_snapshot` 的每个点位都能追溯到源数据经纬度和分类字段
11. 核验 `app_map_layer_cache.geojson` 可以直接被 MapLibre/Leaflet 加载
12. 核验 `MAPTILER_API_KEY` 为空时有 Protomaps/OSM 开发期降级方案
13. 核验 `NWS_USER_AGENT` 已配置，并能通过目标区域中心点拿到 `forecastHourly`
14. 核验 `app_session_profile.target_area_id` 缺失时，Agent 会先追问再回答
15. 核验 `app_data_sync_job_log` 能记录每次同步任务状态、行数、API 调用次数和错误摘要
