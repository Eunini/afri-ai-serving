from scripts.cluster_readiness import model_pod_states


def pod(app, *, ready=True, code=0):
    return {
        "metadata": {"name": app, "labels": {"app": app}},
        "spec": {"nodeName": "node"},
        "status": {
            "conditions": [{"type": "Ready", "status": str(ready)}],
            "initContainerStatuses": []
            if code is None
            else [{"state": {"terminated": {"exitCode": code}}}],
        },
    }


def test_pending_autoscaled_pod_is_waited_for_without_weakening_init_checks():
    active = [pod("afri-ai-speech"), pod("afri-ai-chat")]
    pending = pod("afri-ai-chat", ready=False, code=None)
    records, ready, fatal = model_pod_states(active + [pending])
    assert len(records) == 3 and not ready and not fatal
    assert model_pod_states(active + [pod("afri-ai-chat")])[1:] == (True, False)


def test_failed_hash_verification_is_fatal_even_with_other_ready_replicas():
    records, ready, fatal = model_pod_states(
        [pod("afri-ai-speech"), pod("afri-ai-chat"), pod("afri-ai-chat", ready=False, code=1)]
    )
    assert not ready and fatal
    assert records[-1]["init_exit_codes"] == [1]
