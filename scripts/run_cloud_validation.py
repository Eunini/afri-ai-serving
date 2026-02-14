"""Finite real-model ingress load, pod-failure and HPA observation run.

Run only against the dedicated experiment cluster; credentials stay in external
files/environment. Raw HTTP bodies and authorization headers are never logged.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from loadtest.summarize import summarize


def now():
    return datetime.now(timezone.utc)


def observe(kubectl, stream, mode, phase):
    record = {"timestamp": now().isoformat(), "mode": mode, "phase": phase}
    try:
        hpas = json.loads(
            subprocess.check_output(
                [kubectl, "-n", "afri-ai", "get", "hpa", "-o", "json"],
                timeout=20,
            )
        )["items"]
        record["hpa"] = [
            {
                "name": h["metadata"]["name"],
                **{
                    k: h["status"].get(k)
                    for k in ["currentReplicas", "desiredReplicas", "currentMetrics", "conditions"]
                },
            }
            for h in hpas
        ]
        pods = json.loads(
            subprocess.check_output(
                [kubectl, "-n", "afri-ai", "get", "pods", "-o", "json"],
                timeout=20,
            )
        )["items"]
        record["pods"] = [
            {
                "name": p["metadata"]["name"],
                "uid": p["metadata"]["uid"],
                "node": p["spec"].get("nodeName"),
                "phase": p["status"]["phase"],
                "deleting": bool(p["metadata"].get("deletionTimestamp")),
                "containers": [
                    {
                        "name": c["name"],
                        "ready": c["ready"],
                        "restarts": c["restartCount"],
                        "image_id": c.get("imageID"),
                    }
                    for c in p["status"].get("containerStatuses", [])
                ],
            }
            for p in pods
        ]
    except Exception as error:
        record["observation_error"] = type(error).__name__
    stream.write(json.dumps(record) + "\n")
    stream.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--tls-ca", type=Path, required=True)
    p.add_argument("--k6-config", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--k6-binary", default="k6")
    p.add_argument("--kubectl", default="kubectl")
    p.add_argument("--cooldown-seconds", type=int, default=240)
    a = p.parse_args()
    if not os.environ.get("KUBECONFIG"):
        p.error("Select the dedicated cluster using an external KUBECONFIG")
    a.out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        API_KEY=a.key_file.read_text().strip(),
        SSL_CERT_FILE=str(a.tls_ca.absolute()),
        BASE_URL=a.base_url,
        AUDIO_FILE=str(a.audio.absolute()),
    )
    env["PATH"] = str(Path(a.kubectl).absolute().parent) + os.pathsep + env["PATH"]
    records = []
    with (a.out / "hpa-observations.jsonl").open("w") as observations:
        for mode in ["speech", "chat"]:
            env["MODE"] = mode
            started = now()
            print(f"{started.isoformat()} Starting {mode} load through TLS ingress", flush=True)
            metrics = a.out / (mode + "-load.ndjson")
            with (a.out / (mode + "-load.log")).open("w") as log:
                process = subprocess.Popen(
                    [
                        a.k6_binary,
                        "run",
                        "--quiet",
                        "--config",
                        str(a.k6_config),
                        "--out",
                        "json=" + str(metrics),
                        "loadtest/traffic.js",
                    ],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                failure = None
                failure_log = None
                clock_start = time.monotonic()
                while process.poll() is None:
                    observe(a.kubectl, observations, mode, "load")
                    elapsed = time.monotonic() - clock_start
                    if elapsed >= 360 and failure is None:
                        failure_log = (a.out / (mode + "-failure.log")).open("w")
                        failure = subprocess.Popen(
                            [
                                sys.executable,
                                "-m",
                                "loadtest.failure",
                                "--selector",
                                "app=afri-ai-" + mode,
                                "--out",
                                str(a.out / (mode + "-failure.json")),
                            ],
                            env=env,
                            stdout=failure_log,
                            stderr=subprocess.STDOUT,
                        )
                    time.sleep(10)
                if failure:
                    failure.wait(timeout=620)
                    failure_log.close()
            points = [json.loads(x) for x in metrics.read_text().splitlines()]
            result = {
                "mode": mode,
                "started_at": started.isoformat(),
                "finished_at": now().isoformat(),
                "k6_exit_code": process.returncode,
                "thresholds_passed": process.returncode == 0,
                "windows": summarize(points, started),
                "failure_exit_code": failure.returncode if failure else None,
            }
            (a.out / (mode + "-summary.json")).write_text(json.dumps(result, indent=2) + "\n")
            records.append(result)
            print(
                f"{now().isoformat()} {mode} load finished (k6={process.returncode}); observing cooldown",
                flush=True,
            )
            until = time.monotonic() + a.cooldown_seconds
            while time.monotonic() < until:
                observe(a.kubectl, observations, mode, "cooldown")
                time.sleep(10)
    (a.out / "load-summary.json").write_text(json.dumps(records, indent=2) + "\n")
    print(
        "Finite load/failure observation run finished. Preserve monitoring evidence, then terraform destroy.",
        flush=True,
    )


if __name__ == "__main__":
    main()
