from __future__ import annotations

from app.models.chat import ChatDebug, ChatRequest, ChatResponseData, TraceSummaryItem
from app.models.common import DisplayRefs, SourceItem, WeatherCardData
from app.stores.session_store import SessionStore
from app.services import mock_data


class OrchestratorService:
    """MVP orchestrator facade.

    This intentionally mirrors the future service boundary: API Gateway calls
    one orchestrator object, which decides whether to ask follow-up or delegate
    to mock domain services. Later this class becomes an HTTP/A2A client.
    """

    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def handle_chat(self, request: ChatRequest) -> ChatResponseData:
        profile = self.store.require(request.session_id)
        message = request.message.strip()
        lower = message.lower()
        detected_area_id = mock_data.find_area_id(message)
        if detected_area_id:
            profile = self.store.update_area(request.session_id, detected_area_id)

        if self._needs_area(message) and not profile.target_area_id:
            profile.missing_required_fields = ['target_area']
            return ChatResponseData(
                message_type='follow_up',
                answer='你想了解纽约哪个区域？例如 Astoria、Long Island City、Williamsburg。',
                next_action='ask_follow_up',
                profile_snapshot=profile,
                missing_slots=['target_area'],
                data_quality='unknown',
                debug=self._debug(request.debug, [('orchestrator.missing_slot', 'orchestrator-agent', 'success', 34, None)]),
            )

        area_id = profile.target_area_id or 'QN0101'
        is_weather = any(token in lower for token in ['weather', 'rain', 'temperature']) or any(token in message for token in ['天气', '下雨', '温度'])
        is_transit = any(token in lower for token in ['subway', 'bus', 'commute', 'departure']) or any(token in message for token in ['地铁', '公交', '通勤', '下一班'])
        is_entertainment = any(token in message for token in ['娱乐', '酒吧', '餐厅', '影院']) or 'entertainment' in lower
        is_convenience = any(token in message for token in ['便利', '超市', '公园', '学校', '图书馆']) or 'convenience' in lower
        is_crime = any(token in message for token in ['犯罪', '安全', '偷窃', '抢劫']) or any(token in lower for token in ['crime', 'safe', 'safety', 'robbery', 'theft'])

        if is_weather:
            weather = mock_data.weather(area_id)
            return ChatResponseData(
                message_type='answer', answer=f'{weather.area.area_name} 未来几小时以晴到多云为主，降水概率较低。天气数据当前使用 NWS 契约形状和短缓存占位，后续会接 mcp-weather。',
                next_action='respond_final', profile_snapshot=profile,
                cards=[WeatherCardData(title=f'{weather.area.area_name} 天气', subtitle='未来 6 小时', periods=weather.weather.periods, data_quality=weather.data_quality, source=weather.source)],
                display_refs=DisplayRefs(), sources=weather.source, data_quality=weather.data_quality,
                debug=self._debug(request.debug, [('orchestrator.intent_detected', 'orchestrator-agent', 'success', 80, None), ('weather.current_query', 'weather-agent', 'success', 140, 'mcp-weather')]),
            )

        if is_transit:
            transit = mock_data.transit(profile.target_area.area_name if profile.target_area else 'Astoria', profile.target_destination or 'NYU', 'subway')
            return ChatResponseData(
                message_type='answer', answer=f'从 {profile.target_area.area_name if profile.target_area else "当前区域"} 出发，建议预留约 {transit.total_minutes} 分钟。下一班 {transit.departures[0].route_id} 约 {transit.departures[0].minutes_until_departure} 分钟后出发。当前是静态/缓存占位，实时 MTA 会由 mcp-transit 接入。',
                next_action='respond_final', profile_snapshot=profile, cards=[], display_refs=DisplayRefs(),
                sources=transit.source, data_quality=transit.data_quality,
                debug=self._debug(request.debug, [('orchestrator.intent_detected', 'orchestrator-agent', 'success', 70, None), ('transit.realtime_commute', 'transit-agent', 'success', 180, 'mcp-transit')]),
            )

        metrics = mock_data.area_metrics(area_id)
        if is_crime:
            answer = f'{metrics.area.area_name} 近 30 天犯罪记录占位值为 {metrics.metrics.crime_count_30d} 起，犯罪指数 {metrics.metrics.crime_index_100}/100。后续接入 mcp-safety 后会按 NYPD 明细支持偷窃、抢劫等类型细查。'
        elif is_entertainment:
            answer = f'{metrics.area.area_name} 娱乐设施占位总量为 {metrics.metrics.entertainment_poi_count} 个，可继续细分酒吧、餐厅、影院等类别。'
        elif is_convenience:
            answer = f'{metrics.area.area_name} 便利设施占位总量为 {metrics.metrics.convenience_facility_count} 个，可继续细分超市、公园、学校、图书馆等类别。'
        else:
            answer = f'{metrics.area.area_name} 当前可作为候选区域：租金参考约 ${metrics.metrics.rent_index_value:,.0f}/月，通勤站点 {metrics.metrics.transit_station_count} 个，安全指标中等。你可以继续问犯罪类型、娱乐分类、便利设施或实时通勤。'

        return ChatResponseData(
            message_type='answer', answer=answer, next_action='respond_final', profile_snapshot=profile,
            cards=metrics.metric_cards, display_refs=DisplayRefs(map_layer_ids=[f'map_{metrics.area.area_id}_safety', f'map_{metrics.area.area_id}_poi']),
            sources=[SourceItem(name='MVP mock domain service; replace with A2A/MCP', type='system', updated_at=mock_data.now_iso())],
            data_quality='reference',
            debug=self._debug(request.debug, [('orchestrator.intent_detected', 'orchestrator-agent', 'success', 92, None), ('neighborhood.metrics_query', 'neighborhood-agent', 'success', 210, 'mcp-safety')]),
        )

    def _needs_area(self, message: str) -> bool:
        return any(token in message for token in ['附近', '这个区', '该地区', '区域']) or any(token in message.lower() for token in ['area', 'neighborhood', 'nearby'])

    def _debug(self, enabled: bool, rows: list[tuple[str, str, str, int, str | None]]) -> ChatDebug | None:
        if not enabled:
            return None
        return ChatDebug(trace_summary=[TraceSummaryItem(step=s, service=svc, status=st, latency_ms=lat, mcp=mcp) for s, svc, st, lat, mcp in rows])
