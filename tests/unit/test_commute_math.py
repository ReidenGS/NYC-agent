"""A10 — mcp-transit pure math: haversine + cache_key + to_jsonable."""
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timezone

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture(scope="module")
def commute():
    # app.commute -> app.realtime -> google.transit (gtfs-realtime-bindings).
    # We don't need GTFS parsing for math tests, so stub it.
    if "google.transit.gtfs_realtime_pb2" not in sys.modules:
        google = types.ModuleType("google")
        transit = types.ModuleType("google.transit")
        gtfs = types.ModuleType("google.transit.gtfs_realtime_pb2")
        gtfs.FeedMessage = type("FeedMessage", (), {})
        sys.modules["google"] = google
        sys.modules["google.transit"] = transit
        sys.modules["google.transit.gtfs_realtime_pb2"] = gtfs
    add_service_to_path("mcp-transit")
    return importlib.import_module("app.commute")


def test_haversine_known_distance(commute):
    # Astoria Blvd (40.7686, -73.9196) to Times Square (40.7580, -73.9855).
    miles = commute.haversine_miles(40.7686, -73.9196, 40.7580, -73.9855)
    # Known straight-line distance ~3.5 miles. Allow ±0.3 mi tolerance.
    assert 3.0 < miles < 4.0


def test_haversine_zero_for_same_point(commute):
    assert commute.haversine_miles(40.0, -73.0, 40.0, -73.0) == pytest.approx(0.0, abs=1e-6)


def test_cache_key_deterministic_and_namespaced(commute):
    a = commute.cache_key("astoria", "times sq", "subway", None)
    b = commute.cache_key("astoria", "times sq", "subway", None)
    assert a == b
    assert a.startswith("trip_") and len(a) == len("trip_") + 32


def test_cache_key_changes_with_inputs(commute):
    base = commute.cache_key("a", "b", "subway", None)
    # Any single field change should yield a different key.
    assert commute.cache_key("a", "b", "bus", None) != base
    assert commute.cache_key("a", "c", "subway", None) != base


def test_to_jsonable_serializes_datetime(commute):
    dt = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    out = commute.to_jsonable({"departure_time": dt, "route_id": "N", "delay_seconds": 0})
    assert out["departure_time"] == dt.isoformat()
    assert out["route_id"] == "N"
    assert out["delay_seconds"] == 0
