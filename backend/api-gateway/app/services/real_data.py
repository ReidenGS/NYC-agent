from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.models.area import AreaMetrics, AreaMetricsResponse, AreaSummary
from app.models.common import MetricCard, MetricItem, SourceItem, WeatherPeriod
from app.models.transit import TransitDeparture, TransitRealtimeResponse
from app.models.weather import WeatherPayload, WeatherResponse


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _build_metric_cards(metrics: AreaMetrics, source_snapshot: dict[str, Any], updated_at: str) -> list[MetricCard]:
    def _src(name: str, type_: str) -> list[SourceItem]:
        return [SourceItem(name=name, type=type_, updated_at=updated_at)]
    rent_label = f'${metrics.rent_index_value:,.0f} median' if metrics.rent_index_value else 'n/a'
    cards = [
        MetricCard(title='安全', subtitle='近 30 天公开犯罪记录', score_label=str(metrics.crime_count_30d),
                   metrics=[MetricItem(label='犯罪记录数', value=metrics.crime_count_30d, unit='起'),
                            MetricItem(label='犯罪强度指数', value=float(metrics.crime_index_100 or 0), unit='/100')],
                   data_quality='reference', source=_src('NYPD Complaint Data', 'nyc_open_data')),
        MetricCard(title='租金', subtitle='区域租金参考', score_label=rent_label,
                   metrics=[MetricItem(label='参考租金', value=float(metrics.rent_index_value or 0), unit='USD/月')],
                   data_quality='benchmark', source=_src('RentCast / ZORI cache', 'rental_data')),
        MetricCard(title='通勤', subtitle='站点覆盖', score_label=str(metrics.transit_station_count),
                   metrics=[MetricItem(label='站点数', value=metrics.transit_station_count, unit='个')],
                   data_quality='reference', source=_src('MTA GTFS static', 'transit_static')),
        MetricCard(title='便利', subtitle='生活设施', score_label=str(metrics.convenience_facility_count),
                   metrics=[MetricItem(label='便利设施', value=metrics.convenience_facility_count, unit='个')],
                   data_quality='reference', source=_src('NYC Facilities / OSM', 'poi_data')),
        MetricCard(title='娱乐', subtitle='酒吧/餐厅/影院等', score_label=str(metrics.entertainment_poi_count),
                   metrics=[MetricItem(label='娱乐 POI', value=metrics.entertainment_poi_count, unit='个')],
                   data_quality='reference', source=_src('OpenStreetMap Overpass', 'poi_data')),
    ]
    return cards


def fetch_area_metrics(area_id: str) -> AreaMetricsResponse:
    """Call data-sync-service for the latest metrics snapshot of an NTA."""
    url = f"{settings.data_sync_base_url.rstrip('/')}/areas/{area_id}/metrics"
    with httpx.Client(timeout=settings.agent_request_timeout_seconds) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    area = AreaSummary(
        area_id=payload['area_id'],
        area_name=payload.get('area_name') or payload['area_id'],
        borough=payload.get('borough') or 'NYC',
        latitude=payload.get('latitude'),
        longitude=payload.get('longitude'),
    )
    metrics = AreaMetrics(
        crime_count_30d=int(payload.get('crime_count_30d') or 0),
        crime_index_100=float(payload.get('crime_index_100') or 0),
        entertainment_poi_count=int(payload.get('entertainment_poi_count') or 0),
        convenience_facility_count=int(payload.get('convenience_facility_count') or 0),
        transit_station_count=int(payload.get('transit_station_count') or 0),
        complaint_noise_30d=int(payload.get('complaint_noise_30d') or 0),
        rent_index_value=float(payload.get('rent_index_value') or 0),
    )
    updated_at = payload.get('updated_at') or _now_iso()
    snapshot = payload.get('source_snapshot') or {}
    return AreaMetricsResponse(
        area=area,
        metrics=metrics,
        metric_cards=_build_metric_cards(metrics, snapshot, updated_at),
        source_snapshot={'mode': 'v_area_metrics_latest', 'metric_date': payload.get('metric_date'), **snapshot},
        updated_at=updated_at,
    )


def _coerce_precip(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get('value')
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def fetch_area_weather(area_id: str, hours: int) -> WeatherResponse:
    """Call mcp-weather get_hourly_forecast for the requested area."""
    url = f"{settings.mcp_weather_url.rstrip('/')}/tools/get_hourly_forecast"
    body = {'arguments': {'area_id': area_id, 'hours': hours}}
    with httpx.Client(timeout=settings.agent_request_timeout_seconds) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
    if payload.get('status') not in {'success', 'no_data'}:
        error = payload.get('error') or {}
        raise RuntimeError(f"mcp-weather error: {error.get('code') or payload.get('status')}")
    data = payload.get('data') or {}
    periods_raw = data.get('periods') or []
    periods = [
        WeatherPeriod(
            start_time=p.get('startTime') or p.get('start_time') or '',
            end_time=p.get('endTime') or p.get('end_time') or '',
            temperature=p.get('temperature') or 0,
            temperature_unit=p.get('temperatureUnit') or p.get('temperature_unit') or 'F',
            precipitation_probability=_coerce_precip(p.get('probabilityOfPrecipitation') or p.get('precipitation_probability')),
            wind_speed=p.get('windSpeed') or p.get('wind_speed') or '',
            wind_direction=p.get('windDirection') or p.get('wind_direction') or '',
            short_forecast=p.get('shortForecast') or p.get('short_forecast') or '',
            detailed_forecast=p.get('detailedForecast') or p.get('detailed_forecast'),
            is_daytime=bool(p.get('isDaytime') if 'isDaytime' in p else p.get('is_daytime', True)),
        )
        for p in periods_raw
    ]
    area = AreaSummary(
        area_id=area_id,
        area_name=data.get('area_name') or area_id,
        borough='NYC',
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
    )
    timestamp = payload.get('timestamp') or _now_iso()
    return WeatherResponse(
        area=area,
        weather=WeatherPayload(mode='hourly_summary', target_time=None, periods=periods),
        data_quality='realtime' if periods else 'no_data',
        source=[SourceItem(name='National Weather Service API', type='weather_api',
                            url='https://api.weather.gov', updated_at=timestamp)],
        updated_at=timestamp,
        expires_at=None,
    )


def fetch_transit_realtime(session_id: str, origin: str, destination: str, mode: str) -> TransitRealtimeResponse:
    """Call mcp-transit get_realtime_commute. Mode 'either' is mapped to 'subway'."""
    selected_mode = mode if mode in {'subway', 'bus'} else 'subway'
    url = f"{settings.mcp_transit_url.rstrip('/')}/tools/get_realtime_commute"
    body = {'session_id': session_id, 'arguments': {'origin': origin, 'destination': destination, 'mode': selected_mode}}
    with httpx.Client(timeout=settings.agent_request_timeout_seconds) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
    status = payload.get('status')
    if status not in {'success', 'no_data'}:
        error = payload.get('error') or {}
        raise RuntimeError(f"mcp-transit error: {error.get('code') or status}")
    data = payload.get('data') or {}
    if status == 'no_data' or not data:
        return TransitRealtimeResponse(
            mode='bus' if selected_mode == 'bus' else 'subway',
            origin_stop=origin, destination=destination,
            walking_to_stop_minutes=0, waiting_minutes=0, in_vehicle_minutes=0, total_minutes=0,
            recommended_leave_at=_now_iso(), estimated_arrival_at=_now_iso(),
            realtime_used=False, fallback_used=True, departures=[],
            data_quality='no_data',
            source=[SourceItem(name='MTA GTFS Realtime + static fallback', type='transit_realtime',
                                updated_at=payload.get('timestamp') or _now_iso())],
        )
    snapshot = data.get('source_snapshot') or {}
    origin_stop_meta = snapshot.get('origin_stop') or {}
    departures_raw = data.get('next_departures') or []
    departures: list[TransitDeparture] = []
    now_utc = datetime.now(timezone.utc)
    for row in departures_raw[:5]:
        dep_time = row.get('departure_time') or row.get('arrival_time')
        minutes_until = 0
        if dep_time:
            try:
                dt = datetime.fromisoformat(str(dep_time).replace('Z', '+00:00'))
                minutes_until = max(0, int((dt - now_utc).total_seconds() // 60))
            except ValueError:
                minutes_until = 0
        departures.append(TransitDeparture(
            route_id=row.get('route_id') or '',
            stop_name=origin_stop_meta.get('stop_name') or row.get('stop_id') or '',
            departure_time=str(dep_time) if dep_time else '',
            minutes_until_departure=minutes_until,
            delay_seconds=row.get('delay_seconds'),
        ))
    realtime_used = bool(data.get('realtime_used'))
    return TransitRealtimeResponse(
        mode='bus' if data.get('mode') == 'bus' else 'subway',
        origin_stop=origin_stop_meta.get('stop_name') or origin,
        destination=destination,
        walking_to_stop_minutes=int(data.get('walking_to_stop_minutes') or 0),
        waiting_minutes=int(data.get('waiting_minutes') or 0),
        in_vehicle_minutes=int(data.get('in_vehicle_minutes') or 0),
        total_minutes=int(data.get('total_minutes') or 0),
        recommended_leave_at=str(data.get('recommended_leave_at') or _now_iso()),
        estimated_arrival_at=str(data.get('estimated_arrival_at') or _now_iso()),
        realtime_used=realtime_used,
        fallback_used=not realtime_used,
        departures=departures,
        data_quality='realtime' if realtime_used else 'cached',
        source=[SourceItem(name='MTA GTFS Realtime + static fallback', type='transit_realtime',
                            updated_at=payload.get('timestamp') or _now_iso())],
    )
