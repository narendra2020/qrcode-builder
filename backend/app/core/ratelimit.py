"""
In-process sliding-window rate limiting for upload, AI, verification and
public endpoints. Per-process only: with more than one backend worker,
also enforce limits at the reverse proxy (see README → nginx limit_req).
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.models import User


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiters: dict[str, SlidingWindowLimiter] = {}


def _limiter(name: str, limit: int, window: float) -> SlidingWindowLimiter:
    if name not in _limiters:
        _limiters[name] = SlidingWindowLimiter(limit, window)
    return _limiters[name]


def reset_all() -> None:
    for limiter in _limiters.values():
        limiter.reset()


def client_ip(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _too_many() -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Please wait a moment and try again.")


def limit_by_ip(name: str, limit: int, window_seconds: float):
    limiter = _limiter(name, limit, window_seconds)

    def _dependency(request: Request) -> None:
        if settings.RATE_LIMIT_ENABLED and not limiter.hit(client_ip(request)):
            raise _too_many()

    return _dependency


def limit_by_user(name: str, limit: int, window_seconds: float):
    limiter = _limiter(name, limit, window_seconds)

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if settings.RATE_LIMIT_ENABLED and not limiter.hit(current_user.id):
            raise _too_many()
        return current_user

    return _dependency
