import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app import jobs as jobs_registry
from app.db.session import db_session
from app.repositories import sync_log_repo
from app.settings import settings

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

# Jobs that consume a paid external API. Calling them without the explicit
# ?confirm_paid=yes query parameter returns 412 with a budget preview and
# does NOT issue any external request. This is a hard server-side gate to
# prevent accidental quota burn (e.g. probe scripts, fat-finger curls,
# future automation forgetting the cost dimension).
PAID_JOBS: set[str] = {"sync_rentcast"}


@router.get("/sync/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": jobs_registry.list_jobs()}


@router.get("/sync/status")
def sync_status(limit: int = 20) -> dict[str, Any]:
    with db_session() as session:
        rows = sync_log_repo.list_recent(session, limit=limit)
    return {"recent": rows}


@router.post("/sync/run/{job_name}")
def run_job(job_name: str, confirm_paid: str | None = None) -> dict[str, Any]:
    if job_name not in jobs_registry.JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job: {job_name}")

    if job_name in PAID_JOBS and confirm_paid != "yes":
        # Hard gate: do NOT submit, do NOT call the external API. Return a
        # budget preview so the caller can decide whether to retry with
        # ?confirm_paid=yes.
        preview = _paid_budget_preview(job_name)
        raise HTTPException(
            status_code=412,
            detail={
                "error": "confirm_paid_required",
                "message": (
                    f"{job_name} consumes a paid external API. "
                    "Re-submit with ?confirm_paid=yes to proceed."
                ),
                **preview,
            },
        )

    # Fire-and-forget; status is observable via /sync/status.
    _executor.submit(_safe_run, job_name)
    return {
        "success": True,
        "job_name": job_name,
        "status": "submitted",
        "confirmed_paid": job_name in PAID_JOBS,
        "message": "Job submitted; poll /sync/status for progress.",
    }


def _paid_budget_preview(job_name: str) -> dict[str, Any]:
    """Return a budget snapshot for a paid job without calling the external API."""
    if job_name == "sync_rentcast":
        with db_session() as session:
            month_used = int(
                session.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(api_calls_used), 0)
                        FROM app_data_sync_job_log
                        WHERE job_name = 'sync_rentcast'
                          AND status IN ('succeeded', 'partial', 'failed')
                          AND date_trunc('month', started_at)
                              = date_trunc('month', NOW())
                        """
                    )
                ).scalar()
                or 0
            )
        return {
            "external_api": "RentCast",
            "month_calls_used": month_used,
            "monthly_cap": settings.rentcast_max_calls_per_month,
            "monthly_remaining": max(
                0, settings.rentcast_max_calls_per_month - month_used
            ),
            "per_run_cap": settings.rentcast_max_calls_per_run,
            "would_use_up_to": min(
                settings.rentcast_max_calls_per_run,
                max(0, settings.rentcast_max_calls_per_month - month_used),
            ),
            "cost_note": (
                "Each call hits api.rentcast.io and counts against your "
                "RentCast plan."
            ),
        }
    return {"external_api": "unknown"}


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
        # Defensive: the chain literal already excludes paid jobs, but if a
        # future edit adds one, refuse to call it from bootstrap. Only
        # /sync/run/{job}?confirm_paid=yes can dispatch paid work.
        if job_name in PAID_JOBS:
            logger.warning(
                "bootstrap_step skipped name=%s reason=paid_job_requires_explicit_confirm",
                job_name,
            )
            continue
        logger.info("bootstrap_step start name=%s", job_name)
        _safe_run(job_name, trigger_type="bootstrap")
        logger.info("bootstrap_step done  name=%s", job_name)
