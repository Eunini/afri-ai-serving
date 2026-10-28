import json

import pytest

from scripts.final_report import main, validated_run


def test_no_final_report_from_live_incomplete_or_unverified_run(tmp_path):
    data = {
        "run": {"source_commit": "fixed"},
        "controller": {"status": "measurements_complete", "managed_state_empty": True},
        "teardown": {"destroy_verified": True},
        "network-policy-verification": {"passed": True},
    }
    for name, value in data.items():
        (tmp_path / (name + ".json")).write_text(json.dumps(value))
    assert validated_run(tmp_path) == {"source_commit": "fixed"}
    (tmp_path / "teardown.json").write_text('{"destroy_verified":false}')
    with pytest.raises(ValueError, match="verified teardown"):
        validated_run(tmp_path)


def test_cheapest_point_must_meet_both_latency_and_error_targets(tmp_path, monkeypatch):
    run = tmp_path / "one-node"
    run.mkdir()
    documents = {
        "run": {
            "source_commit": "fixed",
            "models": {},
            "images": {},
            "topology": "one-node",
            "hourly_usd": 1,
            "speech_workload": {"audio_seconds": 5.76, "sha256": "a" * 64},
            "chat_workload": {"max_tokens": 64},
        },
        "controller": {"status": "measurements_complete", "managed_state_empty": True},
        "teardown": {"destroy_verified": True},
        "network-policy-verification": {"passed": True},
    }
    rows = []
    for mode in ["speech", "chat"]:
        documents[mode + "-failure"] = {
            "recovery_seconds": 5,
            "ready_before": 2,
            "status": "recovered",
        }
        for rate, errors, p95 in [(0.1, 0, 500), (0.2, 0.2, 400), (0.5, 0, 31000)]:
            rows.append(
                {
                    "mode": mode,
                    "cluster_hourly_usd": 1,
                    "successful_requests_per_second": rate,
                    "cost_per_1000_successful_usd": 1000 / (3600 * rate),
                    "successful_p50_ms": 100,
                    "successful_p95_ms": p95,
                    "meets_error_slo": errors < 0.05,
                    "successes": int(120 * rate),
                    "requests": int(120 * rate),
                    "error_rate": errors,
                }
            )
    documents["capacity-summary"] = rows
    for name, data in documents.items():
        (run / (name + ".json")).write_text(json.dumps(data))
    report = tmp_path / "report.md"
    monkeypatch.setattr("sys.argv", ["report", str(run), "--out", str(report)])
    main()
    result = json.loads(report.with_suffix(".json").read_text())
    assert len(result["all_capacity_rows"]) == 6
    assert len(result["selected_operating_points"]) == 2
    assert all(
        r["successful_requests_per_second"] == 0.1 for r in result["selected_operating_points"]
    )
    assert result["production_signed_off"] is False
