"""Thin wrapper around NYC Open Data (Socrata).

Pagination per docs/NYC_Agent_Data_Sync_Design.md §11.4 + retry per §7.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://data.cityofnewyork.us/resource"
DEFAULT_TIMEOUT = 60.0


class SocrataError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.socrata_app_token:
        headers["X-App-Token"] = settings.socrata_app_token
    return headers


def fetch_all(
    dataset_id: str,
    *,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    page_size: int | None = None,
    max_rows: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield rows page-by-page. Retries with exponential backoff up to 3 times."""
    page_size = page_size or settings.socrata_page_size
    max_rows = max_rows or settings.socrata_max_rows_per_job
    url = f"{BASE_URL}/{dataset_id}.json"

    offset = 0
    fetched = 0
    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=_headers()) as client:
        while fetched < max_rows:
            params: dict[str, Any] = {
                "$limit": min(page_size, max_rows - fetched),
                "$offset": offset,
            }
            if select:
                params["$select"] = select
            if where:
                params["$where"] = where
            if order:
                params["$order"] = order

            page = _get_with_retry(client, url, params)
            if not page:
                return
            for row in page:
                yield row
            fetched += len(page)
            offset += len(page)
            if len(page) < params["$limit"]:
                return


def _get_with_retry(
    client: httpx.Client, url: str, params: dict[str, Any], retries: int = 3
) -> list[dict[str, Any]]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            wait = 2 ** (attempt - 1)
            logger.warning(
                "socrata_retry url=%s attempt=%d/%d wait=%ss err=%s",
                url, attempt, retries, wait, exc,
            )
            time.sleep(wait)
    raise SocrataError(f"GET {url} failed after {retries} attempts: {last_exc}")
