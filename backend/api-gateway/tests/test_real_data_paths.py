"""Integration tests for the real-data paths in the gateway routes.

We monkeypatch the helpers in app.services.real_data so the tests do not
require running data-sync-service / mcp-weather / mcp-transit. The point is
to verify that the route wiring (envelope shape, session check, status codes)
is correct when the real services succeed and when they fail.
"""
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.area import AreaMetrics, AreaMetricsResponse, AreaSummary
from app.models.common import SourceItem, WeatherPeriod
from app.models.transit import TransitDeparture, TransitRealtimeResponse
from app.models.weather import WeatherPayload, WeatherResponse
from app.services import real_data

settings.use_remote_orchestrator = False
settings.allow_mock_fallback = False

client = TestClient(app)


def _create_session() -> str:
    response = client.post('/sessions', json={'client_timezone': 'America/New_York'})
    assert response.status_code == 200
    return response.json()['data']['session_id']


def _stub_metrics(area_id: str) -> AreaMetricsResponse:
    area = AreaSummary(area_id=area_id, area_name='Astoria', borough='Queens', latitude=40.76, longitude=-73.92)
    metrics = AreaMetrics(crime_count_30d=10, crime_index_100=42.5, entertainment_poi_count=80,
                          convenience_facility_count=40, transit_station_count=6,
                          complaint_noise_30d=5, rent_index_value=2800)
    return AreaMetricsResponse(area=area, metrics=metrics, metric_cards=[],
                               source_snapshot={'mode': 'stub'}, updated_at='2026-04-26T00:00:00+00:00')


def _stub_weather(area_id: str, hours: int) -> WeatherResponse:
    period = WeatherPeriod(start_time='2026-04-26T01:00:00+00:00', end_time='2026-04-26T02:00:00+00:00',
                           temperature=60, temperature_unit='F', precipitation_probability=10,
                           wind_speed='5 mph', wind_direction='NW', short_forecast='Clear',
                           detailed_forecast=None, is_daytime=True)
    return WeatherResponse(
        area=AreaSummary(area_id=area_id, area_name='Astoria', borough='Queens', latitude=40.76, longitude=-73.92),
        weather=WeatherPayload(mode='hourly_summary', target_time=None, periods=[period] * hours),
        data_quality='realtime',
        source=[SourceItem(name='NWS', type='weather_api')],
        updated_at='2026-04-26T00:00:00+00:00',
    )


def _stub_transit(session_id: str, origin: str, destination: str, mode: str) -> TransitRealtimeResponse:
    return TransitRealtimeResponse(
        mode='subway' if mode != 'bus' else 'bus',
        origin_stop='Astoria Blvd', destination=destination,
        walking_to_stop_minutes=4, waiting_minutes=3, in_vehicle_minutes=22, total_minutes=29,
        recommended_leave_at='2026-04-26T00:00:00+00:00',
        estimated_arrival_at='2026-04-26T00:29:00+00:00',
        realtime_used=True, fallback_used=False,
        departures=[TransitDeparture(route_id='N', stop_name='Astoria Blvd',
                                     departure_time='2026-04-26T00:03:00+00:00',
                                     minutes_until_departure=3, delay_seconds=0)],
        data_quality='realtime',
        source=[SourceItem(name='MTA GTFS Realtime', type='transit_realtime')],
    )


def test_real_metrics_path(monkeypatch):
    monkeypatch.setattr(real_data, 'fetch_area_metrics', _stub_metrics)
    session_id = _create_session()
    response = client.get(f'/areas/QN0101/metrics?session_id={session_id}')
    assert response.status_code == 200
    body = response.json()
    assert body['success'] is True
    assert body['data']['area']['area_name'] == 'Astoria'
    assert body['data']['metrics']['crime_count_30d'] == 10
    assert body['data']['source_snapshot']['mode'] == 'stub'


def test_real_weather_path(monkeypatch):
    monkeypatch.setattr(real_data, 'fetch_area_weather', _stub_weather)
    session_id = _create_session()
    response = client.get(f'/areas/QN0101/weather?session_id={session_id}&hours=3')
    assert response.status_code == 200
    body = response.json()
    assert body['success'] is True
    assert len(body['data']['weather']['periods']) == 3
    assert body['data']['data_quality'] == 'realtime'


def test_real_transit_path(monkeypatch):
    monkeypatch.setattr(real_data, 'fetch_transit_realtime', _stub_transit)
    session_id = _create_session()
    payload = {'session_id': session_id, 'origin': 'Astoria Blvd', 'destination': 'Times Sq', 'mode': 'subway'}
    response = client.post('/transit/realtime', json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body['success'] is True
    assert body['data']['realtime_used'] is True
    assert body['data']['departures'][0]['route_id'] == 'N'


def test_real_metrics_failure_propagates_503(monkeypatch):
    def _boom(area_id: str):
        raise RuntimeError('data-sync down')
    monkeypatch.setattr(real_data, 'fetch_area_metrics', _boom)
    monkeypatch.setattr(settings, 'allow_mock_fallback', False)
    session_id = _create_session()
    response = client.get(f'/areas/QN0101/metrics?session_id={session_id}')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'DATA_SYNC_UNAVAILABLE'
