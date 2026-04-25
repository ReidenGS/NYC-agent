from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException

from app import jobs as jobs_registry
from app.db.session import db_session
from app.repositories import sync_log_repo

router = APIRouter()

# Background runner — single worker so jobs serialize per-instance.
# Sufficient for MVP; revisit when we add more concurrent jobs.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync-job")


@router.get("/sync/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": jobs_registry.list_jobs()}


@router.get("/sync/status")
def sync_status(limit: int = 20) -> dict[str, Any]:
    with db_session() as session:
        rows = sync_log_repo.list_recent(session, limit=limit)
    return {"recent": rows}


@router.post("/sync/run/{job_name}")
def run_job(job_name: str) -> dict[str, Any]:
    if job_name not in jobs_registry.JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job: {job_name}")
    # Fire-and-forget; status is observable via /sync/status.
    _executor.submit(_safe_run, job_name)
    return {
        "success": True,
        "job_name": job_name,
        "status": "submitted",
        "message": "Job submitted; poll /sync/status for progress.",
    }


def _safe_run(job_name: str) -> None:
    try:
        jobs_registry.run_job(job_name, trigger_type="manual")
    except Exception:
        # Failure is already persisted to app_data_sync_job_log by job_run().
        pass
