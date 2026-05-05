"""A2 — mock_data fallback functions are the gateway's last-resort response
when real services are unavailable AND ALLOW_MOCK_FALLBACK=true. Their shape
must match production models so the frontend doesn't crash on fallback.
"""
from __future__ import annotations

import pytest

from tests.conftest import add_gateway_to_path


@pytest.fixture()
def mock_data():
    add_gateway_to_path()
    from app.services import mock_data
    return mock_data


def test_all_seed_areas_have_metrics(mock_data):
    """Every area in AREAS must have a corresponding entry in METRICS or the
    fallback path will crash building metric_cards."""
    for area_id in mock_data.AREAS:
        assert area_id in mock_data.METRICS, f"missing METRICS for {area_id}"


def test_area_metrics_returns_five_metric_cards(mock_data):
    response = mock_data.area_metrics("QN0101")
    assert response.area.area_id == "QN0101"
    assert len(response.metric_cards) == 5
    titles = {card.title for card in response.metric_cards}
    # BL §4 — must cover safety / commute / rent / convenience / entertainment.
    assert {"安全", "通勤", "租金", "便利", "娱乐"} == titles


def test_map_layers_returns_two_layers_with_geojson(mock_data):
    response = mock_data.map_layers("QN0101")
    assert response.area_id == "QN0101"
    assert len(response.layers) == 2
    types = {layer.layer_type for layer in response.layers}
    assert types == {"choropleth", "marker"}
    for layer in response.layers:
        assert layer.geojson.type == "FeatureCollection"
        assert len(layer.geojson.features) >= 1


def test_weather_returns_requested_hours(mock_data):
    response = mock_data.weather("QN0101", hours=4)
    assert len(response.weather.periods) == 4
    sample = response.weather.periods[0]
    assert sample.temperature_unit == "F"
    assert sample.wind_speed
    assert sample.short_forecast


def test_weather_caps_to_12_hours(mock_data):
    response = mock_data.weather("QN0101", hours=24)
    assert len(response.weather.periods) == 12  # internal cap


def test_transit_subway_vs_bus_routing(mock_data):
    subway = mock_data.transit("Astoria Blvd", "Times Sq", "subway")
    bus = mock_data.transit("Astoria Blvd", "Times Sq", "bus")
    assert subway.mode == "subway"
    assert bus.mode == "bus"
    # Bus is slower than subway in the demo seed.
    assert bus.in_vehicle_minutes >= subway.in_vehicle_minutes
    assert subway.total_minutes == subway.walking_to_stop_minutes + subway.waiting_minutes + subway.in_vehicle_minutes


def test_transit_unknown_mode_falls_back_to_subway(mock_data):
    response = mock_data.transit("A", "B", "either")
    assert response.mode == "subway"


def test_now_iso_uses_ny_timezone(mock_data):
    iso = mock_data.now_iso()
    # NY is UTC-4 (EDT, Mar–Nov) or UTC-5 (EST, Nov–Mar). Either is correct
    # depending on the calendar date.
    assert iso.endswith(("-04:00", "-05:00"))
