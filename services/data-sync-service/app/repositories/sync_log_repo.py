"""CRUD for app_data_sync_job_log.

Schema reference: docs/NYC_Agent_Data_Sources_API_SQL.md §6 (table 17).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def insert_running(
    session: Session,
    *,
    job_id: str,
    job_name: str,
    trigger_type: str,
    target_scope: dict[str, Any] | None = None,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO app_data_sync_job_log
                (job_id, job_name, status, trigger_type, target_scope, started_at)
            VALUES
                (:job_id, :job_name, 'running', :trigger_type,
                 CAST(:target_scope AS JSONB), :started_at)
            """
        ),
        {
            "job_id": job_id,
            "job_name": job_name,
            "trigger_type": trigger_type,
            "target_scope": _to_json(target_scope or {}),
            "started_at": datetime.now(timezone.utc),
        },
    )


def finalize(
    session: Session,
    *,
    job_id: str,
    status: str,
    rows_fetched: int = 0,
    rows_written: int = 0,
    api_calls_used: int = 0,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.execute(
        text(
            """
            UPDATE app_data_sync_job_log
            SET status = :status,
                finished_at = :finished_at,
                rows_fetched = :rows_fetched,
                rows_written = :rows_written,
                api_calls_used = :api_calls_used,
                error_code = :error_code,
                error_message = :error_message,
                metadata = CAST(:metadata AS JSONB)
            WHERE job_id = :job_id
            """
        ),
        {
            "job_id": job_id,
            "status": status,
            "finished_at": datetime.now(timezone.utc),
            "rows_fetched": rows_fetched,
            "rows_written": rows_written,
            "api_calls_used": api_calls_used,
            "error_code": error_code,
            "error_message": error_message,
            "metadata": _to_json(metadata or {}),
        },
    )


def list_recent(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT job_id, job_name, status, trigger_type,
                   started_at, finished_at,
                   rows_fetched, rows_written, api_calls_used,
                   error_code, error_message
            FROM app_data_sync_job_log
            ORDER BY started_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def _to_json(obj: Any) -> str:
    import json

    return json.dumps(obj, default=str)
