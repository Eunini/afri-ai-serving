"""Delete exactly one selected pod and record recovery while an independent load runs."""

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def kubectl(*args):
    return subprocess.check_output(["kubectl", *args], text=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--namespace", default="afri-ai")
    p.add_argument("--selector", required=True)
    p.add_argument("--out", type=Path, default=Path("docs/failure-result.json"))
    a = p.parse_args()
    pods = json.loads(kubectl("-n", a.namespace, "get", "pods", "-l", a.selector, "-o", "json"))[
        "items"
    ]
    ready = [
        x
        for x in pods
        if any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in x["status"].get("conditions", [])
        )
    ]
    if not ready:
        raise RuntimeError("No ready pod to delete")
    pod = ready[0]["metadata"]["name"]
    original_uids = {x["metadata"]["uid"] for x in pods}
    start = time.monotonic()
    kubectl("-n", a.namespace, "delete", "pod", pod, "--wait=false")
    result = {
        "deleted_pod": pod,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ready_before": len(ready),
        "status": "timeout",
        "recovery_seconds": None,
    }
    while time.monotonic() - start < 600:
        current = json.loads(
            kubectl("-n", a.namespace, "get", "pods", "-l", a.selector, "-o", "json")
        )["items"]
        replacements = [
            x
            for x in current
            if x["metadata"]["uid"] not in original_uids
            and any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in x["status"].get("conditions", [])
            )
        ]
        if replacements:
            result.update(
                status="recovered",
                recovery_seconds=time.monotonic() - start,
                replacement_pod=replacements[0]["metadata"]["name"],
            )
            break
        time.sleep(1)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2))
    if result["status"] != "recovered":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
