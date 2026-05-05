"""Tiny Redis cache + rate-limit helpers shared across services.

Per docs/NYC_Agent_Backend_Tech_Framework.md §2.1 table C, Redis is used in
4 places: mcp-transit (trip cache), mcp-weather (NWS cache), api-gateway
(rate limit), data-sync-service (external API throttle).

Each service imports `RedisCache` and either caches function output via
`get_or_set_json()` or runs a simple `rate_limit_token_bucket()` check.
The connection is lazy and tolerates Redis being down — caching becomes a
no-op rather than crashing the service.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

logger = logging.getLogger(__name__)


class RedisCache:
    def __init__(self, url: str | None) -> None:
        self.url = (url or "").strip()
        self._client = None
        self._init_attempted = False

    @property
    def client(self):
        if self._client is not None or self._init_attempted:
            return self._client
        self._init_attempted = True
        if not self.url or redis is None:
            logger.info("redis disabled (url=%r, package=%s)", self.url, redis is not None)
            return None
        try:
            self._client = redis.Redis.from_url(self.url, decode_responses=True, socket_timeout=1.5)
            self._client.ping()
            logger.info("redis connected at %s", self.url)
        except Exception as exc:
            logger.warning("redis unavailable (%s); cache disabled", exc)
            self._client = None
        return self._client

    def get_json(self, key: str) -> Any | None:
        c = self.client
        if c is None:
            return None
        try:
            raw = c.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug("redis get failed (%s)", exc)
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        c = self.client
        if c is None:
            return
        try:
            c.set(key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception as exc:
            logger.debug("redis set failed (%s)", exc)

    def get_or_set_json(self, key: str, ttl_seconds: int, producer: Callable[[], Any]) -> Any:
        cached = self.get_json(key)
        if cached is not None:
            return cached
        value = producer()
        self.set_json(key, value, ttl_seconds)
        return value

    def rate_limit_token_bucket(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Sliding-window counter: allow up to `limit` calls per `window_seconds`.

        Returns True when allowed. When Redis is down, returns True (fail-open)
        so a Redis outage doesn't black out the service.
        """
        c = self.client
        if c is None:
            return True
        try:
            pipe = c.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, window_seconds)
            count, _ = pipe.execute()
            return int(count) <= limit
        except Exception as exc:
            logger.debug("redis rate_limit failed (%s)", exc)
            return True
