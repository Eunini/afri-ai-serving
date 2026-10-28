from datetime import datetime, timedelta, timezone

import pytest

from scripts.validate_cluster import bounded_price, empty_state


def prices(age=0):
    return {
        "checked_at": (datetime.now(timezone.utc) - timedelta(hours=age)).isoformat(),
        "region": "us-east-1",
        "topologies": {
            "1xm7i-flex.large": {"cluster_usd_per_hour": 0.104},
            "2xc7i-flex.large": {"cluster_usd_per_hour": 0.186},
        },
    }


def test_cluster_budget_counts_both_nodes_and_rejects_stale_or_unbounded_runs():
    assert bounded_price(prices(), 2, 4, 1) == ("2xc7i-flex.large", 0.186)
    for data, nodes, hours, budget in [
        (prices(), 2, 8, 1),
        (prices(49), 1, 4, 1),
        (prices(), 1, 0, 1),
        (prices(), 1, float("nan"), 1),
        (prices(), 1, 4, float("nan")),
        (prices(), 3, 4, 1),
    ]:
        with pytest.raises(ValueError):
            bounded_price(data, nodes, hours, budget)


def test_cleanup_guard_distinguishes_managed_resources_from_retained_data_sources(tmp_path):
    state = tmp_path / "state.json"
    assert empty_state(state)
    state.write_text('{"resources":[{"mode":"data"}]}')
    assert empty_state(state)
    state.write_text('{"resources":[{"mode":"managed"}]}')
    assert not empty_state(state)
