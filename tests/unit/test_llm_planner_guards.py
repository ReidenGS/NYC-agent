"""A6 + H1–H3 — LLM SQL planner guardrails.

Covers:
- validate_plan() rejects SELECT *, missing LIMIT, wrong status, malformed shape
- build_plan() falls back to deterministic when OPENAI_API_KEY missing
- Prompt files on disk have no TODO/FIXME/<placeholder>
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from tests.conftest import add_service_to_path

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def housing():
    add_service_to_path("housing-agent")
    return importlib.import_module("app.llm_planner")


@pytest.fixture()
def neighborhood():
    add_service_to_path("neighborhood-agent")
    return importlib.import_module("app.llm_planner")


# --- A6 / H1 — validate_plan rejection rules ---------------------------------
def test_validate_plan_rejects_select_star(housing):
    plan = {
        "status": "sql_ready",
        "queries": [{"purpose": "analysis", "sql": "SELECT * FROM app_area_metrics_daily LIMIT 1", "params": {}}],
    }
    with pytest.raises(ValueError, match="SELECT \\*"):
        housing.validate_plan(plan)


def test_validate_plan_rejects_missing_limit(housing):
    plan = {
        "status": "sql_ready",
        "queries": [{"purpose": "analysis", "sql": "SELECT area_id FROM app_area_metrics_daily", "params": {}}],
    }
    with pytest.raises(ValueError, match="LIMIT"):
        housing.validate_plan(plan)


def test_validate_plan_rejects_unknown_status(housing):
    with pytest.raises(ValueError, match="status"):
        housing.validate_plan({"status": "totally_made_up"})


def test_validate_plan_rejects_zero_or_too_many_queries(housing):
    with pytest.raises(ValueError, match="1-3"):
        housing.validate_plan({"status": "sql_ready", "queries": []})
    too_many = [
        {"purpose": "analysis", "sql": "SELECT 1 FROM app_area_metrics_daily LIMIT 1", "params": {}}
    ] * 4
    with pytest.raises(ValueError, match="1-3"):
        housing.validate_plan({"status": "sql_ready", "queries": too_many})


def test_validate_plan_rejects_invalid_purpose(housing):
    plan = {
        "status": "sql_ready",
        "queries": [{"purpose": "delete", "sql": "SELECT 1 LIMIT 1", "params": {}}],
    }
    with pytest.raises(ValueError, match="purpose"):
        housing.validate_plan(plan)


def test_validate_plan_accepts_clarification_status_without_queries(housing):
    # status="clarification_required" doesn't require a queries[] list.
    housing.validate_plan({"status": "clarification_required", "clarification": "请告诉我预算"})


def test_neighborhood_validate_plan_same_rules(neighborhood):
    """Both planners share the same hard rules."""
    bad = {
        "status": "sql_ready",
        "queries": [{"purpose": "analysis", "sql": "SELECT * FROM app_area_metrics_daily LIMIT 1", "params": {}}],
    }
    with pytest.raises(ValueError):
        neighborhood.validate_plan(bad)


# --- A6 — deterministic fallback when LLM disabled ---------------------------
def test_build_plan_falls_back_when_openai_key_missing(housing, monkeypatch):
    monkeypatch.setattr(housing.settings, "openai_api_key", "")
    monkeypatch.setattr(housing.settings, "use_llm_sql_planner", True)
    plan = housing.build_plan(
        "housing.rent_query", "Astoria 1居 2500", {"area_id": {"value": "QN0101"}}, {"currency": "USD"}
    )
    assert plan.get("planner_mode") == "deterministic"
    assert plan["status"] == "sql_ready"


def test_build_plan_falls_back_when_planner_disabled(housing, monkeypatch):
    monkeypatch.setattr(housing.settings, "openai_api_key", "fake-key")
    monkeypatch.setattr(housing.settings, "use_llm_sql_planner", False)
    plan = housing.build_plan("housing.rent_query", "Astoria 1居", {}, {})
    assert plan.get("planner_mode") == "deterministic"


# --- H3 — prompt freshness (no leftover placeholders) ------------------------
PROMPT_DIR = REPO_ROOT / "shared" / "prompts"
PROMPT_FILES = sorted(PROMPT_DIR.rglob("*.txt"))


@pytest.mark.parametrize("prompt_file", PROMPT_FILES, ids=lambda p: p.relative_to(PROMPT_DIR).as_posix())
def test_prompt_has_no_unfilled_placeholders(prompt_file: Path):
    text = prompt_file.read_text(encoding="utf-8")
    for marker in ("TODO", "FIXME", "<placeholder>", "<TBD>"):
        assert marker not in text, f"{prompt_file.name} still contains '{marker}'"
    # Sanity — non-empty and contains some Chinese instruction or English keyword.
    assert len(text.strip()) > 50
