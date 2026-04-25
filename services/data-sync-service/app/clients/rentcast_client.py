"""RentCast API client.

Strict rate limiting per docs/NYC_Agent_Data_Sync_Design.md §6:
- per-run cap: RENTCAST_MAX_CALLS_PER_RUN
- per-month cap: RENTCAST_MAX_CALLS_PER_MONTH (enforced by the job
  reading app_data_sync_job_log.api_calls_used)
- no auto-retry on failure (avoid burning quota)
- manual trigger only
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.rentcast.io/v1"
DEFAULT_TIMEOUT = 60.0
LISTINGS_PER_CALL = 500  # RentCast max for /listings


class RentCastError(RuntimeError):
    pass


class RentCastQuotaExceeded(RentCastError):
    pass


class RentCastBudget:
    def __init__(self, max_per_run: int | None = None) -> None:
        self.max_per_run = max_per_run or settings.rentcast_max_calls_per_run
        self.used = 0

    def check_and_increment(self) -> None:
        if self.used >= self.max_per_run:
            raise RentCastQuotaExceeded(
                f"RentCast per-run cap reached ({self.max_per_run})"
            )
        self.used += 1


def _headers() -> dict[str, str]:
    if not settings.rentcast_api_key:
        raise RentCastError("RENTCAST_API_KEY not set; cannot call RentCast.")
    return {
        "Accept": "application/json",
        "X-Api-Key": settings.rentcast_api_key,
    }


def fetch_long_term_rentals(
    *,
    budget: RentCastBudget,
    city: str = "New York",
    state: str = "NY",
    status: str = "Active",
    limit: int = LISTINGS_PER_CALL,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Single page fetch from /listings/rental/long-term. No retry."""
    budget.check_and_increment()

    params = {
        "city": city,
        "state": state,
        "status": status,
        "limit": limit,
        "offset": offset,
    }
    url = f"{BASE_URL}/listings/rental/long-term"
    logger.info(
        "rentcast_request offset=%d limit=%d budget_used=%d",
        offset, limit, budget.used,
    )
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=_headers()) as client:
            r = client.get(url, params=params)
            if r.status_code in (401, 403):
                raise RentCastError(
                    f"RentCast auth failed ({r.status_code}); check RENTCAST_API_KEY"
                )
            if r.status_code == 429:
                raise RentCastQuotaExceeded(
                    "RentCast returned 429; remote quota exhausted"
                )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            # Some plans wrap response in {"data": [...]}; tolerate both.
            return data.get("data") or []
    except httpx.HTTPError as exc:
        # No retry — the doc explicitly forbids it for RentCast.
        raise RentCastError(f"RentCast HTTP error: {exc}") from exc
