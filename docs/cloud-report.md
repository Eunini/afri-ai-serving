# AWS serving measurements

Measured platform validation with pretrained faster-whisper tiny (CPU int8) and Qwen2.5-1.5B Q4_K_M. The final fine-tuned speech model is pending. These measurements do not establish Nigerian-language LLM accuracy.

The speech workload repeats one real 5.76-second Yoruba recording. Chat asks for a two-sentence English explanation, capped at 64 output tokens. Each steady rate runs for 120 seconds; the client is a development VPS using TLS ingress. Full cluster compute, 30 GB/node gp3 storage and public IPv4 list prices are allocated to each isolated endpoint workload. Credits do not change list prices.

## Lowest measured cost meeting the error target

Eligibility requires under 5% request errors and zero dropped arrivals at that tested plateau. Small samples, Flex CPU variability, scaling transients and the single workload limit generalization. This is a measured operating point, not guaranteed production capacity.

| Topology | Endpoint | Successful req/s | Successful p50 (ms) | Successful p95 (ms) | Errors | USD / 1,000 successes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1xm7i-flex.large | speech | 0.208 | 2521 | 3592 | 0.0% | $0.1387 |
| 1xm7i-flex.large | chat | 0.108 | 2632 | 7262 | 0.0% | $0.2668 |

## Recovery after pod deletion

| Topology | Endpoint | Ready pods before | Replacement ready (s) | Result |
| --- | --- | ---: | ---: | --- |
| 1xm7i-flex.large | speech | 2 | 7.39 | recovered |
| 1xm7i-flex.large | chat | 2 | 187.67 | recovered |

Deletion uses the configured 180-second graceful termination period. Replacement readiness is not the same as total service outage: another ready replica can continue serving. Inspect the saved HPA/pod observations and request errors. Stress tests intentionally overload the platform; their failed k6 thresholds are preserved in the run summaries.

## Hardware and cleanup

The AWS Free plan rejected m7i.xlarge. The eligible comparison uses one m7i-flex.large (2 vCPU/8 GiB) versus two c7i-flex.large (4 vCPU/8 GiB total). RAM is matched, CPU is not. A result cannot isolate node count from this hardware difference. A matched m7i.xlarge/two-m7i.large experiment remains separate.

- 1xm7i-flex.large: **Terraform destroy verified** for the known instances, boot volumes, VPC and public-key registration.

The owner reports $100 of six-month credits. The scoped IAM profile cannot inspect billing; these are public list-price calculations, not a verified remaining-credit balance. See [price evidence](aws-public-prices.json) and the per-run sanitized inventories, image IDs, monitoring exports and load summaries under `docs/runs/`.
