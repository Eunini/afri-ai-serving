"""Export the measured dashboard series before destroying ephemeral Prometheus."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--started-at", required=True)
    p.add_argument("--endpoint", default="http://127.0.0.1:19090")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    start = datetime.fromisoformat(a.started_at.replace("Z", "+00:00")).timestamp()
    end = datetime.now(timezone.utc)
    dashboard = json.loads(Path("monitoring/grafana-dashboard.json").read_text())
    result = {
        "started_at": a.started_at,
        "finished_at": end.isoformat(),
        "step_seconds": 15,
        "panels": [],
    }
    with httpx.Client(timeout=60) as client:
        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                response = client.get(
                    a.endpoint.rstrip("/") + "/api/v1/query_range",
                    params={
                        "query": target["expr"],
                        "start": start,
                        "end": end.timestamp(),
                        "step": 15,
                    },
                )
                response.raise_for_status()
                value = response.json()
                if value.get("status") != "success":
                    raise ValueError("Prometheus query failed")
                result["panels"].append(
                    {"title": panel["title"], "query": target["expr"], "data": value["data"]}
                )
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print("Preserved", len(result["panels"]), "measured monitoring series groups.")


if __name__ == "__main__":
    main()
