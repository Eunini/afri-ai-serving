"""Report matching final-model runs only after verified teardown."""

import argparse
import csv
import json
import math
from pathlib import Path


def validated_run(path):
    data = {
        name: json.loads((path / (name + ".json")).read_text())
        for name in ["run", "controller", "teardown", "network-policy-verification"]
    }
    if (
        data["controller"].get("status") != "measurements_complete"
        or not data["controller"].get("managed_state_empty")
        or not data["teardown"].get("destroy_verified")
        or not data["network-policy-verification"].get("passed")
    ):
        raise ValueError("Require complete measurements, policy checks and verified teardown")
    return data["run"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifests = [validated_run(path) for path in args.runs]
    reference = manifests[0]
    if any(
        any(
            m[key] != reference[key]
            for key in ["source_commit", "models", "images", "speech_workload", "chat_workload"]
        )
        for m in manifests
    ):
        raise ValueError("Do not compare different final source, images or model artifacts")
    rows, selected, recoveries = [], [], []
    for path, manifest in zip(args.runs, manifests):
        capacity = json.loads((path / "capacity-summary.json").read_text())
        if len(capacity) != 6 or {r["mode"] for r in capacity} != {"speech", "chat"}:
            raise ValueError("Require all three capacity plateaus for both endpoints")
        for row in capacity:
            if row["cluster_hourly_usd"] != manifest["hourly_usd"]:
                raise ValueError("Capacity cost uses a different hourly price")
            rate, cost = row["successful_requests_per_second"], row["cost_per_1000_successful_usd"]
            if rate and not math.isclose(
                cost, 1000 * manifest["hourly_usd"] / (3600 * rate), rel_tol=1e-10
            ):
                raise ValueError("Recorded cost does not reproduce from measured throughput")
            latency_ok = row["successful_p95_ms"] is not None and row["successful_p95_ms"] <= 30000
            rows.append(
                {
                    "topology": manifest["topology"],
                    **row,
                    "meets_30s_latency_target": latency_ok,
                    "eligible_operating_point": row["meets_error_slo"] and latency_ok,
                }
            )
        for mode in ["speech", "chat"]:
            eligible = [
                r
                for r in rows
                if r["topology"] == manifest["topology"]
                and r["mode"] == mode
                and r["eligible_operating_point"]
            ]
            if eligible:
                selected.append(min(eligible, key=lambda r: r["cost_per_1000_successful_usd"]))
            failure = json.loads((path / (mode + "-failure.json")).read_text())
            recoveries.append({"topology": manifest["topology"], "mode": mode, **failure})
    lines = [
        "# Selected-model AWS serving validation",
        "",
        "Measured research deployment; **production sign-off remains pending**. The selected WAXAL fine-tuned tiny int8 and Qwen2.5-1.5B Q4 models are identified by exact hashes in each run. The ASR checkpoint has 88.76% full-test WER in Project 1; serving success does not establish transcription accuracy.",
        "",
        "Both topologies use the same source, images and weights. The final gateway admits canonical integer PCM WAV before native parsing. Model init hashes, restricted pod networking with same-node controls, real TLS requests, chart upgrade/rollback, load, failure and teardown are recorded. The private localhost certificate does not establish public-domain TLS renewal.",
        "",
        f"The workload repeats one real {reference['speech_workload']['audio_seconds']:.3f}-second Yoruba recording (SHA256 `{reference['speech_workload']['sha256']}`) and, separately, one English two-sentence explanation capped at {reference['chat_workload']['max_tokens']} tokens. Each arrival plateau lasts 120 seconds. This is a short workload sample, not a general capacity or Nigerian-language LLM accuracy claim.",
        "",
        "## Lowest measured cost meeting the stated targets",
        "",
        "Eligibility requires less than 5% errors, zero dropped arrivals, and successful-response sample p95 at most 30 seconds. All plateaus remain in the accompanying CSV. Stress overload failures and fast 429 responses are retained separately; they cannot count as successful inference throughput.",
        "",
        "| Topology | Endpoint | Successes / requests | Successful req/s | Successful p50 ms | Successful p95 ms | Errors | USD / 1,000 successes |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in selected:
        lines.append(
            f"| {row['topology']} | {row['mode']} | {row['successes']} / {row['requests']} | {row['successful_requests_per_second']:.3f} | {row['successful_p50_ms']:.0f} | {row['successful_p95_ms']:.0f} | {row['error_rate']:.1%} | ${row['cost_per_1000_successful_usd']:.4f} |"
        )
    if not selected:
        lines.append("| No tested operating point meets all targets | — | — | — | — | — | — | — |")
    lines += [
        "",
        "Costs allocate the full cluster compute, 30-GB/node gp3 storage and public IPv4 list price to each isolated endpoint workload: `1000 × hourly USD / (3600 × successful req/s)`. Credits do not change list prices. Tax, traffic, setup/idle time, cold starts and mixed-workload amortization are separate; this is not an account billing statement.",
        "",
        "## Pod replacement",
        "",
        "| Topology | Endpoint | Ready pods before deletion | Replacement ready seconds | Result |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in recoveries:
        duration = (
            f"{row['recovery_seconds']:.2f}" if row["recovery_seconds"] is not None else "timeout"
        )
        lines.append(
            f"| {row['topology']} | {row['mode']} | {row['ready_before']} | {duration} | {row['status']} |"
        )
    lines += [
        "",
        "Deletion uses the configured graceful termination period. Replacement readiness differs from total outage when another replica continues serving. Saved request, HPA and pod observations establish what occurred; no outage duration is invented.",
        "",
        "## Evidence and limits",
        "",
    ]
    for path, manifest in zip(args.runs, manifests):
        relative = "runs/" + path.name
        lines.append(
            f"- [{manifest['topology']} run manifest]({relative}/run.json), [policy checks]({relative}/network-policy-verification.json), [monitoring export]({relative}/monitoring-series.json), [verified teardown]({relative}/teardown.json)."
        )
        if (path / "dashboard-final.png").exists():
            lines += [
                "",
                f"![Measured {manifest['topology']} dashboard]({relative}/dashboard-final.png)",
                "",
            ]
    lines += [
        "",
        "One m7i-flex.large has 2 vCPU/8 GiB; two c7i-flex.large nodes have 4 vCPU/8 GiB total. RAM is matched, CPU is not, and Flex performance varies. This comparison cannot isolate node count. Both arrangements have a single control plane and host-path models; no control-plane HA or general availability guarantee is established.",
        "",
        "The client is a shared development host using administrator-only ingress and SSH forwarding. Application deadlines, concurrency admission and autoscaling affect these measurements. Streaming-only dashboard panels can be empty for the nonstreaming workload.",
        "",
        "OS vulnerability and license findings remain recorded in [the security review](security/review-20261028.md). Model quality, broader workloads, operational restoration/key rotation, trusted public TLS and research/human review remain separate release gates. All known resources for these experiments were destroyed and independently checked.",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    with args.out.with_suffix(".csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    args.out.with_suffix(".json").write_text(
        json.dumps(
            {
                "source_commit": reference["source_commit"],
                "selected_operating_points": selected,
                "all_capacity_rows": rows,
                "recovery": recoveries,
                "production_signed_off": False,
            },
            indent=2,
        )
        + "\n"
    )
    print("Final-model report written from matching complete runs with verified teardown.")


if __name__ == "__main__":
    main()
