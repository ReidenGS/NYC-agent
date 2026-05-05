"""A5 — Shared profile schemas: weight normalization, mock_data alias resolution."""
from __future__ import annotations

import pytest

from tests.conftest import add_gateway_to_path


@pytest.fixture(autouse=True)
def _gateway_path():
    add_gateway_to_path()
    yield


# --- DecisionWeights.normalized() -------------------------------------------
def test_decision_weights_default_sums_to_one():
    from nyc_agent_shared.schemas import DecisionWeights
    w = DecisionWeights()
    assert sum(w.model_dump().values()) == pytest.approx(1.0, abs=1e-9)


def test_decision_weights_normalized_renormalizes():
    from nyc_agent_shared.schemas import DecisionWeights
    raw = DecisionWeights(safety=0.4, commute=0.3, rent=0.3, convenience=0.1, entertainment=0.1)
    # Pre-normalization sum is 1.2.
    normed = raw.normalized()
    total = sum(normed.model_dump().values())
    assert total == pytest.approx(1.0, abs=1e-3)
    # Relative ordering preserved.
    assert normed.safety > normed.rent
    assert normed.safety > normed.entertainment


def test_decision_weights_normalized_handles_all_zero():
    """If user wipes weights to 0, fall back to defaults instead of dividing by zero."""
    from nyc_agent_shared.schemas import DecisionWeights
    raw = DecisionWeights(safety=0, commute=0, rent=0, convenience=0, entertainment=0)
    normed = raw.normalized()
    assert sum(normed.model_dump().values()) == pytest.approx(1.0, abs=1e-9)


def test_decision_weights_normalized_clamps_negative():
    """Negative inputs are nonsense — clamp to 0 before normalization."""
    from nyc_agent_shared.schemas import DecisionWeights
    raw = DecisionWeights(safety=-0.5, commute=0.5, rent=0.5, convenience=0, entertainment=0)
    normed = raw.normalized()
    assert normed.safety == pytest.approx(0.0, abs=1e-3)
    assert normed.commute == pytest.approx(0.5, abs=1e-3)


# --- gateway mock_data alias resolution -------------------------------------
def test_find_area_id_resolves_chinese_aliases():
    from app.services.mock_data import find_area_id
    assert find_area_id("Astoria 安全吗") == "QN0101"
    assert find_area_id("阿斯托利亚怎么样") == "QN0101"
    assert find_area_id("绿点的租金") == "BK0102"
    assert find_area_id("曼哈顿中城贵不贵") == "MN0101"


def test_find_area_id_returns_none_for_unknown():
    from app.services.mock_data import find_area_id
    assert find_area_id("我想去布鲁克林") is None
    assert find_area_id(None) is None
    assert find_area_id("") is None


def test_get_area_falls_back_to_default_for_unknown_id():
    """get_area() must never raise — it's used as a default fallback in routes."""
    from app.services.mock_data import get_area, AREAS
    fallback = get_area("XX9999")
    assert fallback.area_id == AREAS["QN0101"].area_id
