import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    left = int(index)
    return values[left] + (values[min(left + 1, len(values) - 1)] - values[left]) * (index - left)


def summarize(points, start_time, window_seconds=120):
    groups = defaultdict(list)
    dropped = defaultdict(int)
    for point in points:
        if point.get("type") != "Point":
            continue
        seconds = (
            datetime.fromisoformat(point["data"]["time"].replace("Z", "+00:00")) - start_time
        ).total_seconds()
        window = max(0, int(seconds // window_seconds))
        if point["metric"] == "http_req_duration":
            groups[window].append(point["data"])
        elif point["metric"] == "dropped_iterations":
            dropped[window] += int(point["data"]["value"])
    output = []
    for window, rows in sorted(groups.items()):
        latencies = [r["value"] for r in rows]
        successes = sum(str(r.get("tags", {}).get("status")) == "200" for r in rows)
        output.append(
            {
                "window_start_seconds": window * window_seconds,
                "window_seconds": window_seconds,
                "requests": len(rows),
                "successes": successes,
                "p50_ms": quantile(latencies, 0.5),
                "p95_ms": quantile(latencies, 0.95),
                "successful_requests_per_second": successes / window_seconds,
                "error_rate": 1 - successes / len(rows),
                "dropped_iterations": dropped[window],
            }
        )
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--started-at", required=True, help="ISO UTC time recorded before k6 starts")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    points = [json.loads(x) for x in a.input.read_text().splitlines()]
    a.out.write_text(
        json.dumps(
            summarize(points, datetime.fromisoformat(a.started_at.replace("Z", "+00:00"))), indent=2
        )
    )
