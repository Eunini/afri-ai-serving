import io

import httpx
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from services.chat.app import create_app as chat_app
from services.speech.app import create_app as speech_app


def wav():
    stream = io.BytesIO()
    sf.write(stream, np.zeros(1600), 16000, format="WAV")
    return stream.getvalue()


def test_speech_auth_decode_failure_and_metrics(monkeypatch):
    monkeypatch.setenv("API_KEY", "unit-test-only")
    calls = []
    with TestClient(speech_app(lambda data: calls.append(data) or "Ẹ káàárọ̀")) as client:
        assert client.get("/ready").status_code == 200
        assert client.post("/transcribe", content=wav()).status_code == 401
        headers = {"Authorization": "Bearer unit-test-only"}
        assert client.post("/transcribe", content=b"invalid", headers=headers).status_code == 415
        multichannel = io.BytesIO()
        sf.write(multichannel, np.zeros((1600, 3)), 16000, format="WAV")
        assert client.post("/transcribe", content=multichannel.getvalue(), headers=headers).status_code == 422
        response = client.post("/transcribe", content=wav(), headers=headers)
        assert response.json()["text"] == "Ẹ káàárọ̀"
        assert len(calls) == 1
        assert "afri_audio_seconds_total" in client.get("/metrics").text


def test_chat_auth_readiness_proxy_and_limits(monkeypatch):
    monkeypatch.setenv("API_KEY", "unit-test-only")

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "B"}}]})

    with TestClient(chat_app(httpx.MockTransport(handler))) as client:
        assert client.get("/ready").status_code == 200
        body = {"messages": [{"role": "user", "content": "hello"}]}
        assert client.post("/v1/chat/completions", json=body).status_code == 401
        headers = {"Authorization": "Bearer unit-test-only"}
        assert client.post("/v1/chat/completions", json=body, headers=headers).json()["choices"]
        assert (
            client.post(
                "/v1/chat/completions", json={**body, "max_tokens": 9999}, headers=headers
            ).status_code
            == 422
        )


def test_upstream_failure_is_503(monkeypatch):
    monkeypatch.setenv("API_KEY", "unit-test-only")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text="internal information")
    )
    with TestClient(chat_app(transport)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}]},
            headers={"Authorization": "Bearer unit-test-only"},
        )
        assert response.status_code == 503
        assert "internal information" not in response.text
