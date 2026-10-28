import json

import httpx
import pytest

from scripts.cluster_smoke import smoke


def test_rollout_retry_preserves_initial_unavailability_without_scoring_it(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if not request.headers.get("Authorization"):
            return httpx.Response(401)
        if len(requests) <= 3:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"choices": [{}]} if request.url.path.startswith("/v1/") else {"text": "fixture"},
        )

    journal = tmp_path / "readiness.jsonl"
    result = smoke(
        "https://example.invalid",
        True,
        "fixture-only",
        b"audio-fixture",
        journal,
        "after_rollback",
        interval=0,
        transport=httpx.MockTransport(handler),
    )
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert all(result.values()) and len(rows) == 2
    assert rows[0]["statuses"]["chat"] == 503
    assert rows[1]["statuses"]["chat"] == 200
    assert "fixture-only" not in journal.read_text()


def test_unauthenticated_success_is_never_hidden_by_retry(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{}]})

    journal = tmp_path / "readiness.jsonl"
    with pytest.raises(RuntimeError, match="authentication"):
        smoke(
            "https://example.invalid",
            True,
            "fixture-only",
            b"fixture",
            journal,
            "initial",
            interval=0,
            transport=httpx.MockTransport(handler),
        )
    assert len(requests) == 1
    assert json.loads(journal.read_text())["statuses"]["unauthorized"] == 200
