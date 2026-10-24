import json
import logging
import time
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import redis.asyncio as aioredis
from config.settings import settings

logger = logging.getLogger("hotmic.redis")

# Bounded in-memory fallback for local dev or temporary Redis outages
_MAX_MEMORY_CACHE_SIZE = 1000
_MAX_MEMORY_RL_SIZE = 2000
_REDIS_COOLDOWN_SECONDS = 30.0
_FEED_VERSION_KEY = "hotmic:feed:ver"

_memory_cache: dict[str, tuple[Any, float]] = {}
_memory_rate_limits: dict[str, list[float]] = {}
_memory_feed_version: int = 1

_redis_client: Optional[aioredis.Redis] = None
_redis_retry_at: float = 0.0


def _normalize_redis_url(raw_url: str) -> tuple[str, float]:
    """Use 127.0.0.1 instead of localhost to avoid Windows IPv6 ::1 SYN timeout,
    and pick a tight timeout for local loopback vs remote TLS (Upstash).
    """
    parsed = urlparse(raw_url)
    host = parsed.hostname or ""
    is_local = host in ("localhost", "127.0.0.1", "::1")

    if host == "localhost":
        netloc = parsed.netloc.replace("localhost", "127.0.0.1", 1)
        raw_url = urlunparse(parsed._replace(netloc=netloc))

    timeout = 0.15 if is_local else 1.5
    return raw_url, timeout


def _get_redis() -> Optional[aioredis.Redis]:
    """Obtain or initialize the shared async Redis/Upstash client with auto-recovery."""
    global _redis_client, _redis_retry_at
    if time.monotonic() < _redis_retry_at:
        return None

    if _redis_client is None:
        raw_url = settings.REDIS_URL.get_secret_value().strip()
        if not raw_url:
            _redis_retry_at = float("inf")
            return None
        try:
            url, timeout = _normalize_redis_url(raw_url)
            _redis_client = aioredis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
            )
        except Exception as exc:
            logger.warning("Redis client init failed; falling back to memory for 30s: %s", exc)
            _redis_retry_at = time.monotonic() + _REDIS_COOLDOWN_SECONDS
            return None

    return _redis_client


def _is_local_redis() -> bool:
    raw_url = settings.REDIS_URL.get_secret_value().strip()
    host = urlparse(raw_url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


def _pause_redis(exc: Exception) -> None:
    """Fall back to in-memory cache (30s retry for Upstash, 300s when local Redis is off)."""
    global _redis_client, _redis_retry_at
    cooldown = 300.0 if _is_local_redis() else _REDIS_COOLDOWN_SECONDS
    if time.monotonic() >= _redis_retry_at:
        logger.info("Redis unavailable (%s); using in-memory store for %.0fs.", exc, cooldown)
    _redis_retry_at = time.monotonic() + cooldown
    _redis_client = None


async def get_cache(key: str) -> Optional[Any]:
    """Retrieve cached JSON value from Redis or bounded in-memory fallback."""
    client = _get_redis()
    if client:
        try:
            data = await client.get(key)
            if data is not None:
                return json.loads(data)
        except Exception as exc:
            _pause_redis(exc)

    now = time.time()
    entry = _memory_cache.get(key)
    if entry is not None:
        val, expiry = entry
        if expiry > now:
            return val
        _memory_cache.pop(key, None)

    return None


async def set_cache(key: str, value: Any, ttl_seconds: int = 30) -> None:
    """Store JSON-serializable value in Redis (or bounded in-memory fallback) with TTL."""
    client = _get_redis()
    if client:
        try:
            serialized = json.dumps(value, default=str)
            await client.set(key, serialized, ex=ttl_seconds)
            return
        except Exception as exc:
            _pause_redis(exc)

    now = time.time()
    if len(_memory_cache) >= _MAX_MEMORY_CACHE_SIZE:
        expired = [k for k, (_, exp) in _memory_cache.items() if exp <= now]
        for k in expired:
            _memory_cache.pop(k, None)
        if len(_memory_cache) >= _MAX_MEMORY_CACHE_SIZE:
            for k in list(_memory_cache.keys())[:100]:
                _memory_cache.pop(k, None)

    _memory_cache[key] = (value, now + ttl_seconds)


async def get_feed_version() -> int:
    """Return current O(1) feed cache generation counter (avoids Redis SCAN)."""
    global _memory_feed_version
    client = _get_redis()
    if client:
        try:
            raw = await client.get(_FEED_VERSION_KEY)
            return int(raw) if raw is not None else 1
        except Exception as exc:
            _pause_redis(exc)
    return _memory_feed_version


async def invalidate_feed_cache() -> None:
    """Invalidate public/personal feed caches in O(1) via version increment (no SCAN)."""
    global _memory_feed_version
    _memory_feed_version += 1

    client = _get_redis()
    if client:
        try:
            await client.incr(_FEED_VERSION_KEY)
            return
        except Exception as exc:
            _pause_redis(exc)


async def delete_cache_pattern(pattern: str) -> None:
    """Compatibility helper to remove matching keys."""
    if pattern == "hotmic:feed:*":
        await invalidate_feed_cache()
        return

    client = _get_redis()
    if client:
        try:
            keys_to_del = []
            async for k in client.scan_iter(match=pattern, count=100):
                keys_to_del.append(k)
                if len(keys_to_del) >= 200:
                    await client.delete(*keys_to_del)
                    keys_to_del = []
            if keys_to_del:
                await client.delete(*keys_to_del)
        except Exception as exc:
            _pause_redis(exc)

    now = time.time()
    raw_pattern = pattern.replace("*", "")
    for k in [k for k, (_, exp) in _memory_cache.items() if (raw_pattern in k) or (exp <= now)]:
        _memory_cache.pop(k, None)


async def check_rate_limit(key: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    """Sliding-window rate limiter using Redis pipeline or bounded in-memory fallback."""
    client = _get_redis()
    rl_key = f"hotmic:ratelimit:{key}"

    if client:
        try:
            now = time.time()
            pipe = client.pipeline()
            pipe.zremrangebyscore(rl_key, 0, now - window_seconds)
            pipe.zcard(rl_key)
            pipe.zadd(rl_key, {str(now): now})
            pipe.expire(rl_key, window_seconds)
            results = await pipe.execute()
            return results[1] < max_requests
        except Exception as exc:
            _pause_redis(exc)

    now = time.time()
    if len(_memory_rate_limits) >= _MAX_MEMORY_RL_SIZE:
        stale = [k for k, ts in _memory_rate_limits.items() if not ts or ts[-1] <= now - window_seconds]
        for k in stale:
            _memory_rate_limits.pop(k, None)
        if len(_memory_rate_limits) >= _MAX_MEMORY_RL_SIZE:
            for k in list(_memory_rate_limits.keys())[:200]:
                _memory_rate_limits.pop(k, None)

    timestamps = [t for t in _memory_rate_limits.get(key, []) if t > now - window_seconds]
    if len(timestamps) >= max_requests:
        _memory_rate_limits[key] = timestamps
        return False

    timestamps.append(now)
    _memory_rate_limits[key] = timestamps
    return True
