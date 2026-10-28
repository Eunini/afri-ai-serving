"""Keep pending autoscaled pods distinct from failed model verification."""


def model_pod_states(pods):
    expected = {"afri-ai-speech", "afri-ai-chat"}
    records = []
    fatal = False
    for pod in pods:
        app = pod["metadata"].get("labels", {}).get("app")
        if app not in expected or pod["metadata"].get("deletionTimestamp"):
            continue
        status = pod.get("status", {})
        initializers = status.get("initContainerStatuses", [])
        exits = [c.get("state", {}).get("terminated", {}).get("exitCode") for c in initializers]
        fatal = fatal or any(code is not None and code != 0 for code in exits)
        records.append(
            {
                "pod": pod["metadata"]["name"],
                "app": app,
                "node": pod.get("spec", {}).get("nodeName"),
                "phase": status.get("phase"),
                "ready": any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions", [])
                ),
                "init_exit_codes": exits,
                "init_waiting_reasons": [
                    c.get("state", {}).get("waiting", {}).get("reason") for c in initializers
                ],
                "images": [c.get("imageID") for c in status.get("containerStatuses", [])],
            }
        )
    ready = (
        not fatal
        and {r["app"] for r in records} == expected
        and all(r["ready"] and r["init_exit_codes"] == [0] for r in records)
    )
    return records, ready, fatal
