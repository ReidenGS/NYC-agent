"""Node 2 — understand (LLM, PydanticOutputParser).

One LLM call: parse the user's current message into IntentResult. We feed
recent message history so demonstratives ("那娱乐呢？") resolve correctly.
"""
from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.a2a_adapter import call_agent
from app.area_rag import get_area_resolver
from app.config import settings
from app.parsers import IntentResult, intent_parser
from app.state import DetectedArea, OrchestratorState

TRANSIT_RAG_INTENTS = {"transit.realtime_commute", "transit.next_departure"}
TRANSIT_RAG_SLOTS = ("origin", "destination", "stop_name")

SYSTEM_PROMPT = """你是 NYC Agent 的专业意图识别与槽位提取模块。
你的任务是基于用户当前查询、对话历史和已知 profile，识别意图、拆分复合意图、提取槽位，并输出严格符合 JSON schema 的结果。

严格规则：
- 你不得回答用户问题。
- 你不得调用工具。
- 你只输出 JSON，不添加任何额外文本。
- 当前日期由用户消息中的 current_date 提供，时区为 America/New_York。
- 基于整个对话历史补全上下文，但当前用户查询优先级最高。
- detected_areas 只填写当前用户查询里明确提到的区域；如果只是沿用历史/profile 区域，不要放进 detected_areas。

支持意图：
- housing.rent_query：租金、房租、租房价格、租金范围、区域租金概况。
- housing.listing_search：房源、具体 apartment/listing、预算内候选房源。
- neighborhood.crime_query：安全、治安、犯罪、危险、偷窃、抢劫。
- neighborhood.convenience_query：便利、超市、公园、学校、图书馆、日常设施、amenity。
- neighborhood.entertainment_query：娱乐、餐厅、酒吧、夜生活、影院、演出附近生活。
- area.metrics_query：整体/综合区域画像、综合指标、整体评分；只有用户没有点名具体维度时才使用。
- transit.realtime_commute：通勤、从 A 到 B 多久、实时路线、推荐出发时间。
- transit.next_departure：下一班地铁/公交、某线路某站发车。
- weather.current：当前天气、今天是否下雨、现在温度。
- weather.hourly_forecast：未来几小时/指定时间天气。
- comparison：比较两个或多个区域，并且用户明确要求比较。
- out_of_scope：寒暄、问你是谁/能做什么、非业务闲聊，或与 NYC 居住决策无关的问题。
- unknown：业务意图不清楚但可能与 NYC 居住决策相关。

超出范围规则：
- 如果用户问题与 NYC 居住、租房、区域、通勤、天气、生活设施无关，返回 intent="out_of_scope"。
- 如果用户只是寒暄、问候、问你是谁、问你能做什么，也返回 intent="out_of_scope"。
- out_of_scope 不需要 detected_areas、constraints.intent_sequence 或业务槽位。
- unknown 只用于用户疑似在问 NYC 居住相关问题，但表达不清楚，无法判断具体业务意图的情况。
- 不要编造不支持的 intent。

out_of_scope 示例：
- 用户："你好" →
  {{"intent":"out_of_scope","detected_areas":[],"constraints":{{}},"persistable_field_updates":{{}},"confidence":0.95}}
- 用户："你是谁？你是 GPT 吗？" →
  {{"intent":"out_of_scope","detected_areas":[],"constraints":{{}},"persistable_field_updates":{{}},"confidence":0.95}}
- 用户："你能做什么？" →
  {{"intent":"out_of_scope","detected_areas":[],"constraints":{{}},"persistable_field_updates":{{}},"confidence":0.95}}
- 用户："帮我写一首关于春天的诗" →
  {{"intent":"out_of_scope","detected_areas":[],"constraints":{{}},"persistable_field_updates":{{}},"confidence":0.9}}
- 用户："今天美股怎么样？" →
  {{"intent":"out_of_scope","detected_areas":[],"constraints":{{}},"persistable_field_updates":{{}},"confidence":0.9}}

槽位提取规则：
- 所有意图通用：
  - detected_areas：当前查询明确提到的区域，尽量映射 area_id。
  - constraints.intent_sequence：复合意图时必填，列出所有意图，顺序保持用户自然表达顺序。
- housing.rent_query / housing.listing_search：
  - budget 或 budget_monthly：预算，如 "2500"、"$3000以内"。
  - bedroom_type：studio / 1br / 2br / 3br 等。
  - listing_limit：用户明确要求看几个房源时提取。
- neighborhood.crime_query：
  - window_days：用户提到最近多少天/月时提取；未提到可留空。
- neighborhood.convenience_query / neighborhood.entertainment_query：
  - categories：用户明确点名的设施或娱乐场景，如 grocery、park、bar、restaurant。
- transit.realtime_commute：
  - origin、destination、mode。mode 可为 subway / bus / either。
  - 如果用户说"从这个区域/那里出发"，可在 constraints.origin 中填 session/profile 的 target_area_name 或 target_area_id。
- transit.next_departure：
  - mode、route_id、stop_name、direction。
- weather.current / weather.hourly_forecast：
  - target_time：今天/明天/后天/未来X小时/指定时间，转换成清晰文本或 ISO 日期时间；没有时间默认 current。
- comparison：
  - comparison_areas：至少两个区域。
  - comparison_dimension：安全/租金/通勤/便利/娱乐/综合。

复合意图规则：
- 如果用户一句话问多个维度，必须拆成多个 intent，不能压成 area.metrics_query。
- intent 字段填第一个主要意图。
- constraints.intent_sequence 填所有意图。
- 只要用户明确说出具体维度，如租金、安全、通勤、天气、便利、娱乐，就用具体意图，不用 area.metrics_query。
- area.metrics_query 只用于"整体怎么样"、"综合指标"、"区域画像"这类未点名具体维度的问题。

复合意图示例：
- "Astoria 租金和安全怎么样？" →
  intent="housing.rent_query",
  constraints.intent_sequence=["housing.rent_query", "neighborhood.crime_query"]
- "LIC 安全、通勤、房租都看看" →
  intent="neighborhood.crime_query",
  constraints.intent_sequence=["neighborhood.crime_query", "transit.realtime_commute", "housing.rent_query"]
- "Williamsburg 今天下雨吗，晚上有啥可玩？" →
  intent="weather.current",
  constraints.intent_sequence=["weather.current", "neighborhood.entertainment_query"]
- "比较 Astoria 和 Williamsburg 的租金和安全" →
  intent="comparison",
  constraints.intent_sequence=["comparison"],
  constraints.comparison_dimension=["rent", "safety"]

缺槽与追问规则：
- 本节点不直接输出自然语言追问字段；只通过 intent、constraints 和 persistable_field_updates 支持后续 gate 节点判断缺槽。
- 不要为了缺槽把 intent 改成 unknown。能识别意图就识别意图。
- target_area 是 housing、neighborhood、weather、recommendation/area 类问题的必填业务槽；如果当前查询没有区域但 profile 里有 target_area，可让后续节点沿用 profile，不要放进 detected_areas。
- transit 如果已有 origin/destination/mode，不要求 target_area。

上一轮追问补槽规则：
- 如果已知上下文里存在 pending_follow_up，当前用户消息要优先理解为对 pending_follow_up.missing_slots 的回答，而不是全新问题。
- 除非用户明确切换话题，否则沿用 pending_follow_up.asked_intent 作为 intent。
- 结合 pending_follow_up.original_user_query 和当前用户消息恢复完整业务意图。
- 将当前用户消息填入对应缺失槽位：
  - target_area / area_id / area_name：把当前消息当成区域、地点或地址；能映射到 NTA 就填 detected_areas.area_id，否则至少填 detected_areas.area_name。
  - bedroom_type：把当前消息当成户型。
  - budget / budget_monthly：把当前消息当成月租预算。
  - origin：把当前消息当成出发地。
  - destination：把当前消息当成目的地。
  - mode：把当前消息当成交通方式。
  - comparison_dimension：把当前消息当成比较维度。
  - comparison_areas：把当前消息当成要比较的区域列表。
- 当前消息是补槽回答时，不要返回 out_of_scope 或 unknown。

可持久化 profile 更新规则：
- persistable_field_updates 只在用户明确表达稳定偏好/画像时填。
- 普通查询一律不持久化偏好。
- "我预算 2500" → {{"budget": {{"max": 2500, "currency": "USD"}}}}
- "通勤不超过 40 分钟" → {{"max_commute_minutes": 40}}
- "我在 NYU 上学/上班" → {{"target_destination": "NYU"}}
- "我有狗/需要安静/喜欢夜生活" → {{"preferences": ["pet-friendly"]}} / ["quiet"] / ["nightlife"]
- "我更在意安全" → {{"weights": {{"safety": 0.5, "commute": 0.2, "rent": 0.15, "convenience": 0.075, "entertainment": 0.075}}}}

NTA 区域名映射示例：
- Astoria = QN0101
- LIC / Long Island City = QN0102
- Williamsburg = BK0101
- Greenpoint = BK0102
- Midtown = MN0101
- East Village = MN0303
- Upper West Side = MN0702
- Sunnyside = QN0201
- Bushwick = BK0401
- Downtown Brooklyn = BK0201

输出格式要求：
{format_instructions}
"""


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.orchestrator_understand_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.llm_request_timeout_seconds,
        temperature=0,
    )


AREA_ALIASES = {
    "astoria": ("QN0101", "Astoria"),
    "lic": ("QN0102", "Long Island City"),
    "long island city": ("QN0102", "Long Island City"),
    "williamsburg": ("BK0101", "Williamsburg"),
    "greenpoint": ("BK0102", "Greenpoint"),
    "midtown": ("MN0101", "Midtown"),
    "east village": ("MN0303", "East Village"),
    "upper west side": ("MN0702", "Upper West Side"),
    "sunnyside": ("QN0201", "Sunnyside"),
    "bushwick": ("BK0401", "Bushwick"),
    "downtown brooklyn": ("BK0201", "Downtown Brooklyn"),
}

INTENTS_REQUIRING_AREA = {
    "housing.rent_query",
    "housing.listing_search",
    "neighborhood.crime_query",
    "neighborhood.convenience_query",
    "neighborhood.entertainment_query",
    "area.metrics_query",
    "weather.current",
    "weather.hourly_forecast",
}


def _extract_area_text_from_update(update: dict) -> str | None:
    detected = update.get("detected_areas") or []
    if detected:
        first = detected[0]
        name = getattr(first, "area_name", None) if first is not None else None
        if isinstance(name, str) and name.strip():
            return name.strip()
    constraints = update.get("constraints") or {}
    if isinstance(constraints, dict):
        for key in ("target_area", "area_name", "query_area", "area", "target_area_name"):
            value = constraints.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _area_query_for_rag(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    anchor = _extract_destination_from_text(text)
    if anchor:
        text = anchor
    text = re.sub(r"(附近|周边)$", "", text).strip(" ,，。.;；")
    return text or None


def _area_candidate_from_user_text(text: str) -> str | None:
    """Best-effort area phrase extraction used only after LLM extraction fails.

    Keep this conservative: prefer explicit "nearby" anchors and leading area
    phrases before business terms, rather than embedding the whole sentence.
    """
    anchor = _extract_destination_from_text(text)
    if anchor:
        return anchor
    stripped = (text or "").strip()
    if not stripped:
        return None
    patterns = [
        r"^(.+?)(?:的)?(?:房租|租金|房源|安全|治安|犯罪|便利|设施|娱乐|天气|通勤)",
        r"^(.+?)\s+(?:rent|rental|safety|crime|amenity|convenience|entertainment|weather|commute)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip(" ,，。.;；:：!?！？")
        candidate = re.sub(r"^(我想看|我想查|我想了解|想看|想查|查一下|看看|在|关于)\s*", "", candidate)
        candidate = re.sub(r"(?:有(?:什么|啥|哪些|没有)?|有没有|有哪些|有什么|有啥).*$", "", candidate)
        candidate = candidate.strip(" ,，。.;；:：!?！？的")
        if 2 <= len(candidate) <= 80:
            return candidate
    return None


def _reconcile_target_area_fields(update: dict) -> dict:
    area_name = update.get("target_area_name")
    area_query = _area_query_for_rag(area_name)
    if not area_query:
        return update
    try:
        resolver = get_area_resolver()
        resolved = resolver.resolve(area_query)
    except Exception:
        return update
    if resolved.resolved and resolved.area_id and resolved.area_name:
        update["target_area_id"] = resolved.area_id
        update["target_area_name"] = resolved.area_name
        detected = update.get("detected_areas") or []
        if not detected:
            update["detected_areas"] = [
                DetectedArea(area_id=resolved.area_id, area_name=resolved.area_name, source="rag_resolved")
            ]
    return update


def _rag_resolve_area(state: OrchestratorState, update: dict) -> dict:
    intent = str(update.get("intent") or "")
    if intent not in INTENTS_REQUIRING_AREA and not (
        state.pending_follow_up and state.pending_follow_up.asked_slot in {"target_area", "area_id", "area_name"}
    ):
        return update
    existing_detected = update.get("detected_areas") or []
    if existing_detected:
        first = existing_detected[0]
        first_id = getattr(first, "area_id", None) if first is not None else None
        first_name = getattr(first, "area_name", None) if first is not None else None
        if first_id:
            # Guardrail: if LLM emits mismatched (area_id, area_name), trust
            # canonical RAG resolution from area_name.
            first_query = _area_query_for_rag(first_name if isinstance(first_name, str) else None)
            if first_query:
                try:
                    resolver = get_area_resolver()
                    by_name = resolver.resolve(first_query)
                except Exception:
                    return update
                if by_name.resolved and by_name.area_id and by_name.area_name and by_name.area_id != first_id:
                    update["detected_areas"] = [
                        DetectedArea(
                            area_id=by_name.area_id,
                            area_name=by_name.area_name,
                            source="rag_resolved",
                        )
                    ]
                    update["target_area_id"] = by_name.area_id
                    update["target_area_name"] = by_name.area_name
                    constraints = dict(update.get("constraints") or {})
                    constraints["area_resolution"] = {
                        "method": "vector_rag",
                        "resolved": True,
                        "score": by_name.score,
                        "corrected_mismatch": {
                            "original_area_id": first_id,
                            "original_area_name": first_name,
                        },
                    }
                    update["constraints"] = constraints
            return update
        # LLM gave area_name but no area_id -> use RAG to bind canonical id.
        first_query = _area_query_for_rag(first_name if isinstance(first_name, str) else None)
        if first_query:
            try:
                resolver = get_area_resolver()
                result = resolver.resolve(first_query)
            except Exception:
                return update
            constraints = dict(update.get("constraints") or {})
            if result.resolved and result.area_id and result.area_name:
                update["detected_areas"] = [
                    DetectedArea(area_id=result.area_id, area_name=result.area_name, source="rag_resolved")
                ]
                update["target_area_id"] = result.area_id
                update["target_area_name"] = result.area_name
                constraints["area_resolution"] = {
                    "method": "vector_rag",
                    "resolved": True,
                    "score": result.score,
                }
            else:
                constraints["area_resolution"] = {
                    "method": "vector_rag",
                    "resolved": False,
                    "candidates": [
                        {"area_id": c.area_id, "area_name": c.area_name, "borough": c.borough, "score": c.score}
                        for c in (result.candidates or [])
                    ],
                }
            update["constraints"] = constraints
        return update

    # Important: only RAG-resolve area text extracted by LLM understand output.
    # Do not embed the whole raw user sentence here. If extraction failed,
    # fall back to a conservative phrase extractor for explicit area prefixes.
    area_text = _area_query_for_rag(_extract_area_text_from_update(update))
    if not area_text:
        area_text = _area_query_for_rag(_area_candidate_from_user_text(state.current_user_message or ""))
    if not area_text:
        return update
    try:
        resolver = get_area_resolver()
        result = resolver.resolve(area_text)
    except Exception:
        return update

    constraints = dict(update.get("constraints") or {})
    if result.resolved and result.area_id and result.area_name:
        update["detected_areas"] = [
            DetectedArea(area_id=result.area_id, area_name=result.area_name, source="rag_resolved")
        ]
        update["target_area_id"] = result.area_id
        update["target_area_name"] = result.area_name
        constraints["area_resolution"] = {
            "method": "vector_rag",
            "resolved": True,
            "score": result.score,
        }
        update["constraints"] = constraints
        return update

    constraints["area_resolution"] = {
        "method": "vector_rag",
        "resolved": False,
        "candidates": [
            {"area_id": c.area_id, "area_name": c.area_name, "borough": c.borough, "score": c.score}
            for c in (result.candidates or [])
        ],
    }
    update["constraints"] = constraints
    return update


def _rag_resolve_transit(state: OrchestratorState, update: dict) -> dict:
    """Call transit-agent's RAG to resolve origin/destination/stop_name.

    Only fires for transit intents — guarantees no extra A2A round-trip for
    housing/neighborhood/weather flows. Threshold logic lives in transit-agent.
    """
    intent = str(update.get("intent") or "")
    if intent not in TRANSIT_RAG_INTENTS:
        return update
    constraints = dict(update.get("constraints") or {})
    queries: dict[str, str] = {}
    for slot in TRANSIT_RAG_SLOTS:
        v = constraints.get(slot)
        if isinstance(v, str) and v.strip():
            queries[slot] = v.strip()
    if not queries:
        return update
    try:
        response = call_agent(
            "transit",
            task_type="transit.resolve_endpoints",
            session_id=state.session_id,
            payload={"queries": queries},
            trace_id=state.trace_id,
        )
    except Exception:
        # Best-effort: do not block understand on transit RAG failure; the
        # downstream gate/respond path can still ask the user to clarify.
        return update
    if (response or {}).get("status") != "success":
        return update
    resolutions = ((response or {}).get("payload") or {}).get("resolutions") or {}
    if not isinstance(resolutions, dict):
        return update
    constraints["transit_endpoint_resolution"] = {
        "method": "transit_vector_rag",
        "resolutions": resolutions,
    }
    for slot, resolution in resolutions.items():
        if not isinstance(resolution, dict):
            continue
        if resolution.get("resolved"):
            constraints[f"{slot}_resolved"] = {
                "kind": resolution.get("kind"),
                "entity_id": resolution.get("entity_id"),
                "name": resolution.get("name"),
                "mode": resolution.get("mode"),
                "borough": resolution.get("borough"),
                "latitude": resolution.get("latitude"),
                "longitude": resolution.get("longitude"),
                "score": resolution.get("score"),
            }
    update["constraints"] = constraints
    return update


def _detect_areas(text: str) -> list[DetectedArea]:
    lower = text.lower()
    detected: list[DetectedArea] = []
    for alias, (area_id, area_name) in AREA_ALIASES.items():
        if alias in lower:
            detected.append(DetectedArea(area_id=area_id, area_name=area_name, source="user_explicit"))
            break
    return detected


def _detect_intents(text: str) -> list[str]:
    lower = text.lower()

    intents: list[str] = []
    if any(t in lower for t in ["weather", "rain", "temperature"]) or any(t in text for t in ["天气", "下雨", "温度"]):
        intents.append("weather.current")
    if any(t in lower for t in ["rent", "listing", "apartment", "bedroom", "studio", "1br", "2br"]) or any(t in text for t in ["租金", "房租", "房源", "公寓", "户型", "几居"]):
        intents.append("housing.rent_query")
    if any(t in lower for t in ["subway", "bus", "commute", "departure"]) or any(t in text for t in ["地铁", "公交", "通勤", "下一班"]):
        intents.append("transit.realtime_commute")
    if any(t in lower for t in ["bar", "restaurant", "entertainment"]) or any(t in text for t in ["娱乐", "酒吧", "餐厅", "影院"]):
        intents.append("neighborhood.entertainment_query")
    if any(t in lower for t in ["park", "library", "convenience", "amenity"]) or any(t in text for t in ["便利", "超市", "公园", "图书馆", "学校"]):
        intents.append("neighborhood.convenience_query")
    if any(t in lower for t in ["crime", "safe", "safety", "theft", "robbery"]) or any(t in text for t in ["安全", "犯罪", "偷窃", "抢劫"]):
        intents.append("neighborhood.crime_query")
    if not intents and (
        any(t in lower for t in ["hello", "hi", "what can you do", "who are you"])
        or any(t in text for t in ["你好", "你是谁", "你能做什么"])
    ):
        intents.append("out_of_scope")
    return intents


_DEST_NEARBY_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9·\-\'’\s]{2,40})附近")
_BUDGET_RE = re.compile(r"(?:(\d+(?:\.\d+)?)\s*[kK千])|(\d{3,6})")
_BEDROOM_PATTERNS = [
    (re.compile(r"\bstudio\b", re.IGNORECASE), "studio"),
    (re.compile(r"(开间|单间)"), "studio"),
    (re.compile(r"1\s*b\s*1\s*b", re.IGNORECASE), "1br"),
    (re.compile(r"\b1\s*bed\s*1\s*bath\b", re.IGNORECASE), "1br"),
    (re.compile(r"\b1\s*(?:br|b|bed(?:room)?)\b", re.IGNORECASE), "1br"),
    (re.compile(r"(一居|一室|1居|一室一厅|1室1厅)"), "1br"),
    (re.compile(r"2\s*b\s*2\s*b", re.IGNORECASE), "2br"),
    (re.compile(r"\b2\s*bed\s*2\s*bath\b", re.IGNORECASE), "2br"),
    (re.compile(r"\b2\s*(?:br|b|bed(?:room)?)\b", re.IGNORECASE), "2br"),
    (re.compile(r"(两居|两室|2居|两室一厅|2室1厅)"), "2br"),
    (re.compile(r"\b3\s*(?:br|b|bed(?:room)?)\b", re.IGNORECASE), "3br"),
    (re.compile(r"(三居|三室|3居)"), "3br"),
]

_BEDROOM_CUE_RE = re.compile(
    r"(户型|几居|居室|一居|两居|三居|一室|两室|三室|studio|bed|br|b1b|b2b)",
    re.IGNORECASE,
)

_BEDROOM_SYNONYMS = {
    "studio": "studio",
    "efficiency": "studio",
    "开间": "studio",
    "单间": "studio",
    "1b": "1br",
    "1br": "1br",
    "onebed": "1br",
    "onebedroom": "1br",
    "一居": "1br",
    "一室": "1br",
    "1居": "1br",
    "1室1厅": "1br",
    "一室一厅": "1br",
    "1b1b": "1br",
    "1bed1bath": "1br",
    "2b": "2br",
    "2br": "2br",
    "twobed": "2br",
    "twobedroom": "2br",
    "两居": "2br",
    "两室": "2br",
    "2居": "2br",
    "2室1厅": "2br",
    "两室一厅": "2br",
    "2b2b": "2br",
    "2bed2bath": "2br",
    "3b": "3br",
    "3br": "3br",
    "threebed": "3br",
    "threebedroom": "3br",
    "三居": "3br",
    "三室": "3br",
    "3居": "3br",
}


def _extract_destination_from_text(text: str) -> str | None:
    # Capture phrases like "华尔街附近", "NYU附近", "Wall Street 附近"
    if "附近" not in text:
        return None
    prefix = text.split("附近", 1)[0].strip()
    if not prefix:
        return None
    # Keep the nearest clause before "附近".
    prefix = re.split(r"[，。,.;；:：!?！？\n]", prefix)[-1].strip()
    prefix = re.sub(
        r"^(我想看|我想找|我想了解|想看|想找|看看|查一下|查查|在|到|去|住在|住|从)\s*",
        "",
        prefix,
    )
    prefix = re.sub(r"^(find|search|look\s*for|show\s*me)\s+", "", prefix, flags=re.IGNORECASE)
    match = _DEST_NEARBY_RE.search(f"{prefix}附近")
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" ,，。.;；")
    return value or None


def _extract_budget_from_text(text: str) -> float | None:
    lowered = text.lower()
    if not any(k in lowered for k in ("预算", "月租", "rent", "$", "usd", "刀", "美金", "美元", "k")):
        return None
    for m in _BUDGET_RE.finditer(text):
        if m.group(1):
            try:
                return float(m.group(1)) * 1000
            except ValueError:
                continue
        if m.group(2):
            try:
                value = float(m.group(2))
            except ValueError:
                continue
            if value >= 400:
                return value
    return None


def _extract_bedroom_from_text(text: str) -> str | None:
    lowered = (text or "").lower()
    compact = re.sub(r"[\s\-/_,，。:：;；()（）]+", "", lowered)
    if compact in _BEDROOM_SYNONYMS:
        return _BEDROOM_SYNONYMS[compact]

    for key, value in _BEDROOM_SYNONYMS.items():
        if key and key in compact:
            return value
    for pattern, value in _BEDROOM_PATTERNS:
        if pattern.search(text):
            return value
    return None


def _llm_classify_bedroom(text: str) -> str | None:
    if not settings.openai_api_key:
        return None
    try:
        llm = ChatOpenAI(
            model=settings.orchestrator_understand_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_request_timeout_seconds,
            temperature=0,
        )
        out = llm.invoke(
            [
                SystemMessage(content="Return exactly one token from: studio,1br,2br,3br,none."),
                HumanMessage(content=text),
            ]
        ).content
    except Exception:
        return None
    token = str(out or "").strip().lower()
    return token if token in {"studio", "1br", "2br", "3br"} else None


def _apply_budget_bedroom_semantics(state: OrchestratorState, update: dict) -> dict:
    text = state.current_user_message or ""
    if not text:
        return update
    constraints = dict(update.get("constraints") or {})
    persist = dict(update.get("persistable_field_updates") or {})

    budget = _extract_budget_from_text(text)
    if budget is not None:
        constraints.setdefault("budget_monthly", budget)
        persist.setdefault("budget", {"max": budget, "currency": "USD"})

    bedroom = _extract_bedroom_from_text(text)
    if bedroom is None:
        intent = str(update.get("intent") or "")
        if intent.startswith("housing.") or any(k in text.lower() for k in ("户型", "bed", "br", "studio")):
            bedroom = _llm_classify_bedroom(text)
    if bedroom:
        constraints.setdefault("bedroom_type", bedroom)
        persist.setdefault("bedroom_type", bedroom)
    else:
        intent = str(update.get("intent") or "")
        if intent.startswith("housing.") and _BEDROOM_CUE_RE.search(text):
            constraints["bedroom_unrecognized"] = True

    update["constraints"] = constraints
    update["persistable_field_updates"] = persist
    return update


def _force_housing_intent_for_bedroom_query(state: OrchestratorState, update: dict) -> dict:
    text = state.current_user_message or ""
    if not text:
        return update
    intent = str(update.get("intent") or "")
    constraints = dict(update.get("constraints") or {})
    if intent in {"unknown", "out_of_scope"} and _BEDROOM_CUE_RE.search(text):
        update["intent"] = "housing.rent_query"
        if not constraints.get("bedroom_type"):
            constraints["bedroom_unrecognized"] = True
        update["constraints"] = constraints
    return update


def _deterministic_understand(state: OrchestratorState) -> dict:
    """Small local parser used when LLM is unavailable or returns an error.

    It is intentionally conservative: enough to run smoke tests and demo the
    data path without a valid API key, while production still uses the LLM.
    """
    text = state.current_user_message or ""
    detected = _detect_areas(text)
    intents = _detect_intents(text)

    intent = intents[0] if intents else "unknown"

    update: dict = {
        "intent": intent,
        "detected_areas": detected,
        "constraints": {"intent_sequence": intents} if len(intents) > 1 else {},
        "persistable_field_updates": {},
    }
    if detected:
        first = detected[0]
        if first.area_id:
            update["target_area_id"] = first.area_id
            update["target_area_name"] = first.area_name
        elif not state.target_area_id:
            update["target_area_name"] = first.area_name
    update = _force_housing_intent_for_bedroom_query(state, update)
    update = _apply_budget_bedroom_semantics(state, update)
    update = _rag_resolve_transit(state, _rag_resolve_area(state, update))
    return _reconcile_target_area_fields(update)


def understand(state: OrchestratorState) -> dict:
    if not settings.openai_api_key:
        return _deterministic_understand(state)

    llm = _build_llm()
    sys = SystemMessage(
        content=SYSTEM_PROMPT.format(format_instructions=intent_parser.get_format_instructions())
    )

    # Stuff context: known target_area + last 6 messages (auto-supplied via
    # state.messages) + the current user message.
    ctx_lines = []
    if state.target_area_id:
        ctx_lines.append(
            f"已知目标区域: area_id={state.target_area_id} area_name={state.target_area_name}"
        )
    if state.pending_follow_up:
        pending = state.pending_follow_up
        ctx_lines.append("pending_follow_up:")
        ctx_lines.append(f"- asked_slot: {pending.asked_slot}")
        ctx_lines.append(f"- missing_slots: {pending.missing_slots or [pending.asked_slot]}")
        ctx_lines.append(f"- asked_intent: {pending.asked_intent}")
        ctx_lines.append(f"- original_user_query: {pending.original_user_query or ''}")
        ctx_lines.append(f"- partial_constraints: {pending.partial_constraints or {}}")
    ctx = "\n".join(ctx_lines) or "无已知上下文。"
    current_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    user = HumanMessage(
        content=(
            f"current_date: {current_date}\n"
            f"timezone: America/New_York\n\n"
            f"已知上下文:\n{ctx}\n\n"
            f"用户当前消息:\n{state.current_user_message}"
        )
    )

    try:
        response = llm.invoke([sys, *state.messages[-6:], user])
    except Exception:
        return _deterministic_understand(state)
    try:
        result: IntentResult = intent_parser.parse(response.content)
    except Exception:
        # Soft fallback — if the LLM produced unparseable output, default to
        # unknown so the gate node can ask for more.
        return {"intent": "unknown", "constraints": {}, "persistable_field_updates": {}}

    detected = [
        DetectedArea(area_id=a.area_id, area_name=a.area_name, source=a.source)
        for a in result.detected_areas
    ]
    update: dict = {
        "intent": result.intent,
        "detected_areas": detected,
        "constraints": result.constraints,
        "persistable_field_updates": result.persistable_field_updates,
    }
    if state.pending_follow_up:
        pending = state.pending_follow_up
        answered = False
        slots = set(pending.missing_slots or [pending.asked_slot])
        original_intent = pending.asked_intent
        if result.intent in {"unknown", "out_of_scope", "chitchat"} and pending.asked_intent:
            update["intent"] = pending.asked_intent
        if slots.intersection({"target_area", "area_id", "area_name"}) and detected:
            answered = True
        if any(slot in result.constraints for slot in slots):
            answered = True
        if answered:
            update["pending_follow_up"] = None
        elif original_intent and result.intent not in {original_intent, "unknown", "out_of_scope", "chitchat"}:
            # User clearly started a new task instead of answering the pending
            # clarification. Keep conversation history, but cancel the dangling
            # follow-up pointer so future short messages are not misapplied.
            update["pending_follow_up"] = None
    # Promote detected area into target_area and keep id/name in sync.
    if detected:
        first = detected[0]
        if first.area_id:
            update["target_area_id"] = first.area_id
            update["target_area_name"] = first.area_name
        elif state.pending_follow_up and state.pending_follow_up.asked_slot in {"target_area", "area_id", "area_name"}:
            update["target_area_name"] = first.area_name
    update = _force_housing_intent_for_bedroom_query(state, update)
    update = _apply_budget_bedroom_semantics(state, update)
    update = _rag_resolve_transit(state, _rag_resolve_area(state, update))
    return _reconcile_target_area_fields(update)
