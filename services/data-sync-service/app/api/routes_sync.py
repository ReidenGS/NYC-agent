import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException

from app import jobs as jobs_registry
from app.db.session import db_session
from app.repositories import sync_log_repo

logger = logging.getLogger(__name__)
router = APIRouter()

# Background runner — single worker so jobs serialize per-instance.
# Sufficient for MVP; revisit when we add more concurrent jobs.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync-job")

# Bootstrap chain order (docs/NYC_Agent_Data_Sync_Design.md §14):
#   NTAs first (every spatial assignment depends on them), then crime,
#   POIs (overpass + facilities), MTA static, then 311.
# RentCast and ZORI are NOT in bootstrap because they have cost/api-key
# constraints — operators run them explicitly.
BOOTSTRAP_CHAIN = [
    "sync_nta",
    "sync_nypd_crime",
    "sync_overpass_poi",
    "sync_facilities",
    "sync_mta_static",
    "sync_311",
]


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


def _safe_run(job_name: str, trigger_type: str = "manual") -> None:
    try:
        jobs_registry.run_job(job_name, trigger_type=trigger_type)
    except Exception:
        # Failure is already persisted to app_data_sync_job_log by job_run().
        pass


@router.post("/sync/run-bootstrap")
def run_bootstrap() -> dict[str, Any]:
    """Submit the bootstrap chain. Each job runs in sequence on the same
    single-worker executor; failures of one step do NOT abort later steps
    (NTA failure aside — downstream jobs will skip rows they can't assign).
    Status of each step is visible via /sync/status."""
    _executor.submit(_run_bootstrap_chain)
    return {
        "success": True,
        "chain": BOOTSTRAP_CHAIN,
        "status": "submitted",
        "message": "Bootstrap chain submitted; poll /sync/status for per-step progress.",
    }


def _run_bootstrap_chain() -> None:
    for job_name in BOOTSTRAP_CHAIN:
        logger.info("bootstrap_step start name=%s", job_name)
        _safe_run(job_name, trigger_type="bootstrap")
        logger.info("bootstrap_step done  name=%s", job_name)
