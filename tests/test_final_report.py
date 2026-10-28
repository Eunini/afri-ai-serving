import json

import pytest

from scripts.final_report import validated_run


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
