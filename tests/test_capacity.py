from scripts.run_capacity import summarize_capacity


def test_executor_dropped_arrivals_disqualify_successful_http_plateau():
    points = [
        {
            "type": "Point",
            "metric": "http_req_duration",
            "data": {
                "value": 100,
                "tags": {"offered_rps": "0.5", "scenario": "steady_5_per_10s", "status": "200"},
            },
        },
        {
            "type": "Point",
            "metric": "dropped_iterations",
            "data": {"value": 3, "tags": {"scenario": "steady_5_per_10s"}},
        },
    ]
    row = summarize_capacity(points, 0.1, "chat", 0)[0]
    assert row["error_rate"] == 0
    assert row["dropped_iterations"] == 3
    assert not row["meets_error_slo"]
