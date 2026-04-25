# NYC Agent 数据同步与入库设计（MVP）

## 1. 目标
本文件只定义数据如何从外部 API / 文件源同步到 PostgreSQL + PostGIS。

目标：
- 先跑通数据同步，确认数据库中有可查询数据
- 支撑后续 Domain Agent 生成 SQL 查询
- 控制 RentCast、Overpass 等有限额度/公共服务的调用成本
- 为 Demo 提供稳定 seed 数据

不做：
- 不处理用户聊天请求
- 不参与 A2A 对话
- 不调用 LLM
- 不生成用户回答
- 不作为 MCP 工具服务

## 2. 服务边界
新增独立服务：

```text
data-sync-service
```

职责：
- 拉取外部 API / CSV / GTFS 数据
- 清洗和标准化字段
- 生成 PostGIS `geom`
- 做点位到 NTA 区域的空间归属
- 写入业务表
- 生成聚合表
- 生成地图图层缓存
- 控制外部 API 调用额度
- 写入同步日志

不负责：
- 不接收前端业务查询
- 不调用 Orchestrator / Domain Agent
- 不直接给用户返回回答

## 3. 运行方式
`data-sync-service` 使用：

```text
FastAPI + APScheduler + 手动触发接口
```

MVP 接口：

```text
GET  /health
GET  /sync/jobs
GET  /sync/status
POST /sync/run/{job_name}
POST /sync/run-bootstrap
```

规则：
- 服务启动后注册定时任务
- 手动触发用于开发、调试和 Demo
- 定时任务可通过 `.env` 关闭
- 高成本 API 必须手动触发

## 4. Bootstrap Seed
MVP 默认跑 seed，不默认全量同步纽约。

seed 目的：
- 快速得到可演示数据
- 避免外部 API 限额被全量任务消耗
- 保证前端和 Agent 查询先可用

MVP seed 区域：
- Astoria
- Long Island City
- Williamsburg
- Greenpoint
- Midtown
- East Village
- Upper West Side
- Sunnyside
- Bushwick
- Downtown Brooklyn

不包含：
- Jersey City

原因：
- MVP 数据源主要是 NYC Open Data
- Jersey City 不在 NYPD、NYC 311、NYC Facilities、NTA 覆盖范围内
- 后续扩展时需要 NJ 侧数据源

如果用户查询 Jersey City：
```text
当前 MVP 数据主要覆盖 NYC，Jersey City 不在完整数据范围内。
```

## 5. 刷新频率
采用分级刷新策略。

| 数据源 | 刷新策略 | 原因 |
|---|---|---|
| NTA 区域边界 | 手动或月度 | 基本不变 |
| NYPD 犯罪 | 每日或手动 seed | 免费 API，适合更新安全数据 |
| 311 投诉 | 每日或每周 | 免费 API，用于生活质量参考 |
| NYC Facilities | 每周或手动 | 变化慢 |
| Overpass POI | 手动 seed 或每周 | 避免打扰公共服务 |
| RentCast listing | 手动 seed / 低频刷新 | 免费额度很少，必须保护 |
| ZORI | 月度 | 数据本身按月 |
| HUD FMR | 年度或手动 | 政府年度数据 |
| MTA static GTFS | 每周或手动 | 站点/线路变化不高频 |
| MTA realtime | 用户请求时按需 | 不进 data-sync-service 长期任务 |

## 6. RentCast 成本保护
RentCast 不允许自动定时刷新。

规则：
- 只允许手动触发 `POST /sync/run/rentcast_listings`
- 触发前必须显示预计 API 调用次数
- 每次运行有最大调用次数
- 每月有最大调用次数
- 达到上限立即停止
- 失败不自动重试
- 用户查询租房数据默认读 PostgreSQL 缓存

建议 `.env`：

```env
RENTCAST_SYNC_ENABLED=false
RENTCAST_MAX_CALLS_PER_RUN=5
RENTCAST_MAX_CALLS_PER_MONTH=50
```

## 7. 重试策略
同步失败采用分级重试。

| 数据源 | 重试策略 |
|---|---|
| Socrata / NYC Open Data | 最多 3 次，指数退避 |
| MTA static GTFS | 最多 3 次 |
| HUD FMR | 最多 2 次 |
| ZORI CSV | 最多 2 次 |
| Overpass | 最多 1 次，延迟 |
| RentCast | 不自动重试 |

说明：
- RentCast 失败后只记录日志，不自动消耗更多额度
- Overpass 是公共服务，要避免高频重试
- 重试次数和错误摘要写入 `app_data_sync_job_log.metadata`

## 8. 入库策略
采用 MVP 混合策略：
- 不做完整原始数仓
- 关键数据保留 `raw_source` 或 `source_snapshot`
- 业务表直接可被 Agent 查询
- 必要时做轻量 staging

| 数据源 | 入库方式 |
|---|---|
| NTA 边界 | 写 `app_area_dimension`，保留 `geom_geojson` 和 `geom` |
| NYPD 犯罪 | 写 `app_crime_incident_snapshot`，保留 `raw_source`，再聚合到 `app_area_metrics_daily` |
| 311 | 聚合到 `app_area_metrics_daily`，必要字段进 `source_snapshot` |
| Facilities | 写分类聚合表 / `app_map_poi_snapshot` |
| Overpass | 写 `app_map_poi_snapshot` 和分类聚合表 |
| RentCast listing | 写 `app_area_rental_listing_snapshot`，保留 `raw_source`，再聚合到 `app_area_rental_market_daily` |
| ZORI/HUD | 写 `app_area_rent_benchmark_monthly` |
| MTA static | 写 `app_transit_stop_dimension` |
| MTA realtime | 不做长期同步，只由 `mcp-transit` 按需缓存 |
| NWS weather | 不做长期同步，只由 `mcp-weather` 按需缓存 |

天气说明：
- 天气属于短时生活辅助，不进入 data-sync 长期入库。
- `mcp-weather` 直接按区域中心点请求 NWS，并将 `/points` 结果和 hourly forecast 写入 Redis 短缓存。
- data-sync 只需要保证 `app_area_dimension` 有可用中心点/几何边界，供天气查询取坐标。

## 9. PostGIS 空间归属
区域空间归属使用 PostgreSQL + PostGIS，不在 Python 中手写空间判断。

规则：
- `app_area_dimension.geom` 存 NTA `GEOMETRY(MULTIPOLYGON, 4326)`
- 点位表保留 `latitude/longitude`
- 点位表同时生成 `geom GEOMETRY(POINT, 4326)`
- 使用 `ST_Contains` 或 `ST_Intersects` 做点位归属
- 边界附近点可用 `ST_DWithin` 做补偿
- 经纬度为空时 `geom` 为空，不能参与空间归属
- 如果 NTA 源数据是 `POLYGON`，入库时用 `ST_Multi(...)` 转成 `MULTIPOLYGON`

示例：

```sql
UPDATE app_crime_incident_snapshot c
SET area_id = a.area_id
FROM app_area_dimension a
WHERE c.geom IS NOT NULL
  AND ST_Contains(a.geom, c.geom);
```

点位生成：

```sql
UPDATE app_crime_incident_snapshot
SET geom = ST_SetSRID(ST_Point(longitude, latitude), 4326)
WHERE longitude IS NOT NULL
  AND latitude IS NOT NULL;
```

## 10. 聚合任务
聚合表生成采用组合策略：
- 单个数据源同步后跑相关局部聚合
- `bootstrap` 完成后跑一次全量聚合
- 聚合任务也写入 sync log

| 同步任务 | 后续局部聚合 |
|---|---|
| `sync_nypd_crime` | 更新 `app_crime_incident_snapshot` + `app_area_metrics_daily.crime_count_30d` |
| `sync_311_noise` | 更新 `app_area_metrics_daily.complaint_noise_30d` |
| `sync_overpass_poi` | 更新 `app_area_entertainment_category_daily`、`app_area_convenience_category_daily`、`app_map_poi_snapshot` |
| `sync_facilities` | 更新 `app_area_convenience_category_daily`、`app_map_poi_snapshot` |
| `sync_rentcast` | 更新 `app_area_rental_listing_snapshot` + `app_area_rental_market_daily` |
| `sync_zori_hud` | 更新 `app_area_rent_benchmark_monthly` |
| `sync_mta_static` | 更新 `app_transit_stop_dimension` + `app_area_metrics_daily.transit_station_count` |
| `run_bootstrap` | 最后统一重算聚合表和 seed 地图图层 |

## 11. 地图图层缓存
地图图层缓存使用组合策略：
- seed 区域：数据同步后预生成地图图层
- 非 seed 区域：用户请求时按需生成并缓存
- `app_map_layer_cache.expires_at` 控制过期
- 图层生成失败不阻塞文本回答

图层类型：
- 安全区域变色图层
- 犯罪热力/点位图层
- 娱乐设施点位图层
- 便利设施点位图层
- 房源点位图层，后续可选
- 通勤路线图层，后续可选

## 12. 同步任务配置
同步任务配置写入 `.env`。

建议：

```env
SYNC_ENABLE_SCHEDULED_JOBS=true
SYNC_BOOTSTRAP_AREAS=Astoria,Long Island City,Williamsburg,Greenpoint,Midtown,East Village,Upper West Side,Sunnyside,Bushwick,Downtown Brooklyn

RENTCAST_SYNC_ENABLED=false
RENTCAST_MAX_CALLS_PER_RUN=5
RENTCAST_MAX_CALLS_PER_MONTH=50

OVERPASS_MAX_REQUESTS_PER_RUN=10
OVERPASS_SLEEP_SECONDS=3

SOCRATA_PAGE_SIZE=1000
SOCRATA_MAX_ROWS_PER_JOB=50000

MAP_LAYER_PREGENERATE_FOR_SEED=true
```

规则：
- API key 仍然放在数据源文档中的 `.env` 占位里
- RentCast 默认不自动同步
- seed 区域可配置
- 每个外部 API 有独立上限
- scheduled jobs 可关闭

## 13. 同步任务日志
所有同步任务写入：

```text
app_data_sync_job_log
```

记录：
- `job_id`
- `job_name`
- `status`
- `trigger_type`
- `target_scope`
- `started_at`
- `finished_at`
- `rows_fetched`
- `rows_written`
- `api_calls_used`
- `error_code`
- `error_message`
- `metadata`

用途：
- Debug 同步任务
- Demo 展示数据管道
- 控制 RentCast API 消耗
- 判断数据是否过期
- 支撑 `/sync/status`

## 14. MVP 同步顺序
推荐先按这个顺序落地：

1. 初始化 PostGIS 和业务表
2. 同步 NTA 区域边界到 `app_area_dimension`
3. 同步 NYPD 犯罪到 `app_crime_incident_snapshot`
4. 跑犯罪数据空间归属和 `crime_count_30d` 聚合
5. 同步 Overpass / Facilities POI 到 `app_map_poi_snapshot`
6. 跑娱乐/便利分类聚合
7. 手动同步少量 RentCast listing
8. 跑租房市场聚合
9. 同步 MTA static stops
10. 预生成 seed 区域地图图层
11. 检查 `app_data_sync_job_log`
12. 用 SQL 手动验证 seed 区域数据是否可查

## 15. 数据可用性验证
同步完成后至少验证：

```sql
-- seed 区域是否存在
SELECT area_id, area_name, borough
FROM app_area_dimension
WHERE area_name ILIKE '%Astoria%';

-- 犯罪明细是否可查
SELECT offense_category, COUNT(*) AS crime_count
FROM app_crime_incident_snapshot
WHERE area_id = :area_id
GROUP BY offense_category
ORDER BY crime_count DESC
LIMIT 20;

-- 娱乐分类是否可查
SELECT category_code, poi_count
FROM app_area_entertainment_category_daily
WHERE area_id = :area_id
ORDER BY poi_count DESC;

-- 租金市场是否可查
SELECT bedroom_type, rent_median, listing_count
FROM app_area_rental_market_daily
WHERE area_id = :area_id
ORDER BY metric_date DESC;

-- 同步日志是否可查
SELECT job_name, status, rows_written, api_calls_used, started_at, finished_at
FROM app_data_sync_job_log
ORDER BY started_at DESC
LIMIT 20;
```

验证原则：
- 数据为空时先检查 sync log
- 空间归属为空时检查 `geom` 是否生成
- 聚合为空时检查明细表是否有对应 `area_id`
- RentCast 数据为空时不自动刷新，先确认 API 调用预算
