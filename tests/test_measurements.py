from datetime import datetime, timezone

import pytest

from loadtest.cost import cost_per_1000
from loadtest.summarize import summarize


def test_cost_uses_successful_throughput():
    assert cost_per_1000(0.1, 100, 3600) == 1
    with pytest.raises(ValueError):
        cost_per_1000(0.1, 0, 1)


def test_loadtest_windows_preserve_errors():
    start = datetime(2026, 10, 25, tzinfo=timezone.utc)
    points = [
        {
            "type": "Point",
            "metric": "http_req_duration",
            "data": {"time": "2026-10-25T00:00:10Z", "value": value, "tags": {"status": status}},
        }
        for value, status in [(100, "200"), (200, "500")]
    ]
    result = summarize(points, start)[0]
    assert result["p50_ms"] == 150
    assert result["error_rate"] == 0.5
    assert result["successful_requests_per_second"] == 1 / 120
