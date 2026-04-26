from __future__ import annotations

from datetime import datetime, timedelta, timezone

NY_TZ = timezone(timedelta(hours=-4))


def now_iso() -> str:
    return datetime.now(NY_TZ).replace(microsecond=0).isoformat()
