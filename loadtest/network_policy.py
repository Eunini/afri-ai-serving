"""Compare protected pods with an unselected control on each same cluster node."""

import argparse
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


PROBE = """import json,socket
result={'dns_ok':False,'public_tcp_connected':False}
try:
    result['dns_ok']=bool(socket.getaddrinfo('example.com',443))
except OSError:
    pass
try:
    with socket.create_connection(('1.1.1.1',443),timeout=3):
        result['public_tcp_connected']=True
except OSError:
    pass
print(json.dumps(result))
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    base = [args.kubectl, "-n", "afri-ai"]
    created = []
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "controls": {},
        "protected_pods": [],
        "scope": "DNS and one public TCP endpoint only; same-node unselected controls. Does not prove universal egress isolation or prevent DNS exfiltration.",
        "passed": False,
    }

    def command(extra, *, body=None, timeout=90):
        return subprocess.check_output(base + extra, input=body, timeout=timeout)

    try:
        pods = json.loads(command(["get", "pods", "-o", "json"]))["items"]
        selected = [
            p
            for p in pods
            if p["metadata"].get("labels", {}).get("app") in {"afri-ai-speech", "afri-ai-chat"}
            and not p["metadata"].get("deletionTimestamp")
            and any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in p["status"].get("conditions", [])
            )
        ]
        if {p["metadata"]["labels"]["app"] for p in selected} != {"afri-ai-speech", "afri-ai-chat"}:
            raise ValueError("Both model services must have ready pods before policy checks")
        for node in sorted({p["spec"]["nodeName"] for p in selected}):
            name = "afri-network-control-" + uuid.uuid4().hex[:8]
            job = {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {"name": name},
                "spec": {
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": 60,
                    "ttlSecondsAfterFinished": 120,
                    "template": {
                        "metadata": {"labels": {"app": "afri-network-control"}},
                        "spec": {
                            "nodeName": node,
                            "restartPolicy": "Never",
                            "automountServiceAccountToken": False,
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 10001,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [
                                {
                                    "name": "probe",
                                    "image": args.image,
                                    "imagePullPolicy": "Never",
                                    "command": ["python", "-c", PROBE],
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "50m", "memory": "32Mi"},
                                        "limits": {"cpu": "250m", "memory": "64Mi"},
                                    },
                                }
                            ],
                        },
                    },
                },
            }
            command(["apply", "-f", "-"], body=json.dumps(job).encode())
            created.append(name)
            command(["wait", "--for=condition=Complete", "job/" + name, "--timeout=75s"])
            control = json.loads(command(["logs", "job/" + name]))
            result["controls"][node] = control
            if not control["dns_ok"] or not control["public_tcp_connected"]:
                raise ValueError("Same-node control cannot establish baseline network reachability")
        for pod in selected:
            observation = json.loads(
                command(
                    ["exec", pod["metadata"]["name"], "-c", "gateway", "--", "python", "-c", PROBE],
                    timeout=30,
                )
            )
            result["protected_pods"].append(
                {"pod": pod["metadata"]["name"], "node": pod["spec"]["nodeName"], **observation}
            )
            if not observation["dns_ok"] or observation["public_tcp_connected"]:
                raise ValueError("Protected pod DNS/public-egress result violates the policy")
        result["passed"] = True
    finally:
        for name in created:
            command(["delete", "job", name, "--wait=true", "--timeout=30s"], timeout=40)
        result["temporary_control_jobs_removed"] = True
        args.out.write_text(json.dumps(result, indent=2) + "\n")
    print("Model-pod policy check passed; temporary controls removed.")


if __name__ == "__main__":
    main()
