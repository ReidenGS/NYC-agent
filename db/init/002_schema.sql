-- =====================================================================
-- NYC Agent business schema (PostgreSQL 16 + PostGIS 3.4)
-- This file is a verbatim copy of the SQL block in
--   NYC_Agent_Data_Sources_API_SQL.md  §6
-- That markdown is the canonical contract. If schema must change,
-- edit the markdown first, then regenerate this file.
-- =====================================================================

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
