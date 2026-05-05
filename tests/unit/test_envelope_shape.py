"""A1 — Gateway envelope models satisfy the API contract from
docs/NYC_Agent_API_Schema_Contract.md.

Every gateway response must be a top-level envelope with success / trace_id /
data / error keys. The error subobject must always have code/message/retryable.
"""
from __future__ import annotations

import pytest

from tests.conftest import add_gateway_to_path


@pytest.fixture(autouse=True)
def _gateway_path():
    add_gateway_to_path()
    yield


def test_success_envelope_serializes_with_data():
    from app.models.common import ApiEnvelope
    env = ApiEnvelope(success=True, trace_id="trace_abc", session_id="sess_x",
                       data={"hello": "world"}, error=None)
    payload = env.model_dump()
    assert payload["success"] is True
    assert payload["trace_id"] == "trace_abc"
    assert payload["data"] == {"hello": "world"}
    assert payload["error"] is None


def test_error_envelope_carries_required_fields():
    from app.models.common import ApiEnvelope, ApiError
    err = ApiError(code="VALIDATION_ERROR", message="missing field", retryable=False)
    env = ApiEnvelope(success=False, trace_id="trace_err", data=None, error=err)
    dumped = env.model_dump()
    assert dumped["error"]["code"] == "VALIDATION_ERROR"
    assert dumped["error"]["retryable"] is False
    assert dumped["error"]["details"] == {}  # default factory must produce dict


def test_metric_card_default_card_type():
    from app.models.common import MetricCard, MetricItem
    card = MetricCard(title="安全", metrics=[MetricItem(label="犯罪", value=10)])
    assert card.card_type == "metric"
    assert card.data_quality == "reference"


def test_weather_card_data_default_card_type():
    from app.models.common import WeatherCardData, WeatherPeriod, SourceItem
    card = WeatherCardData(
        title="今晚",
        periods=[WeatherPeriod(start_time="t1", end_time="t2", temperature=60,
                               temperature_unit="F", wind_speed="5 mph",
                               wind_direction="N", short_forecast="Clear",
                               is_daytime=True)],
        data_quality="realtime",
        source=[SourceItem(name="NWS")],
    )
    assert card.card_type == "weather"


def test_envelope_generic_payload_validation_error():
    """Pydantic must reject malformed error blocks with missing required keys."""
    from app.models.common import ApiError
    with pytest.raises(Exception):
        ApiError(code="X")  # missing message + retryable
