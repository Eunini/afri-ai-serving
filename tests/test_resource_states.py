import pytest

from scripts.resource_states import instance_gone


@pytest.mark.parametrize(
    "states,expected",
    [([], True), (["terminated"], True), (["running"], False), (["terminated", "stopped"], False)],
)
def test_teardown_accepts_expired_records_but_never_live_or_stopped_instances(states, expected):
    reservations = [{"Instances": [{"State": {"Name": state}} for state in states]}]
    assert instance_gone(reservations) is expected
