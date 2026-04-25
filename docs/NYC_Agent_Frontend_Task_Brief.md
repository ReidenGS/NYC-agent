# NYC Agent 前端任务说明（给 Gemini / Coding Agent）

## 1. 任务目标
请基于已有业务逻辑和 API Schema 契约，实现一个 React + TypeScript 前端，用于展示 NYC 租房与生活区域决策 Agent。

该前端不是普通聊天机器人 UI，而是一个“Agentic Decision Dashboard”：
- 用户通过自然语言咨询纽约区域
- 页面实时展示 Agent 已理解的目标区域、预算、权重和偏好
- 展示安全、租金、通勤、便利设施、娱乐设施等指标
- 支持地图图层可视化
- 支持 debug 模式展示 A2A / MCP 调用链

## 2. 必须阅读的输入文档
实现前必须阅读：

1. `NYC_Agent_API_Schema_Contract.md`
   - API 契约
   - TypeScript 类型来源
   - request / response schema
   - error envelope

2. `AI_Agent_Business_Logic.md`
   - 产品业务逻辑
   - 用户目标
   - 问答驱动流程
   - 权重和状态面板规则

可选阅读：

3. `NYC_Agent_Backend_Tech_Framework.md`
   - 后端服务结构
   - debug trace 设计
   - Agent / MCP 关系

## 3. 技术栈要求
必须使用：
- React
- TypeScript
- Vite
- CSS Modules / 普通 CSS / Tailwind 三选一

推荐使用：
- TanStack Query：API 请求、缓存、加载状态
- Zustand：轻量前端状态管理
- MapLibre GL JS：真实交互地图渲染、拖拽、缩放、图层交互
- date-fns：时间格式化

不要使用：
- 复杂 SSR 框架
- Next.js，除非明确说明原因
- 大型 UI 套件，除非只轻量使用
- 与 contract 不一致的临时数据结构

## 4. 实现原则
1. 严格遵守 `NYC_Agent_API_Schema_Contract.md`
2. 所有后端响应都使用 `ApiEnvelope<T>`
3. 先定义 TypeScript types，再写 API client，再写组件
4. 后端未完成时可以使用 mock adapter
5. mock 数据必须完全符合 schema contract
6. 不要假设不存在的 API
7. 不要在前端展示数值 `confidence`
8. 数据来源和更新时间必须展示
9. 地图图层必须通过 `map_layer_id` 或 `/areas/{area_id}/map-layers` 加载
10. Debug 信息仅在 debug 模式显示
11. 地图必须优先使用真实 MapLibre GL JS 实例，不要用静态图片或纯 Div 模拟正式地图
12. MapTiler 只作为底图瓦片和样式服务，地图拖拽/缩放/图层交互由 MapLibre GL JS 实现

## 5. 页面结构
MVP 只需要一个主页面：

```text
NYC Housing Agent Dashboard
```

页面分区：

1. 左侧：Chat Panel
2. 右侧上方：Profile / Weight State Panel
3. 右侧中部：Area Metrics Cards
4. 右侧下方：Weather Card + Transit Realtime Card
5. 页面底部或侧边：Map Panel
6. Debug 模式：Trace Debug Panel

移动端：
- Chat 在上
- Profile/Weights 折叠为卡片
- Metrics 横向滚动
- Weather 卡片跟随目标区域展示
- Map 放在下方
- Debug panel 默认折叠

## 6. 必须实现的组件

### 6.1 `ChatPanel`
功能：
- 输入自然语言
- 调用 `POST /chat`
- 展示用户消息和 Agent 回复
- 支持 loading 状态
- 支持 follow-up 问题
- 支持 error 展示

要求：
- 每次 `/chat` 返回后更新 `profile_snapshot`
- 如果返回 `display_refs.map_layer_ids`，通知 MapPanel 加载图层
- 如果 `message_type=follow_up`，在 UI 中明显展示这是追问

### 6.2 `ProfileStatePanel`
功能：
- 展示当前 Agent 理解的用户状态
- 展示必填字段是否缺失
- 展示预算、目标区域、通勤目的地、偏好

必须展示：
- `target_area`
- `budget`
- `target_destination`
- `max_commute_minutes`
- `missing_required_fields`
- `conversation_summary`

要求：
- 用户可以看出 Agent 有没有理解错
- 缺少 `target_area` 时要突出提示

### 6.3 `WeightPanel`
功能：
- 展示五个权重：
  - safety
  - commute
  - rent
  - convenience
  - entertainment

要求：
- 可以用进度条、滑块或比例条展示
- 支持用户修改权重
- 修改后调用 `PATCH /sessions/{session_id}/profile`
- 更新后刷新完整 `profile_snapshot`

### 6.4 `AreaMetricsCards`
功能：
- 调用 `GET /areas/{area_id}/metrics`
- 展示区域指标卡片

卡片至少包括：
- Safety
- Rent
- Commute
- Convenience
- Entertainment
- Weather，作为生活辅助卡片，不进入权重打分

要求：
- 展示关键数字
- 展示数据来源
- 展示更新时间
- 不展示数值置信度

### 6.5 `MapPanel`
功能：
- 调用 `GET /areas/{area_id}/map-layers`
- 使用真实 MapLibre GL JS 实例展示地图
- 支持鼠标/触控拖拽平移
- 支持滚轮缩放、双击缩放和控件缩放
- 支持图层切换
- 支持点击 marker / POI 后展示 popup
- 支持根据目标区域 `fitBounds` 或 `flyTo` 聚焦

图层：
- safety choropleth
- crime heatmap / marker
- entertainment markers
- convenience markers
- rental markers，后续可选

要求：
- 使用 `VITE_MAPTILER_API_KEY` 加载 MapTiler style / tiles
- 如果没有 `VITE_MAPTILER_API_KEY`，允许显示地图 fallback 提示或使用 mock/static fallback，但必须在代码中保留真实 MapLibre 实现路径
- 图层加载失败不能影响聊天功能
- 默认聚焦目标区域
- `dragPan`、`scrollZoom`、`doubleClickZoom` 默认启用
- 地图组件卸载时必须清理 MapLibre 实例，避免重复初始化和内存泄漏
- 不要为了预览方便把最终实现替换成 Canvas/Div 手写拖拽模拟

### 6.6 `TransitRealtimeCard`
功能：
- 调用 `POST /transit/realtime`
- 展示实时通勤信息

必须展示：
- 下一班 / 下两班
- 推荐出发时间
- 步行到站时间
- 等车时间
- 总通勤时间
- 是否实时数据
- fallback 标记

### 6.7 `WeatherCard`
功能：
- 调用 `GET /areas/{area_id}/weather`
- 默认展示目标区域当前到未来 6 小时天气
- 当 `/chat` 返回天气类 card 时，也能在聊天区展示

必须展示：
- 温度
- 天气摘要
- 降水概率
- 风速/风向
- 预报时间范围
- 数据来源和更新时间
- cached / realtime 标记

要求：
- 没有 `target_area` 时不请求天气
- 天气加载失败不能影响聊天、地图、指标卡片
- 不在前端直接调用 NWS，统一通过后端 Gateway

### 6.8 `DebugTracePanel`
功能：
- 仅 debug 模式显示
- 调用 `GET /debug/traces/{trace_id}`
- 展示 Agent 调用链

必须展示：
- service
- step
- status
- latency_ms
- MCP 名称
- 脱敏 SQL，如果存在

禁止展示：
- API Key
- 完整 Prompt
- 未脱敏 SQL 参数
- 敏感内部上下文

## 7. API Client 要求

必须实现：

```text
src/api/client.ts
src/api/sessions.ts
src/api/chat.ts
src/api/areas.ts
src/api/transit.ts
src/api/weather.ts
src/api/debug.ts
```

所有 API client 必须：
- 使用统一 `ApiEnvelope<T>`
- 处理 `success=false`
- 抛出或返回标准 `ApiError`
- 支持 `trace_id` 读取
- 支持 mock adapter 切换

建议配置：

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=true
VITE_DEBUG_MODE=true
VITE_MAPTILER_API_KEY=
```

## 8. TypeScript 类型要求

建议文件：

```text
src/types/api.ts
src/types/profile.ts
src/types/chat.ts
src/types/area.ts
src/types/map.ts
src/types/transit.ts
src/types/weather.ts
src/types/debug.ts
```

必须包含：
- `ApiEnvelope<T>`
- `ApiError`
- `ProfileSnapshot`
- `ChatRequest`
- `ChatResponseData`
- `AreaMetricsResponse`
- `MapLayersResponse`
- `TransitRealtimeRequest`
- `TransitRealtimeResponse`
- `WeatherResponse`
- `TraceDebugResponse`

所有类型必须参考 `NYC_Agent_API_Schema_Contract.md`。

## 9. Mock Adapter 要求
因为后端可能尚未完成，必须支持 mock。

mock 数据要求：
- 必须符合 schema contract
- 必须覆盖 happy path
- 必须覆盖 missing target_area
- 必须覆盖 no_data
- 必须覆盖 debug trace
- 必须覆盖 map layer empty state

mock 示例场景：
1. 用户问“Astoria 安全吗”
2. 用户问“那边房租贵吗”
3. 用户没给区域，Agent 追问
4. 用户设置“安全最重要”
5. 用户请求实时通勤
6. 用户问“Astoria 今晚会下雨吗”
7. Debug panel 展示 A2A/MCP trace

## 10. 用户体验要求
界面需要体现“决策辅助”，不是普通聊天窗口。

必须体现：
- 当前目标区域
- Agent 已知信息
- 缺失信息
- 权重变化
- 数据来源
- 更新时间
- 地图图层状态
- 天气状态
- Debug trace，debug 模式下

交互要求：
- 用户发送消息后，ChatPanel 立即进入 loading
- API 失败时展示可理解错误
- profile_snapshot 更新时，状态面板同步更新
- 权重被更新时，高亮变化
- 地图加载失败不阻塞其他模块
- 天气加载失败不阻塞其他模块
- no_data 时不要展示为“现实中不存在”，应显示“当前数据库没有匹配数据”

## 11. 视觉方向
目标视觉：
- 面向刚到 NYC 的用户
- 清晰、可信、信息密度适中
- 比普通聊天机器人更像城市决策工作台

建议：
- 使用地图、卡片、权重条、时间线增强信息感
- 避免纯白空洞布局
- 避免默认紫色 AI SaaS 风格
- 移动端必须可用

可以采用：
- NYC subway inspired color accents
- Neighborhood dashboard style
- Neutral background + strong map/data panels

## 12. 实现顺序
请按以下顺序实现：

1. 根据 schema contract 创建 TypeScript types
2. 创建 API client 和 mock adapter
3. 创建 session 初始化逻辑
4. 创建 ChatPanel
5. 创建 ProfileStatePanel 和 WeightPanel
6. 创建 AreaMetricsCards
7. 创建 WeatherCard
8. 创建真实 MapLibre MapPanel
9. 创建 TransitRealtimeCard
10. 创建 DebugTracePanel
11. 组合成 Dashboard 页面
12. 加载状态、错误状态、空状态
13. 检查移动端布局

## 13. 禁止事项
不要：
- 不要发明 contract 中不存在的 API
- 不要绕过 `ApiEnvelope<T>`
- 不要把 confidence 直接展示给用户
- 不要把 debug 默认展示给普通用户
- 不要硬编码 API Key
- 不要假设地图一定可用
- 不要用 Mapbox API Key；本项目使用 `MapTiler + MapLibre`
- 不要把 Canvas/Div 拖拽模拟当作最终地图实现
- 不要把 no_data 解释为现实中不存在
- 不要把 mock 数据结构写得和真实 contract 不一致

## 14. 交付结果
最终交付应包括：

```text
src/types/*
src/api/*
src/mocks/*
src/components/ChatPanel.tsx
src/components/ProfileStatePanel.tsx
src/components/WeightPanel.tsx
src/components/AreaMetricsCards.tsx
src/components/MapPanel.tsx
src/components/TransitRealtimeCard.tsx
src/components/WeatherCard.tsx
src/components/DebugTracePanel.tsx
src/pages/Dashboard.tsx
src/App.tsx
```

并提供：
- 运行命令
- `.env.example`
- mock / real API 切换方式
- 主要组件说明

## 15. 成功标准
前端完成后，应该能演示：

1. 首次打开页面创建 session
2. 用户自然语言询问区域
3. Chat 返回回答
4. 状态面板更新目标区域和权重
5. 指标卡片显示区域数据
6. 地图面板可以真实拖拽、缩放、切换图层，缺少 Key 时显示明确 fallback
7. 实时通勤卡片可以展示下一班车
8. 天气卡片可以默认展示目标区域天气
9. Debug 模式可以展示 Agent/MCP 调用链
10. no_data 和 error 能被正确展示
11. 所有数据结构符合 schema contract
