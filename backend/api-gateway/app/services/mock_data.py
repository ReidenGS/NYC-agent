from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.area import AreaMetrics, AreaMetricsResponse, AreaSummary, GeoJsonFeature, GeoJsonFeatureCollection, GeoJsonGeometry, MapLayer, MapLayersResponse
from app.models.common import MetricCard, MetricItem, SourceItem, WeatherPeriod
from app.models.transit import TransitDeparture, TransitRealtimeResponse
from app.models.weather import WeatherPayload, WeatherResponse

NY_TZ = timezone(timedelta(hours=-4))

AREAS: dict[str, AreaSummary] = {
    'QN0101': AreaSummary(area_id='QN0101', area_name='Astoria', borough='Queens', latitude=40.7686, longitude=-73.9196),
    'QN0102': AreaSummary(area_id='QN0102', area_name='Long Island City', borough='Queens', latitude=40.7447, longitude=-73.9485),
    'BK0101': AreaSummary(area_id='BK0101', area_name='Williamsburg', borough='Brooklyn', latitude=40.7081, longitude=-73.9571),
    'BK0102': AreaSummary(area_id='BK0102', area_name='Greenpoint', borough='Brooklyn', latitude=40.7308, longitude=-73.9542),
    'MN0101': AreaSummary(area_id='MN0101', area_name='Midtown', borough='Manhattan', latitude=40.7549, longitude=-73.9840),
}

ALIASES: dict[str, str] = {
    'astoria': 'QN0101', '阿斯托利亚': 'QN0101',
    'lic': 'QN0102', 'long island city': 'QN0102', '长岛市': 'QN0102',
    'williamsburg': 'BK0101', '威廉斯堡': 'BK0101',
    'greenpoint': 'BK0102', '绿点': 'BK0102',
    'midtown': 'MN0101', '曼哈顿中城': 'MN0101',
}

METRICS: dict[str, AreaMetrics] = {
    'QN0101': AreaMetrics(crime_count_30d=42, crime_index_100=63.5, entertainment_poi_count=86, convenience_facility_count=54, transit_station_count=7, complaint_noise_30d=19, rent_index_value=2850),
    'QN0102': AreaMetrics(crime_count_30d=37, crime_index_100=58.0, entertainment_poi_count=112, convenience_facility_count=48, transit_station_count=9, complaint_noise_30d=25, rent_index_value=3600),
    'BK0101': AreaMetrics(crime_count_30d=51, crime_index_100=68.2, entertainment_poi_count=148, convenience_facility_count=61, transit_station_count=8, complaint_noise_30d=34, rent_index_value=3900),
    'BK0102': AreaMetrics(crime_count_30d=29, crime_index_100=49.5, entertainment_poi_count=74, convenience_facility_count=46, transit_station_count=5, complaint_noise_30d=16, rent_index_value=3400),
    'MN0101': AreaMetrics(crime_count_30d=83, crime_index_100=76.0, entertainment_poi_count=210, convenience_facility_count=95, transit_station_count=18, complaint_noise_30d=44, rent_index_value=4300),
}


def now_iso() -> str:
    return datetime.now(NY_TZ).replace(microsecond=0).isoformat()


def future_iso(minutes: int) -> str:
    return (datetime.now(NY_TZ) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def find_area_id(text: str | None) -> str | None:
    if not text:
        return None
    lower = text.lower()
    for alias, area_id in ALIASES.items():
        if alias in lower or alias in text:
            return area_id
    for area_id, area in AREAS.items():
        if area.area_id.lower() in lower or area.area_name.lower() in lower:
            return area_id
    return None


def get_area(area_id: str) -> AreaSummary:
    return AREAS.get(area_id, AREAS['QN0101'])


def build_metric_cards(area_id: str) -> list[MetricCard]:
    metrics = METRICS.get(area_id, METRICS['QN0101'])
    updated_at = now_iso()
    return [
        MetricCard(title='安全', subtitle='近 30 天公开犯罪记录', score_label='中等', metrics=[MetricItem(label='犯罪记录数', value=metrics.crime_count_30d, unit='起')], data_quality='reference', source=[SourceItem(name='NYPD Complaint Data', type='nyc_open_data', updated_at=updated_at)]),
        MetricCard(title='租金', subtitle='区域租金参考', score_label=f'${metrics.rent_index_value:,.0f} median', metrics=[MetricItem(label='参考租金', value=metrics.rent_index_value, unit='USD/月')], data_quality='benchmark', source=[SourceItem(name='RentCast / ZORI cache', type='rental_data', updated_at=updated_at)]),
        MetricCard(title='通勤', subtitle='站点覆盖', score_label='较好', metrics=[MetricItem(label='站点数', value=metrics.transit_station_count, unit='个')], data_quality='reference', source=[SourceItem(name='MTA GTFS static', type='transit_static', updated_at=updated_at)]),
        MetricCard(title='便利', subtitle='生活设施', score_label=str(metrics.convenience_facility_count), metrics=[MetricItem(label='便利设施', value=metrics.convenience_facility_count, unit='个')], data_quality='reference', source=[SourceItem(name='NYC Facilities / OSM', type='poi_data', updated_at=updated_at)]),
        MetricCard(title='娱乐', subtitle='酒吧/餐厅/影院等', score_label=str(metrics.entertainment_poi_count), metrics=[MetricItem(label='娱乐 POI', value=metrics.entertainment_poi_count, unit='个')], data_quality='reference', source=[SourceItem(name='OpenStreetMap Overpass', type='poi_data', updated_at=updated_at)]),
    ]


def area_metrics(area_id: str) -> AreaMetricsResponse:
    updated_at = now_iso()
    return AreaMetricsResponse(
        area=get_area(area_id),
        metrics=METRICS.get(area_id, METRICS['QN0101']),
        metric_cards=build_metric_cards(area_id),
        source_snapshot={'mode': 'mock_until_mcp_available', 'updated_at': updated_at},
        updated_at=updated_at,
    )


def map_layers(area_id: str) -> MapLayersResponse:
    area = get_area(area_id)
    metrics = METRICS.get(area_id, METRICS['QN0101'])
    lat = area.latitude or 40.76
    lon = area.longitude or -73.92
    updated_at = now_iso()
    polygon = [[
        [lon - 0.018, lat - 0.014], [lon + 0.018, lat - 0.014],
        [lon + 0.018, lat + 0.014], [lon - 0.018, lat + 0.014],
        [lon - 0.018, lat - 0.014],
    ]]
    return MapLayersResponse(area_id=area.area_id, layers=[
        MapLayer(
            layer_id=f'map_{area.area_id}_safety', layer_type='choropleth', metric_name='crime_index',
            geojson=GeoJsonFeatureCollection(features=[GeoJsonFeature(geometry=GeoJsonGeometry(type='Polygon', coordinates=polygon), properties={'area_id': area.area_id, 'area_name': area.area_name, 'crime_index_100': metrics.crime_index_100})]),
            style_hint={'color_scale': 'red', 'value_field': 'crime_index_100'}, data_quality='cached', updated_at=updated_at,
        ),
        MapLayer(
            layer_id=f'map_{area.area_id}_poi', layer_type='marker', metric_name='entertainment',
            geojson=GeoJsonFeatureCollection(features=[
                GeoJsonFeature(geometry=GeoJsonGeometry(type='Point', coordinates=[lon, lat]), properties={'name': f'{area.area_name} Entertainment Cluster', 'category': 'restaurant', 'count': metrics.entertainment_poi_count}),
                GeoJsonFeature(geometry=GeoJsonGeometry(type='Point', coordinates=[lon - 0.006, lat - 0.004]), properties={'name': f'{area.area_name} Convenience Cluster', 'category': 'supermarket', 'count': metrics.convenience_facility_count}),
            ]),
            style_hint={'color': 'blue'}, data_quality='cached', updated_at=updated_at,
        ),
    ])


def weather(area_id: str, hours: int = 6) -> WeatherResponse:
    area = get_area(area_id)
    base = datetime.now(NY_TZ).replace(minute=0, second=0, microsecond=0)
    periods: list[WeatherPeriod] = []
    for i in range(max(1, min(hours, 12))):
        start = base + timedelta(hours=i + 1)
        end = start + timedelta(hours=1)
        periods.append(WeatherPeriod(
            start_time=start.isoformat(), end_time=end.isoformat(), temperature=62 + min(i, 4),
            temperature_unit='F', precipitation_probability=max(5, 20 - i * 2), wind_speed='7 mph',
            wind_direction='NW', short_forecast='Mostly Sunny' if i < 3 else 'Partly Cloudy',
            detailed_forecast='NWS realtime integration is pending; this is a cached demo shape.', is_daytime=True,
        ))
    updated_at = now_iso()
    return WeatherResponse(
        area=area, weather=WeatherPayload(mode='hourly_summary', target_time=None, periods=periods),
        data_quality='cached', source=[SourceItem(name='National Weather Service API', type='weather_api', url='https://api.weather.gov', updated_at=updated_at)],
        updated_at=updated_at, expires_at=future_iso(30),
    )


def transit(origin: str, destination: str, mode: str) -> TransitRealtimeResponse:
    selected_mode = 'bus' if mode == 'bus' else 'subway'
    route = 'Q69' if selected_mode == 'bus' else 'N'
    stop = '31 St / Broadway' if selected_mode == 'bus' else 'Astoria Blvd'
    departures = [
        TransitDeparture(route_id=route, stop_name=stop, departure_time=future_iso(4), minutes_until_departure=4, delay_seconds=0),
        TransitDeparture(route_id='W' if selected_mode == 'subway' else 'Q100', stop_name=stop, departure_time=future_iso(11), minutes_until_departure=11, delay_seconds=30),
    ]
    walking = 7
    waiting = departures[0].minutes_until_departure
    in_vehicle = 28 if selected_mode == 'subway' else 36
    total = walking + waiting + in_vehicle
    return TransitRealtimeResponse(
        mode=selected_mode, origin_stop=stop, destination=destination,
        walking_to_stop_minutes=walking, waiting_minutes=waiting, in_vehicle_minutes=in_vehicle,
        total_minutes=total, recommended_leave_at=future_iso(0), estimated_arrival_at=future_iso(total),
        realtime_used=False, fallback_used=True, departures=departures, data_quality='cached',
        source=[SourceItem(name='MTA GTFS Realtime pending; static fallback', type='transit_realtime', updated_at=now_iso())],
    )
