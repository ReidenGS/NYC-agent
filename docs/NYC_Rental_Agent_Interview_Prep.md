# NYC 房租查询平台面试准备文档

## 1. 项目一句话介绍

这个项目是一个面向初到纽约用户的 AI 租房决策 Agent，主要服务留学生、短期实习生和刚入职的年轻人。用户可以用自然语言询问某个区域的租金、安全、通勤、便利设施、娱乐设施和天气等信息，系统会自动理解问题、补全必要信息、调用不同领域 Agent 查询数据，最后给出结构化、可解释的回答，并逐步帮助用户收敛到 1-2 个候选居住区域。

**面试回答口径：**

我做这个项目的出发点是解决纽约租房信息分散、区域判断困难的问题。它不是一个传统筛房源网站，而是一个问答驱动的 AI Agent，用户可以像咨询顾问一样提问，系统根据租金、安全、通勤、生活便利度等维度动态分析和推荐区域。

## 2. 业务功能概览

项目的核心业务功能包括：

- **区域问答**：用户可以询问 Astoria、Williamsburg 等区域的安全、娱乐、便利设施、租金和生活环境。
- **租金查询**：支持按区域和户型查询租金区间、租金中位数、房源数量和数据时间。
- **真实房源筛选**：基于预算、户型和目标区域筛选候选房源，用于生成看房清单。
- **安全与犯罪分析**：结合公开犯罪数据，回答某区域近期犯罪情况和安全趋势。
- **便利与娱乐设施分析**：查询附近超市、餐饮、娱乐 POI 的数量和密度。
- **通勤查询**：结合 MTA、GTFS 或实时交通信息，分析通勤可达性和下一班车。
- **天气查询**：支持当前天气和小时级天气预报，作为生活辅助信息。
- **用户偏好与权重更新**：用户可以表达“安全更重要”“预算最多 3000”等偏好，系统会更新会话中的权重和约束。
- **区域推荐与解释**：当信息足够时，系统基于当前权重生成候选区域排序，并解释推荐理由。

**面试回答口径：**

业务上我把它设计成“连续咨询 + 动态更新偏好”的模式。用户不需要一开始填完整表单，只要自然语言提问，Agent 会根据当前问题判断是否需要追问，比如缺少目标区域或通勤目的地时先补槽，信息足够后再查询和推荐。

## 3. 整体架构

项目后端采用分层、多服务架构，核心组件可以概括为：

```text
Frontend
   |
API Gateway
   |
Orchestrator Agent (LangGraph)
   |
   +-- NL-to-SQL Agent
   |       |
   |       +-- MCP Housing / Safety / Amenity / Entertainment
   |
   +-- Transit Agent  -> MCP Transit
   +-- Weather Agent  -> MCP Weather
   +-- Profile Agent  -> MCP Profile
   |
PostgreSQL + PostGIS / Redis / External APIs
```

各层职责如下：

- **API Gateway**：作为前端入口，负责接收 `/chat` 请求、创建或透传 `session_id`、生成 `trace_id`、做轻量校验和限流，不直接处理复杂业务逻辑。
- **Orchestrator Agent**：项目的核心编排层，负责意图识别、槽位抽取、地名解析、缺槽追问、Agent 调度、结果聚合和最终回答。
- **Domain Agents**：负责特定领域能力，比如通勤、天气、用户画像等。下游 Agent 设计为无状态服务，完全依赖 Orchestrator 传入的结构化 slots。
- **NL-to-SQL Agent**：统一接管租金、房源、安全、便利设施、娱乐设施等 SQL 类查询，把自然语言问题转成受控 SQL plan。
- **MCP 工具层**：封装数据库、外部 API 和缓存访问，是工具调用和安全边界。MCP 接收结构化参数，不直接理解自然语言。
- **PostgreSQL/PostGIS**：存储区域、房源、租金、犯罪、POI 等业务数据，并支持地理空间查询。
- **Redis**：用于实时交通、天气缓存、API 限流和外部 API 调用频率控制。

**面试回答口径：**

我在架构上没有把所有能力写进一个大 Agent，而是拆成 Gateway、Orchestrator、领域 Agent、NL-to-SQL Agent 和 MCP 工具层。这样 Orchestrator 负责推理和调度，MCP 负责可靠的数据访问，每一层职责比较清楚，也更容易调试和替换。

## 4. 核心请求链路

用户提问后，系统的主链路如下：

1. 前端把用户问题发送到 `POST /chat`。
2. API Gateway 透传请求到 Orchestrator Agent。
3. Orchestrator 先从 LangGraph checkpoint 中恢复当前会话状态，包括历史消息、目标区域、预算、偏好权重和待追问字段。
4. Orchestrator 使用 LLM 进行意图识别和槽位抽取，例如判断用户是在问租金、安全、通勤还是区域推荐。
5. 如果缺少关键槽位，比如用户问“这里安全吗”但没有目标区域，系统先追问，不直接调用下游 Agent。
6. 如果槽位齐全，Orchestrator 根据 `task_type` 选择合适的 Agent。
7. SQL 类问题会路由到 NL-to-SQL Agent，由它生成 SQL plan，并通过对应 MCP 执行受控只读查询。
8. 实时通勤和天气问题分别调用 Transit Agent 和 Weather Agent，再由对应 MCP 访问外部 API 或缓存。
9. Orchestrator 收集各 Agent 返回的结构化结果，保留来源、时间戳、数据质量和错误状态。
10. 最后由 Orchestrator 生成面向用户的自然语言回答，并更新会话摘要和必要的 profile 快照。

**面试回答口径：**

可以把主链路理解成“理解问题、判断是否追问、调用工具、聚合回答”四步。项目里我比较关注的是让 LLM 只做擅长的自然语言理解和回答生成，而把可控的数据访问、SQL 校验、缓存和错误处理放到代码和 MCP 工具层里。

## 5. Orchestrator Agent 与 LangGraph 编排

Orchestrator 是整个系统的决策中心，使用 LangGraph 实现 ReAct 风格的 6 节点状态机：

- **Node 1 backfill**：如果上一轮系统追问了某个字段，本轮用户回答看起来是在补充该字段，就回填到 state。
- **Node 2 understand**：用 LLM 和 PydanticOutputParser 抽取 intent、areas、constraints 和可持久化字段更新。
- **Node 2.5 persist**：如果用户明确更新了预算、目标区域、偏好等字段，就按需同步到 profile。
- **Node 3 gate**：检查当前 intent 的必填槽位是否齐全，不齐则进入追问分支。
- **Node 4 plan_and_execute**：根据任务类型选择一个或多个下游 Agent，支持多维问题并行调用。
- **Node 5 observe**：收集下游 Agent 返回的完整结构化结果，只基于 status 判断后续路径。
- **Node 6 respond**：用 LLM 根据结构化结果生成最终中文回答，并附带来源、时间窗口和必要提示。

这个设计让每轮对话最多进行两次 LLM 调用：一次用于理解，一次用于回答。其余步骤尽量用规则和代码完成，从而降低成本和不确定性。

**面试回答口径：**

我选择 LangGraph 是因为这个项目不是单轮问答，而是一个有状态、多步骤的 Agent 工作流。LangGraph 可以把理解、追问、执行、观察和回答拆成明确节点，让流程可追踪，也方便在 LangSmith 里看每个节点的耗时和结果。

## 6. A2A 多 Agent 协作设计

项目使用 `python-a2a` 做 Agent-to-Agent 通信。Orchestrator 作为上游编排者，下游 Agent 通过统一消息格式接收任务。

关键设计点：

- 每个 Agent 有自己的 `AgentCard`，描述名称、能力和可处理的任务类型。
- Orchestrator 调用下游 Agent 时，会传入 `task_type`、`session_id`、`slots` 和 `domain_context`。
- 下游 Agent 不主动读取 profile，也不依赖其它 Agent 的状态。
- 如果下游 Agent 发现必要参数缺失，会返回 `clarification_required` 和 `missing_slots`，由 Orchestrator 统一决定怎么追问用户。
- 多意图问题可以并行调用多个 Agent，部分失败不影响其它成功结果。

**面试回答口径：**

多 Agent 的价值主要在职责拆分。比如租房、交通、天气和用户画像的工具、数据源和错误处理都不一样，拆开后每个 Agent 更容易维护。为了避免多 Agent 之间状态混乱，我让下游 Agent 都保持无状态，统一由 Orchestrator 管理会话状态和上下文。

## 7. NL-to-SQL Agent 设计

NL-to-SQL Agent 负责所有 SQL 类业务问题，包括：

- `housing.rent_query`
- `housing.listing_search`
- `neighborhood.crime_query`
- `neighborhood.convenience_query`
- `neighborhood.entertainment_query`
- `area.metrics_query`

它的输入不是原始聊天上下文，而是 Orchestrator 已经整理过的结构化任务，包括 `task_type`、`domain_user_query`、`slots` 和 `domain_context`。NL-to-SQL Agent 根据任务类型按需加载对应领域的 prompt 规则和表结构说明，生成 SQL plan，并选择对应的 MCP 工具执行。

为了降低幻觉和错误查询风险，系统做了两层重试与校验：

- **LLM plan 校验**：检查 LLM 输出是否能解析、`mcp_tool` 是否存在、目标表和任务领域是否匹配。
- **MCP SQL 校验**：MCP Validator 作为最终安全边界，校验 SQL 是否只读、是否访问白名单表和字段、是否有 LIMIT、是否参数化。

**面试回答口径：**

这里我没有让 LLM 直接连数据库，而是让它生成一个受控 SQL plan。真正执行前会先经过本地 plan 校验，再经过 MCP 的 SQL Validator。这样既能利用 LLM 做自然语言到查询意图的转换，又能把数据库访问限制在安全范围内。

## 8. MCP 工具层设计

MCP 层负责把数据库、外部 API 和缓存封装成结构化工具。项目规划了 7 个 MCP 服务：

- `mcp-housing`：租金、房源、租金基准。
- `mcp-safety`：犯罪数据、安全指标。
- `mcp-amenity`：便利设施和生活配套。
- `mcp-entertainment`：娱乐设施和 POI。
- `mcp-transit`：MTA、GTFS、实时通勤。
- `mcp-weather`：National Weather Service 天气数据和缓存。
- `mcp-profile`：用户画像、偏好权重和推荐结果。

MCP 的统一原则是：只接收结构化参数，不接收自然语言；SQL 类工具只允许只读查询；返回结果必须带 `source`、`timestamp`、`confidence` 和 `data_quality`。

**面试回答口径：**

我把 MCP 理解成 Agent 和真实世界数据之间的工具边界。Agent 可以负责推理和任务拆解，但真正访问数据库或外部 API 时，必须走 MCP，这样可以统一做参数校验、SQL 白名单、错误码和数据来源记录。

## 9. 数据与状态管理

项目的数据和状态分为几类：

- **业务数据**：存储在 PostgreSQL/PostGIS 中，包括区域维表、租金聚合表、房源快照、犯罪事件、POI、交通站点等。
- **空间数据**：使用 PostGIS 支持区域匹配、附近设施查询和空间范围分析。
- **会话短期记忆**：使用 LangGraph PostgresSaver，根据 `session_id` 自动 checkpoint 当前对话 state。
- **用户画像快照**：通过 `mcp-profile` 保存预算、目标区域、偏好权重、推荐快照和 conversation summary。
- **短期缓存**：Redis 缓存实时交通、天气响应，也用于 Gateway 限流和外部 API 频率控制。

**面试回答口径：**

状态管理上，我把“会话中的工作副本”和“持久化 profile 快照”分开。对话进行中以 LangGraph state 为准，避免每一轮都去读 profile；只有用户显式更新偏好、生成摘要或推荐结果时，才同步到 mcp-profile。

## 10. 地名解析与 RAG

纽约区域名称存在别名、缩写和模糊表达，例如用户可能说 “near NYU”“Astoria 附近” 或者拼写不完全准确。因此项目在 Orchestrator 的 understand 阶段加入地名解析能力：

- 对用户提到的 `target_area` 做 embedding 检索。
- 高置信度时自动映射到标准 `area_id`。
- 低置信度或候选不唯一时，不强行匹配，而是返回候选让用户确认。
- 映射后的 `area_id` 作为后续租金、安全、POI 和推荐查询的统一主键。

**面试回答口径：**

这个项目里 RAG 的一个具体用途是地名标准化。因为用户说的是自然语言，但后端查询需要标准 area_id，所以我用 embedding 检索把用户输入映射到区域字典；如果置信度不够，就让 Agent 追问确认，避免查错区域。

## 11. 成本、延迟与可靠性设计

项目在 Demo/MVP 阶段有明确的成本和延迟约束：

- 首次问题响应目标控制在 5 秒以内。
- 多维汇总或推荐控制在 30 秒以内。
- 每轮 Orchestrator 尽量最多 2 次 LLM 调用。
- 静态和准静态数据优先从 PostgreSQL 读取。
- 天气、实时交通等高频外部 API 使用 Redis 短缓存。
- 租房数据默认读取已缓存数据，不在每次用户提问时直接调用 RentCast。
- Agent 回答中保留数据来源、时间戳和数据质量，避免把旧数据说成实时数据。

**面试回答口径：**

我在设计时没有把所有问题都交给 LLM 或实时 API。能规则处理的节点就用规则，能缓存的数据就缓存，租房这种成本较高的数据默认读已同步的数据，并在回答中说明时间戳和数据质量。

## 12. 项目难点与解决思路

### 难点一：自然语言问题不完整

用户经常不会一次说清楚区域、预算、通勤目的地和偏好。解决方式是由 Orchestrator 先做 intent 和 slot 判断，缺少关键字段时只追问一个最重要问题，避免一次问太多。

### 难点二：多 Agent 状态容易混乱

如果每个 Agent 都自己读写用户画像，状态会不一致。解决方式是让 Orchestrator 统一管理 state，下游 Agent 无状态化，只根据本轮 payload 执行任务。

### 难点三：LLM 生成 SQL 有风险

LLM 可能生成错误字段、错误表或危险 SQL。解决方式是引入 NL-to-SQL Agent 和 MCP Validator 两层校验，只允许白名单表字段、只读 SELECT、参数化查询和受限 LIMIT。

### 难点四：数据来源不同，质量不一致

租金、犯罪、POI、天气和交通数据的实时性不同。解决方式是在每个 MCP 返回中统一带 source、timestamp、confidence 和 data_quality，让最终回答可以明确说明数据依据。

**面试回答口径：**

我认为这个项目最大的挑战不是单个模型调用，而是让 LLM、Agent、工具和数据源稳定协作。所以我的设计重点是状态统一、工具边界清晰、SQL 可控、数据来源可追踪。

## 13. 面试可能追问与回答

### Q1：为什么要用多 Agent，而不是一个 Agent 做所有事情？

因为这个项目的能力跨越租房、安全、交通、天气、用户画像和推荐，每个领域的数据源、工具和错误处理都不一样。用一个大 Agent 会让 prompt、工具和状态都很复杂。拆成多 Agent 后，Orchestrator 负责统一调度，下游 Agent 负责单一领域能力，模块边界更清晰，也更容易测试和替换。

### Q2：为什么引入 MCP？

MCP 是 Agent 和真实数据源之间的工具层。它的价值是把数据库和外部 API 封装成结构化工具，同时统一做参数校验、SQL 安全校验、错误码、数据来源和时间戳记录。这样 LLM 不会直接访问数据库，系统可控性更强。

### Q3：如何避免 LLM 生成错误 SQL？

我没有让 LLM 直接执行 SQL，而是让 NL-to-SQL Agent 先生成 SQL plan。系统会检查 task_type、mcp_tool、目标表是否匹配；真正执行前，MCP Validator 还会检查是否只读、是否访问白名单表字段、是否包含 LIMIT、是否参数化。校验失败会把错误反馈给 LLM 重试，超过次数后返回 no_data 或明确错误原因。

### Q4：如果用户没有说清楚问题怎么办？

Orchestrator 会先判断当前 intent 的必填槽位是否齐全。例如租金、安全和天气一般都需要目标区域，如果缺少 target_area，就先追问区域；问通勤则可能需要目的地或出发点。追问策略是一次只问一个对当前问题影响最大的字段，最多连续追问 3 轮。

### Q5：为什么用 LangGraph？

因为这个项目不是简单的一问一答，而是需要有状态、多步骤、可追踪的工作流。LangGraph 可以把 backfill、understand、gate、plan_execute、observe、respond 拆成明确节点，每个节点职责清楚，并且可以通过 checkpoint 恢复会话状态。

### Q6：这个项目里 RAG 用在哪里？

主要用在地名解析和区域标准化上。用户可能用自然语言描述区域，系统需要把它映射成标准 area_id 才能查数据库。通过 embedding 检索可以召回候选区域，高置信时自动匹配，低置信时让用户确认。

### Q7：如何控制 LLM 成本？

Orchestrator 每轮最多 2 次 LLM 调用，一次理解用户问题，一次生成最终回答。中间的槽位校验、路由、状态更新和工具执行尽量用规则和代码完成。实时数据也会通过 Redis 做缓存，租房数据默认读取已同步的数据库快照。

### Q8：如果某个 Agent 或工具调用失败怎么办？

下游 Agent 返回统一 status，例如 `success`、`clarification_required`、`no_data`、`dependency_failed` 或 `unsupported_data_request`。Orchestrator 不强行解析每个 Agent 的内部字段，而是根据 status 决定是否追问、降级回答或说明数据暂不可用。多 Agent 并行时，一个失败不影响其它成功结果。

### Q9：你在项目中主要体现了哪些 AI Agent 能力？

主要包括自然语言意图识别、槽位抽取、Prompt Engineering、结构化输出解析、LangGraph 工作流编排、A2A 多 Agent 协作、工具调用、RAG 地名解析和 NL-to-SQL。相比传统后端，我更想强调的是如何把 LLM 能力稳定接入真实业务流程。

### Q10：这个项目如果继续优化，你会做什么？

我会优先优化三点：第一是提升地名解析和候选区域推荐的准确率；第二是完善评测集，用固定问题测试 intent、slot 和最终回答质量；第三是把推荐逻辑从 Orchestrator 中进一步拆出来，等规则复杂后独立成 decision-agent。

## 14. 一分钟项目介绍版本

NYC 房租查询平台是一个面向初到纽约用户的 AI Agent 项目，目标是帮助留学生、实习生或年轻工作人群更高效地判断适合居住的区域。用户可以直接用自然语言询问某个区域的租金、安全、通勤、便利设施、娱乐设施和天气等信息，系统会自动识别意图、补全必要槽位，并调用不同领域 Agent 查询结构化数据。

架构上，我把系统分成 API Gateway、Orchestrator Agent、领域 Agent、NL-to-SQL Agent、MCP 工具层和数据层。Orchestrator 基于 LangGraph 管理整个对话流程，负责意图识别、槽位抽取、缺失信息追问、Agent 调度和结果聚合。SQL 类问题由 NL-to-SQL Agent 统一处理，再通过 MCP 做只读 SQL 校验和执行，避免 LLM 直接访问数据库。通勤、天气和用户画像则分别由独立 Agent 和 MCP 工具处理。

这个项目里我重点实践的是 LLM 应用落地和 AI Agent 架构设计，包括多 Agent 协作、工具调用、结构化输出、RAG 地名解析和 NL-to-SQL 安全边界设计。
