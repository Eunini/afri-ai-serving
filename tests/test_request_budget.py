import asyncio

import httpx

from services.chat.app import create_app
from services.common import RequestBudgetMiddleware


def test_large_json_is_rejected_before_parsing_and_auth_precedes_upload(monkeypatch):
    monkeypatch.setenv("API_KEY", "budget-test")

    async def check():
        app = create_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = "/v1/chat/completions"
            response = await client.post(path, content=b"x" * 300000)
            assert response.status_code == 401
            response = await client.post(
                path, content=b"invalid-json", headers={
                    "Authorization": "Bearer budget-test", "Content-Length": "300000"
                },
            )
            assert response.status_code == 413

            async def chunked():
                yield b"x" * 150000
                yield b"x" * 150000

            response = await client.post(
                path, content=chunked(), headers={"Authorization": "Bearer budget-test"}
            )
            assert response.status_code == 413

    asyncio.run(check())


def test_stream_keeps_its_slot_until_disconnect_then_releases_it(monkeypatch):
    monkeypatch.setenv("API_KEY", "budget-test")

    async def check():
        started, finish = asyncio.Event(), asyncio.Event()

        async def upstream(scope, receive, send):
            assert (await receive())["body"] == b"{}"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            started.set()
            await finish.wait()  # A response stream is still in flight.
            await send({"type": "http.response.body", "body": b"ok"})

        budget = RequestBudgetMiddleware(
            upstream, path="/generate", max_body_bytes=100, max_inflight=1
        )
        scope = {
            "type": "http", "method": "POST", "path": "/generate",
            "headers": [(b"authorization", b"Bearer budget-test")],
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        responses = []

        async def send(message):
            responses.append(message)

        active = asyncio.create_task(budget(scope, receive, send))
        await started.wait()
        responses.clear()
        await budget(scope, receive, send)
        assert responses[0]["status"] == 429
        assert (b"retry-after", b"1") in responses[0]["headers"]
        active.cancel()  # Client disconnect/cancellation during a stream.
        try:
            await active
        except asyncio.CancelledError:
            pass
        finish.set()
        responses.clear()
        await budget(scope, receive, send)
        assert responses[0]["status"] == 200 and budget.inflight == 0

    asyncio.run(check())


def test_slow_upload_times_out_and_does_not_keep_a_model_slot(monkeypatch):
    monkeypatch.setenv("API_KEY", "budget-test")

    async def check():
        async def unreachable(*args):
            raise AssertionError("Timed-out upload must never reach the model")

        budget = RequestBudgetMiddleware(
            unreachable, path="/generate", max_body_bytes=100,
            max_inflight=1, upload_timeout=0.01,
        )
        scope = {
            "type": "http", "method": "POST", "path": "/generate",
            "headers": [(b"authorization", b"Bearer budget-test")],
        }

        async def receive():
            await asyncio.Event().wait()

        messages = []

        async def send(message):
            messages.append(message)

        await budget(scope, receive, send)
        assert messages[0]["status"] == 408 and budget.inflight == 0

    asyncio.run(check())
