import asyncio
import hmac
import os
import time

from fastapi import Header, HTTPException
from prometheus_client import Counter, Histogram
from starlette.responses import JSONResponse

REQUESTS = Counter("afri_requests_total", "HTTP requests", ["service", "route", "status"])
LATENCY = Histogram(
    "afri_request_duration_seconds",
    "HTTP latency",
    ["service", "route"],
    buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)


def require_authorization(authorization):
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(503, "API key is not configured")
    if not hmac.compare_digest(authorization.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(401, "Invalid API key")


async def authorize(authorization: str = Header(default="")):
    require_authorization(authorization)


class RequestBudgetMiddleware:
    """Authenticate and bound uploads before parsing, with no unbounded model queue.

    Admission lasts through the entire response, including a streamed response or
    disconnect. Limits are per worker; the supplied containers run one worker.
    """

    def __init__(self, app, *, path, max_body_bytes, max_inflight, upload_timeout=30):
        self.app = app
        self.path = path
        self.max_body_bytes = max_body_bytes
        self.max_inflight = max_inflight
        self.upload_timeout = upload_timeout
        self.inflight = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope["path"] != self.path:
            return await self.app(scope, receive, send)

        async def reject(status, detail):
            response = JSONResponse(
                {"detail": detail}, status_code=status,
                headers={"Retry-After": "1"} if status == 429 else None,
            )
            await response(scope, receive, send)

        auth = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
        try:
            require_authorization(auth[0].decode("latin1") if len(auth) == 1 else "")
        except HTTPException as error:
            return await reject(error.status_code, error.detail)
        lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        if lengths:
            if len(lengths) != 1 or not lengths[0] or any(c not in b"0123456789" for c in lengths[0]):
                return await reject(400, "Invalid Content-Length")
            # Avoid converting arbitrarily long attacker-controlled integers.
            significant = lengths[0].lstrip(b"0") or b"0"
            if len(significant) > 12 or int(significant) > self.max_body_bytes:
                return await reject(413, "Request body exceeds the upload limit")
        if self.inflight >= self.max_inflight:
            return await reject(429, "Model busy; retry later")
        # No await between the check and increment: admission is atomic on this event loop.
        self.inflight += 1
        try:
            chunks, size = [], 0
            deadline = asyncio.get_running_loop().time() + self.upload_timeout
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return await reject(408, "Upload timed out")
                try:
                    message = await asyncio.wait_for(receive(), timeout=remaining)
                except asyncio.TimeoutError:
                    return await reject(408, "Upload timed out")
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > self.max_body_bytes:
                    return await reject(413, "Request body exceeds the upload limit")
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            del chunks
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
        finally:
            self.inflight -= 1


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
