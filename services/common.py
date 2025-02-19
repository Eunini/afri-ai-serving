import hmac
import os
import time

from fastapi import Header, HTTPException
from prometheus_client import Counter, Histogram

REQUESTS = Counter("afri_requests_total", "HTTP requests", ["service", "route", "status"])
LATENCY = Histogram(
    "afri_request_duration_seconds",
    "HTTP latency",
    ["service", "route"],
    buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)


async def authorize(authorization: str = Header(default="")):
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(503, "API key is not configured")
    if not hmac.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(401, "Invalid API key")


def instrument(app, service):
    @app.middleware("http")
    async def measure(request, call_next):
        start, status = time.perf_counter(), 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            # Do not label raw URLs, prompts, filenames, or arbitrary model values.
            REQUESTS.labels(service, path, str(status)).inc()
            LATENCY.labels(service, path).observe(time.perf_counter() - start)
