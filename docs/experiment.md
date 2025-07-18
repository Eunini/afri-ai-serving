# Serving experiment and cost report

## Question and method

Compare successful request throughput, median/p95 response time, error rate,
autoscaling and recovery for one larger node versus two smaller nodes. Keep total
vCPU/RAM comparable, document any unavoidable resource difference, and include
the control plane and monitoring overhead. Use the same audio distribution and
chat output budget for both topologies. Repeat each run at least three times.

The k6 schedule raises offered traffic through 1, 2, 4 and 8 requests/s, followed
by a three-minute reduction. These are ramp windows, not guaranteed steady-state
plateaus. Record dropped iterations as offered load the generator could not send.
Do not equate offered rate with delivered throughput.

## Required observations

Capture k6 NDJSON and summary, image/model hashes, CPU/memory requests and limits,
pod counts at 5-second intervals, Prometheus metrics, Grafana screenshot and
the failure-test result. Delete exactly one ready pod during load. Recovery is
the first new replacement UID becoming Ready, not the continued readiness of
another pre-existing replica. Also record user-visible error/latency impact from
the concurrent load test.

CPU HPA is a demonstration, not a guarantee of optimal scheduling for inference.
The speech service bounds concurrent work and responds 429 when busy; those
responses must count as errors in capacity reports. Chat stream duration and
post-header failures are distinct from ordinary HTTP response-header latency.

## Results

| Topology | Workload | Successful requests/s | p50 ms | p95 ms | Error rate | Recovery s | USD/1,000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| One node | Speech | Pending | Pending | Pending | Pending | Pending | Pending |
| One node | Chat | Pending | Pending | Pending | Pending | Pending | Pending |
| Two nodes | Speech | Pending | Pending | Pending | Pending | Pending | Pending |
| Two nodes | Chat | Pending | Pending | Pending | Pending | Pending | Pending |

No dashboard screenshot, autoscaling observation, cloud throughput or cloud cost
is fabricated for this table. Local integration evidence is recorded separately.

## Cost method

`cost_per_1000 = total_node_hourly_price × elapsed_seconds / 3600 / successful_requests × 1000`.
Use successful requests, including time when the cluster is idle or recovering.
Record provider, region, shapes, date, public list-price URL and promotional price
separately. For a shared speech/chat cluster, report full-cluster cost per isolated
workload or an explicit allocation; do not charge both as though each were alone
and then add them. Storage, egress and model downloads may incur additional cost.

## Limits and teardown

A two-node server/agent arrangement does not provide control-plane HA. Shared
host paths require model pre-positioning on every node. A small free-tier
allocation may be insufficient to demonstrate the full HPA maximum. Cluster
creation, scaling/failure measurements and `terraform destroy` verification need
real AWS access. At initial build no cloud resources were created.
