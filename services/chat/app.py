import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from services.common import authorize, instrument

STREAM_ERRORS = Counter("afri_chat_stream_errors_total", "Chat streaming errors after headers")
STREAM_LATENCY = Histogram("afri_chat_stream_duration_seconds", "Complete chat stream duration")


class Message(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(max_length=16000)


class ChatRequest(BaseModel):
    model: str = "local"
    messages: list[Message] = Field(min_length=1, max_length=32)
    max_tokens: int = Field(default=128, ge=1, le=512)
    temperature: float = Field(default=0, ge=0, le=2)
    stream: bool = False
    stream_options: dict | None = None


def create_app(transport=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.client = httpx.AsyncClient(
            base_url=os.environ.get("LLAMA_URL", "http://127.0.0.1:8081"),
            timeout=180,
            transport=transport,
        )
        yield
        await app.state.client.aclose()

    app = FastAPI(title="African-language chat gateway", lifespan=lifespan)
    instrument(app, "chat")

    @app.get("/health")
    def health():
        return {"status": "alive"}

    @app.get("/ready")
    async def ready():
        try:
            result = await app.state.client.get("/health")
            result.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, "Language model is not ready") from None
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/chat/completions", dependencies=[Depends(authorize)])
    async def chat(payload: ChatRequest):
        if sum(len(m.content) for m in payload.messages) > 32000:
            raise HTTPException(413, "Messages exceed the total input limit")
        body = payload.model_dump(exclude_none=True)
        body["model"] = "local"
        request = app.state.client.build_request("POST", "/v1/chat/completions", json=body)
        try:
            upstream = await app.state.client.send(request, stream=payload.stream)
        except httpx.HTTPError:
            raise HTTPException(503, "Language model unavailable") from None
        if upstream.status_code != 200:
            await upstream.aclose()
            raise HTTPException(503, "Language model unavailable")
        if not payload.stream:
            try:
                return upstream.json()
            finally:
                await upstream.aclose()

        async def chunks():
            import time

            start = time.perf_counter()
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            except httpx.HTTPError:
                STREAM_ERRORS.inc()
                raise
            finally:
                STREAM_LATENCY.observe(time.perf_counter() - start)
                await upstream.aclose()

        return StreamingResponse(chunks(), media_type="text/event-stream")

    return app


app = create_app()
