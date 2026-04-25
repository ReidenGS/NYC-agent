"""Overpass API client (OpenStreetMap).

Public service — strict rate limiting per docs/NYC_Agent_Data_Sync_Design.md
§7 (max 1 retry with delay) and §11.4 (sleep between requests).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_TIMEOUT = 120.0


class OverpassError(RuntimeError):
    pass


class OverpassQuotaExceeded(OverpassError):
    pass


class OverpassBudget:
    """Per-run request budget. Mutable counter passed into each call."""

    def __init__(self, max_requests: int | None = None) -> None:
        self.max_requests = max_requests or settings.overpass_max_requests_per_run
        self.used = 0

    def check_and_increment(self) -> None:
        if self.used >= self.max_requests:
            raise OverpassQuotaExceeded(
                f"Overpass per-run cap reached ({self.max_requests})"
            )
        self.used += 1


def post_query(query: str, *, budget: OverpassBudget, sleep_after: bool = True) -> dict[str, Any]:
    """Run a single Overpass QL query. Up to 1 retry with delay."""
    budget.check_and_increment()
    last_exc: Exception | None = None

    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                logger.info("overpass_request attempt=%d budget_used=%d", attempt, budget.used)
                r = client.post(
                    OVERPASS_URL,
                    data={"data": query},
                    headers={"User-Agent": "nyc-agent-data-sync/0.1"},
                )
                r.raise_for_status()
                payload = r.json()
                if sleep_after and settings.overpass_sleep_seconds > 0:
                    time.sleep(settings.overpass_sleep_seconds)
                return payload
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == 1:
                wait = max(settings.overpass_sleep_seconds, 5)
                logger.warning("overpass_retry waiting=%ss err=%s", wait, exc)
                time.sleep(wait)
            else:
                break

    raise OverpassError(f"Overpass POST failed after retry: {last_exc}")
