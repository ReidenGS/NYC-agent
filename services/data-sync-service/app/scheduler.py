"""APScheduler integration for data-sync-service.

Cadence follows docs/NYC_Agent_Data_Sync_Design.md §5:

  daily   02:30 ET   sync_nypd_crime, sync_311
  weekly  Sun 03:00  sync_facilities, sync_overpass_poi, sync_mta_static, sync_mta_bus_static
  weekly  Sun 04:30  build_map_layers      (after the weekly snapshot wave)
  monthly 1st 04:00  sync_zori_hud, sync_nta

Constraints:
  - Disabled entirely when SYNC_ENABLE_SCHEDULED_JOBS != true.
  - Paid jobs (sync_rentcast) are NEVER auto-scheduled. The HTTP
    confirm_paid gate protects the entrypoint, but we belt-and-suspenders
    here to make sure the scheduler can't bypass it.
  - Triggers reuse the same ThreadPoolExecutor as manual /sync/run/{job}
    so concurrent dispatches still serialize one job at a time.
  - Times are in America/New_York; the dataset cadence is NYC-anchored.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import jobs as jobs_registry
from app.settings import settings

logger = logging.getLogger(__name__)

NYC_TZ = ZoneInfo("America/New_York")

# Mirror routes_sync.PAID_JOBS — kept here too so this module is self-contained
# when imported by tests / CLI without the API layer.
_PAID_JOBS: set[str] = {"sync_rentcast"}


# (job_name, cron_kwargs) — see APScheduler CronTrigger docs.
SCHEDULE: list[tuple[str, dict[str, Any]]] = [
    # Daily — refresh the public Socrata pulls that change most often.
    ("sync_nypd_crime", {"hour": 2,  "minute": 30}),
    ("sync_311",        {"hour": 2,  "minute": 45}),
    # Weekly Sunday — slower-moving sources.
    ("sync_facilities",     {"day_of_week": "sun", "hour": 3, "minute":  0}),
    ("sync_overpass_poi",   {"day_of_week": "sun", "hour": 3, "minute": 30}),
    ("sync_mta_static",     {"day_of_week": "sun", "hour": 4, "minute":  0}),
    ("sync_mta_bus_static", {"day_of_week": "sun", "hour": 4, "minute": 15}),
    ("build_map_layers",    {"day_of_week": "sun", "hour": 4, "minute": 30}),
    # Monthly — boundaries and rent benchmark series.
    ("sync_nta",       {"day": 1, "hour": 4, "minute":  0}),
    ("sync_zori_hud",  {"day": 1, "hour": 4, "minute": 30}),
    # Annual — HUD publishes new FMR each fiscal year (Oct 1).
    # Run shortly after FY rollover to pick up the new numbers.
    ("sync_hud_fmr",   {"month": 10, "day": 5, "hour": 5, "minute": 0}),
]


_scheduler: BackgroundScheduler | None = None


def start(executor: ThreadPoolExecutor) -> BackgroundScheduler | None:
    """Initialise and start the scheduler. Returns None when disabled.

    `executor` is the same ThreadPool used by /sync/run/{job_name}, so
    scheduled and manual triggers share serialization.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    if not settings.sync_enable_scheduled_jobs:
        logger.info("scheduler_disabled SYNC_ENABLE_SCHEDULED_JOBS=false")
        return None

    sched = BackgroundScheduler(timezone=NYC_TZ)
    registered: list[str] = []

    for job_name, cron_kwargs in SCHEDULE:
        if job_name in _PAID_JOBS:
            logger.warning(
                "scheduler_skip_paid name=%s reason=paid_job_never_auto",
                job_name,
            )
            continue
        if job_name not in jobs_registry.JOBS:
            logger.warning("scheduler_skip_unknown name=%s", job_name)
            continue

        sched.add_job(
            _make_dispatcher(executor, job_name),
            trigger=CronTrigger(**cron_kwargs, timezone=NYC_TZ),
            id=f"sched__{job_name}",
            name=f"scheduled {job_name}",
            replace_existing=True,
            misfire_grace_time=3600,  # if container was down, skip if >1h late
            coalesce=True,            # multiple missed firings collapse to one
        )
        registered.append(job_name)

    sched.start()
    _scheduler = sched
    logger.info(
        "scheduler_started tz=%s registered=%d jobs=%s",
        NYC_TZ.key, len(registered), registered,
    )
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler_stopped")


def list_scheduled() -> list[dict[str, Any]]:
    """Return current schedule for /sync/scheduler introspection."""
    if _scheduler is None:
        return []
    out: list[dict[str, Any]] = []
    for job in _scheduler.get_jobs():
        out.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": (
                job.next_run_time.isoformat() if job.next_run_time else None
            ),
            "trigger": str(job.trigger),
        })
    return out


def _make_dispatcher(executor: ThreadPoolExecutor, job_name: str):
    """Return a 0-arg callable APScheduler can invoke. The dispatcher
    submits the actual work to the shared executor so jobs serialize."""
    def dispatch() -> None:
        logger.info("scheduler_fire name=%s", job_name)
        executor.submit(_safe_run, job_name)

    return dispatch


def _safe_run(job_name: str) -> None:
    try:
        jobs_registry.run_job(job_name, trigger_type="scheduled")
    except Exception:
        # Failure is already persisted to app_data_sync_job_log by job_run().
        logger.exception("scheduled_job_failed name=%s", job_name)
