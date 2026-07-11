"""HTTP middleware — request logging + simple per-IP rate limits."""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("intakepilot.http")


class TokenBucket:
    """In-memory token bucket. capacity tokens refill at `rate` per second."""

    def __init__(self, capacity: float, rate: float):
        self.capacity = capacity
        self.rate = rate
        self.tokens = capacity
        self.updated = time.monotonic()

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.updated
        self.updated = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens < cost:
            return False
        self.tokens -= cost
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket limits for session create + turns (abuse soft-cap)."""

    def __init__(self, app, sessions_per_min: float = 30,
                 turns_per_min: float = 60):
        super().__init__(app)
        self._sessions_per_min = sessions_per_min
        self._turns_per_min = turns_per_min
        self._buckets: dict[tuple[str, str], TokenBucket] = {}

    def _bucket(self, key: tuple[str, str], capacity: float) -> TokenBucket:
        b = self._buckets.get(key)
        if b is None:
            b = TokenBucket(capacity=capacity, rate=capacity / 60.0)
            self._buckets[key] = b
        return b

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host or "unknown"
        return "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "POST":
            path = request.url.path.rstrip("/")
            ip = self._client_ip(request)
            limit = None
            kind = None
            if path == "/api/sessions":
                limit, kind = self._sessions_per_min, "sessions"
            elif path.startswith("/api/sessions/") and path.endswith("/turns"):
                limit, kind = self._turns_per_min, "turns"
            elif path.startswith("/api/share/") and path.endswith("/clone"):
                limit, kind = 20.0, "share_clone"
            elif "/share" in path and request.method == "POST":
                limit, kind = 20.0, "share_create"
            if limit is not None and kind is not None:
                if not self._bucket((ip, kind), limit).allow():
                    return JSONResponse(
                        {"detail": "rate limit exceeded"}, status_code=429)
        return await call_next(request)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Structured JSON access log with a short request_id."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(json.dumps({
                "event": "request", "request_id": request_id,
                "method": request.method, "path": request.url.path,
                "status": status, "duration_ms": elapsed_ms,
            }))
