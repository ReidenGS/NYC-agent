"""F1–F3 — mcp-sql is the only service that runs LLM-generated SQL against
real Postgres. Its validate_sql() is the safety wire and MUST refuse:
  F1. non-SELECT statements (INSERT/UPDATE/DELETE/DROP/ALTER/etc)
  F2. queries without LIMIT or with LIMIT > max
  F3. tables outside the domain whitelist (incl. information_schema)

We test against the live mcp-sql service over HTTP so the policy + container
config + DB binding all participate.
"""
from __future__ import annotations

import os

import httpx
import pytest

MCP_SQL_URL = os.environ.get("MCP_SQL_URL", "http://localhost:8020").rstrip("/")
ENDPOINT = f"{MCP_SQL_URL}/tools/execute_readonly_sql"


@pytest.fixture(scope="module")
def http():
    with httpx.Client(timeout=10.0) as client:
        yield client


def _exec(http: httpx.Client, sql: str, *, domain: str = "safety",
          params: dict | None = None, max_rows: int = 5) -> dict:
    body = {"arguments": {"domain": domain, "sql": sql, "params": params or {}, "max_rows": max_rows}}
    response = http.post(ENDPOINT, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_baseline_select_succeeds(http):
    """Sanity — a clean SELECT against an allowed table should pass."""
    body = _exec(
        http,
        "SELECT area_id FROM v_area_metrics_latest LIMIT 1",
        domain="safety",
    )
    assert body["status"] in {"success", "no_data"}, body
    assert body["error"] is None


# --- F1: non-SELECT rejection ------------------------------------------------
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO v_area_metrics_latest (area_id) VALUES ('XX') ",
        "UPDATE v_area_metrics_latest SET crime_count_30d = 0",
        "DELETE FROM v_area_metrics_latest",
        "DROP TABLE v_area_metrics_latest",
        "ALTER TABLE v_area_metrics_latest ADD COLUMN x int",
        "TRUNCATE v_area_metrics_latest",
    ],
)
def test_rejects_non_select_statement(http, sql):
    body = _exec(http, sql)
    assert body["status"] == "validation_error", body
    assert body["error"] is not None
    # Don't assert exact code — just that it's a validation refusal, not exec.


# --- F2: LIMIT enforcement ---------------------------------------------------
def test_rejects_query_without_limit(http):
    body = _exec(http, "SELECT area_id FROM v_area_metrics_latest")
    assert body["status"] == "validation_error", body


def test_caps_max_rows_to_policy(http):
    """If caller asks for max_rows > policy default, mcp-sql silently caps."""
    body = _exec(
        http,
        "SELECT area_id FROM v_area_metrics_latest LIMIT 1000",
        max_rows=10000,
    )
    # Cap is settings.sql_max_rows_default (typically 50). Should still
    # succeed but return no more than the cap.
    if body["status"] == "success":
        assert len(body["data"]) <= 50


# --- F3: table whitelist + system catalogs blocked ---------------------------
@pytest.mark.parametrize(
    "sql",
    [
        # Disallowed system catalogs.
        "SELECT * FROM information_schema.tables LIMIT 5",
        "SELECT relname FROM pg_class LIMIT 5",
        "SELECT * FROM pg_catalog.pg_tables LIMIT 5",
        # Tables that exist but aren't whitelisted for this domain.
        "SELECT * FROM app_data_sync_job_log LIMIT 5",
    ],
)
def test_rejects_non_whitelisted_tables(http, sql):
    body = _exec(http, sql, domain="safety")
    assert body["status"] == "validation_error", body


def test_rejects_select_star(http):
    """SELECT * is forbidden by policy (the LLM might leak unexpected cols)."""
    body = _exec(http, "SELECT * FROM v_area_metrics_latest LIMIT 1")
    assert body["status"] == "validation_error", body


def test_unknown_domain_returns_404_on_schema_endpoint(http):
    """The /schema/{domain} endpoint must reject unknown domains so callers
    don't probe for a whitelist that doesn't exist."""
    response = http.get(f"{MCP_SQL_URL}/schema/totally_made_up")
    assert response.status_code == 404
