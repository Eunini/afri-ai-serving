"""Measure low-load plateaus after stress testing; never hide overload errors."""

import argparse
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from loadtest.summarize import quantile
from scripts.run_cloud_validation import observe


def summarize_capacity(points, hourly_usd, mode, k6_returncode):
    results = []
    groups, dropped = defaultdict(list), defaultdict(int)
    for point in points:
        if point.get("type") != "Point":
            continue
        data = point["data"]
        tags = data.get("tags", {})
        key = tags.get("offered_rps")
        if key is None:
            scenario = re.fullmatch(r"steady_(\d+)_per_10s", tags.get("scenario", ""))
            if scenario:
                key = str(int(scenario[1]) / 10)
        if point["metric"] == "http_req_duration":
            groups[key].append(data)
        elif point["metric"] == "dropped_iterations":
            dropped[key] += int(data["value"])
    for offered, rows in sorted(groups.items()):
        good = [r["value"] for r in rows if str(r.get("tags", {}).get("status")) == "200"]
        throughput = len(good) / 120
        errors = 1 - len(good) / len(rows)
        results.append(
            {
                "mode": mode,
                "offered_requests_per_second": float(offered),
                "phase_seconds": 120,
                "requests": len(rows),
                "successes": len(good),
                "error_rate": errors,
                "dropped_iterations": dropped[offered],
                "unattributed_dropped_iterations": dropped[None],
                "successful_p50_ms": quantile(good, 0.5),
                "successful_p95_ms": quantile(good, 0.95),
                "successful_requests_per_second": throughput,
                "cluster_hourly_usd": hourly_usd,
                "cost_per_1000_successful_usd": 1000 * hourly_usd / (3600 * throughput)
                if throughput
                else None,
                "meets_error_slo": errors < 0.05 and dropped[offered] == 0 and dropped[None] == 0,
                "k6_overall_thresholds_passed": k6_returncode == 0,
                "scope": "120s arrival plateau; all responses assigned by offered-rate tag, including completions during grace period. Single short workload, not a general capacity guarantee.",
            }
        )
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--k6-binary", default="k6")
    p.add_argument("--kubectl", default="kubectl")
    p.add_argument("--hourly-usd", type=float, required=True)
    a = p.parse_args()
    env = os.environ.copy()
    env.update(
        API_KEY=(a.state_dir / "api-key").read_text().strip(),
        SSL_CERT_FILE=str(a.state_dir / "benchmark-tls.crt"),
        BASE_URL=a.base_url,
        AUDIO_FILE=str(a.audio.absolute()),
    )
    results = []
    with (a.out / "capacity-observations.jsonl").open("w") as observations:
        for mode in ["speech", "chat"]:
            env["MODE"] = mode
            print(datetime.now(timezone.utc).isoformat(), "Starting steady", mode, flush=True)
            raw = a.out / (mode + "-capacity.ndjson")
            with (a.out / (mode + "-capacity.log")).open("w") as log:
                process = subprocess.Popen(
                    [
                        a.k6_binary,
                        "run",
                        "--quiet",
                        "--config",
                        str(a.state_dir / "k6-config.json"),
                        "--out",
                        "json=" + str(raw),
                        "loadtest/capacity.js",
                    ],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                while process.poll() is None:
                    observe(a.kubectl, observations, mode, "capacity")
                    time.sleep(10)
            results.extend(
                summarize_capacity(
                    [json.loads(line) for line in raw.read_text().splitlines()],
                    a.hourly_usd,
                    mode,
                    process.returncode,
                )
            )
            (a.out / "capacity-summary.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        "Steady-load measurements saved. Preserve monitoring evidence and destroy the experiment.",
        flush=True,
    )


if __name__ == "__main__":
    main()
