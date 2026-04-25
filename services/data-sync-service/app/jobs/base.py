"""Job execution template.

Every sync job follows the same lifecycle (NYC_Agent_Backend_Tech_Framework.md §11.3):
  1. create job_log row with status=running
  2. execute job body
  3. finalize job_log with succeeded / partial / failed and stats
"""
from __future__ import annotations

import logging
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

from ulid import ULID

from app.db.session import db_session
from app.repositories import sync_log_repo

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    job_id: str
    job_name: str
    status: str
    rows_fetched: int = 0
    rows_written: int = 0
    api_calls_used: int = 0
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobContext:
    job_id: str
    job_name: str
    trigger_type: str
    rows_fetched: int = 0
    rows_written: int = 0
    api_calls_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def _new_job_id(job_name: str) -> str:
    return f"{job_name}_{ULID()}"


@contextmanager
def job_run(
    job_name: str,
    trigger_type: str = "manual",
    target_scope: dict[str, Any] | None = None,
) -> Iterator[tuple[JobContext, JobResult]]:
    """Context manager that wraps a job execution with logging.

    Usage:
        with job_run("sync_nta") as (ctx, result):
            ctx.rows_fetched = ...
            ctx.rows_written = ...
    """
    job_id = _new_job_id(job_name)
    ctx = JobContext(job_id=job_id, job_name=job_name, trigger_type=trigger_type)
    result = JobResult(job_id=job_id, job_name=job_name, status="running")

    started = datetime.now(timezone.utc)
    logger.info("job_start name=%s id=%s trigger=%s", job_name, job_id, trigger_type)

    with db_session() as session:
        sync_log_repo.insert_running(
            session,
            job_id=job_id,
            job_name=job_name,
            trigger_type=trigger_type,
            target_scope=target_scope,
        )

    try:
        yield ctx, result
    except Exception as exc:
        result.status = "failed"
        result.error_code = type(exc).__name__
        result.error_message = str(exc)[:500]
        result.metadata = {**ctx.metadata, "traceback_tail": traceback.format_exc().splitlines()[-5:]}
        with db_session() as session:
            sync_log_repo.finalize(
                session,
                job_id=job_id,
                status=result.status,
                rows_fetched=ctx.rows_fetched,
                rows_written=ctx.rows_written,
                api_calls_used=ctx.api_calls_used,
                error_code=result.error_code,
                error_message=result.error_message,
                metadata=result.metadata,
            )
        logger.exception("job_failed name=%s id=%s", job_name, job_id)
        raise
    else:
        if result.status == "running":
            result.status = "succeeded"
        result.rows_fetched = ctx.rows_fetched
        result.rows_written = ctx.rows_written
        result.api_calls_used = ctx.api_calls_used
        result.metadata = ctx.metadata
        with db_session() as session:
            sync_log_repo.finalize(
                session,
                job_id=job_id,
                status=result.status,
                rows_fetched=ctx.rows_fetched,
                rows_written=ctx.rows_written,
                api_calls_used=ctx.api_calls_used,
                metadata=ctx.metadata,
            )
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        logger.info(
            "job_done name=%s id=%s status=%s rows_written=%d elapsed_s=%.2f",
            job_name, job_id, result.status, ctx.rows_written, elapsed,
        )
