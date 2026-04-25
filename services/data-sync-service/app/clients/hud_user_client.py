"""HUD USER Fair Market Rent API client.

Auth:  Authorization: Bearer <HUD_USER_API_TOKEN>
Docs:  https://www.huduser.gov/portal/dataset/fmr-api.html

The token is a long-lived JWT, free to obtain from huduser.gov. No
per-call cost — but the API is gov infrastructure so keep call volume
modest. We make at most 5 calls per run (one per NYC county).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.huduser.gov/hudapi/public/fmr"
DEFAULT_TIMEOUT = 60.0


class HudError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not settings.hud_user_api_token:
        raise HudError("HUD_USER_API_TOKEN not set; cannot call HUD User API.")
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.hud_user_api_token}",
    }


def fetch_fmr_for_county(fips_entity_id: str, year: int) -> dict[str, Any]:
    """Return the parsed `data` payload for a county FMR record.

    `fips_entity_id` is the 10-digit ID HUD User uses (county FIPS + 99999),
    e.g. '3606199999' for New York County.

    Up to 2 retries with simple linear backoff (this is a slow gov
    endpoint; aggressive retry is unhelpful).
    """
    url = f"{BASE_URL}/data/{fips_entity_id}"
    last_exc: Exception | None = None

    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=_headers()) as client:
                logger.info("hud_request entity=%s year=%d attempt=%d", fips_entity_id, year, attempt)
                r = client.get(url, params={"year": year})
                if r.status_code in (401, 403):
                    raise HudError(
                        f"HUD auth failed ({r.status_code}); check HUD_USER_API_TOKEN"
                    )
                r.raise_for_status()
                payload = r.json()
                if "data" not in payload:
                    raise HudError(f"HUD response missing 'data': {payload!r}")
                return payload["data"]
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            if attempt == 1:
                import time
                time.sleep(3)
    raise HudError(f"HUD GET {url}?year={year} failed after retry: {last_exc}")
