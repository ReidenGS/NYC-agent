"""A8 — data-sync `job_run` context manager: success / failure / partial paths
all log a finalize() call with the right status and counters.
"""
from __future__ import annotations

import importlib
from contextlib import contextmanager

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture()
def base():
    add_service_to_path("data-sync-service")
    return importlib.import_module("app.jobs.base")


@pytest.fixture()
def captured_logs(base, monkeypatch):
    """Replace db_session + sync_log_repo so job_run is fully in-memory."""
    calls = {"insert_running": [], "finalize": []}

    @contextmanager
    def fake_db_session():
        yield None

    def fake_insert(session, **kwargs):
        calls["insert_running"].append(kwargs)

    def fake_finalize(session, **kwargs):
        calls["finalize"].append(kwargs)

    monkeypatch.setattr(base, "db_session", fake_db_session)
    monkeypatch.setattr(base.sync_log_repo, "insert_running", fake_insert)
    monkeypatch.setattr(base.sync_log_repo, "finalize", fake_finalize)
    return calls


def test_job_run_success_finalizes_with_succeeded(base, captured_logs):
    with base.job_run("my_test_job") as (ctx, result):
        ctx.rows_fetched = 100
        ctx.rows_written = 95
        ctx.api_calls_used = 3
    assert result.status == "succeeded"
    assert result.rows_written == 95
    assert len(captured_logs["insert_running"]) == 1
    assert len(captured_logs["finalize"]) == 1
    final = captured_logs["finalize"][0]
    assert final["status"] == "succeeded"
    assert final["rows_written"] == 95
    assert final["api_calls_used"] == 3
    assert "error_code" not in final or final.get("error_code") is None


def test_job_run_failure_finalizes_with_failed_and_reraises(base, captured_logs):
    with pytest.raises(RuntimeError, match="boom"):
        with base.job_run("my_failing_job") as (ctx, result):
            ctx.rows_fetched = 5
            raise RuntimeError("boom")
    final = captured_logs["finalize"][0]
    assert final["status"] == "failed"
    assert final["error_code"] == "RuntimeError"
    assert final["error_message"] == "boom"
    # Counters captured even on failure.
    assert final["rows_fetched"] == 5


def test_job_run_partial_status_preserved(base, captured_logs):
    """A job can self-mark partial and the wrapper should not overwrite it."""
    with base.job_run("partial_job") as (ctx, result):
        ctx.rows_written = 10
        result.status = "partial"
    assert result.status == "partial"
    final = captured_logs["finalize"][0]
    assert final["status"] == "partial"


def test_job_run_assigns_unique_ids(base, captured_logs):
    with base.job_run("job_a") as (_, _r1):
        pass
    with base.job_run("job_a") as (_, _r2):
        pass
    ids = [c["job_id"] for c in captured_logs["insert_running"]]
    assert len(set(ids)) == 2
    assert all(jid.startswith("job_a_") for jid in ids)
