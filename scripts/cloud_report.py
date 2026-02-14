"""Publish bounded workload measurements with explicit models, SLO and teardown."""

import argparse
import csv
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--out", type=Path, default=Path("docs/cloud-report.md"))
    a = p.parse_args()
    table, selected, failures, cleanup = [], [], [], []
    for path in a.runs:
        manifest = json.loads((path / "run.json").read_text())
        capacity = json.loads((path / "capacity-summary.json").read_text())
        for row in capacity:
            table.append({"topology": manifest["topology"], **row})
        for mode in ["speech", "chat"]:
            eligible = [r for r in capacity if r["mode"] == mode and r["meets_error_slo"]]
            if eligible:
                selected.append(
                    {
                        "topology": manifest["topology"],
                        **min(eligible, key=lambda r: r["cost_per_1000_successful_usd"]),
                    }
                )
            failure = json.loads((path / (mode + "-failure.json")).read_text())
            failures.append({"topology": manifest["topology"], "mode": mode, **failure})
        teardown = (
            json.loads((path / "teardown.json").read_text())
            if (path / "teardown.json").exists()
            else {}
        )
        cleanup.append((manifest["topology"], teardown.get("destroy_verified", False)))
    lines = [
        "# AWS serving measurements",
        "",
        "Measured platform validation with pretrained faster-whisper tiny (CPU int8) and Qwen2.5-1.5B Q4_K_M. The final fine-tuned speech model is pending. These measurements do not establish Nigerian-language LLM accuracy.",
        "",
        "The speech workload repeats one real 5.76-second Yoruba recording. Chat asks for a two-sentence English explanation, capped at 64 output tokens. Each steady rate runs for 120 seconds; the client is a development VPS using TLS ingress. Full cluster compute, 30 GB/node gp3 storage and public IPv4 list prices are allocated to each isolated endpoint workload. Credits do not change list prices.",
        "",
        "## Lowest measured cost meeting the error target",
        "",
        "Eligibility requires under 5% request errors and zero dropped arrivals at that tested plateau. Small samples, Flex CPU variability, scaling transients and the single workload limit generalization. This is a measured operating point, not guaranteed production capacity.",
        "",
        "| Topology | Endpoint | Successful req/s | Successful p50 (ms) | Successful p95 (ms) | Errors | USD / 1,000 successes |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in selected:
        lines.append(
            f"| {r['topology']} | {r['mode']} | {r['successful_requests_per_second']:.3f} | {r['successful_p50_ms']:.0f} | {r['successful_p95_ms']:.0f} | {r['error_rate']:.1%} | ${r['cost_per_1000_successful_usd']:.4f} |"
        )
    if not selected:
        lines.append("| No tested plateau met the error target | — | — | — | — | — | — |")
    lines += [
        "",
        "## Recovery after pod deletion",
        "",
        "| Topology | Endpoint | Ready pods before | Replacement ready (s) | Result |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for r in failures:
        duration = (
            f"{r['recovery_seconds']:.2f}" if r["recovery_seconds"] is not None else "timeout"
        )
        lines.append(
            f"| {r['topology']} | {r['mode']} | {r['ready_before']} | {duration} | {r['status']} |"
        )
    lines += [
        "",
        "Deletion uses the configured 180-second graceful termination period. Replacement readiness is not the same as total service outage: another ready replica can continue serving. Inspect the saved HPA/pod observations and request errors. Stress tests intentionally overload the platform; their failed k6 thresholds are preserved in the run summaries.",
        "",
        "## Hardware and cleanup",
        "",
        "The AWS Free plan rejected m7i.xlarge. The eligible comparison uses one m7i-flex.large (2 vCPU/8 GiB) versus two c7i-flex.large (4 vCPU/8 GiB total). RAM is matched, CPU is not. A result cannot isolate node count from this hardware difference. A matched m7i.xlarge/two-m7i.large experiment remains separate.",
        "",
    ]
    for topology, verified in cleanup:
        lines.append(
            f"- {topology}: "
            + (
                "**Terraform destroy verified** for the known instances, boot volumes, VPC and public-key registration."
                if verified
                else "teardown verification pending."
            )
        )
    lines += [
        "",
        "The owner reports $100 of six-month credits. The scoped IAM profile cannot inspect billing; these are public list-price calculations, not a verified remaining-credit balance. See [price evidence](aws-public-prices.json) and the per-run sanitized inventories, image IDs, monitoring exports and load summaries under `docs/runs/`.",
        "",
    ]
    a.out.write_text("\n".join(lines))
    with a.out.with_suffix(".csv").open("w") as stream:
        writer = csv.DictWriter(stream, list(table[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(table)
    print("Wrote bounded workload report and all steady-rate results.")


if __name__ == "__main__":
    main()
