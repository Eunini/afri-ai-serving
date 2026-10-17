import subprocess

import pytest

from scripts.smoke_containers import cleanup_verified


@pytest.mark.parametrize(
    "containers,network,expected",
    [("other-run", "", True), ("ours", "", False), ("", "our-network", False)],
)
def test_cleanup_requires_both_our_containers_and_network_to_be_absent(containers, network, expected):
    def call(*args):
        return containers if args[0] == "ps" else network

    assert cleanup_verified(call, ["ours"], "our-network") is expected


def test_unavailable_docker_does_not_count_as_verified_cleanup():
    def call(*args):
        raise subprocess.CalledProcessError(1, "docker")

    assert not cleanup_verified(call, ["ours"], "our-network")
