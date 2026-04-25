"""Job registry. Each job exposes a `run(trigger_type) -> JobResult`."""
from app.jobs.base import JobResult
from app.jobs import (
    sync_facilities,
    sync_mta_static,
    sync_nta,
    sync_nypd_crime,
    sync_overpass_poi,
)

JOBS: dict[str, callable] = {
    "sync_nta": sync_nta.run,
    "sync_nypd_crime": sync_nypd_crime.run,
    "sync_overpass_poi": sync_overpass_poi.run,
    "sync_facilities": sync_facilities.run,
    "sync_mta_static": sync_mta_static.run,
}


def list_jobs() -> list[str]:
    return sorted(JOBS.keys())


def run_job(job_name: str, trigger_type: str = "manual") -> JobResult:
    if job_name not in JOBS:
        raise KeyError(f"Unknown job: {job_name}")
    return JOBS[job_name](trigger_type=trigger_type)
