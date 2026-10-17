# Completion record

Built: Terraform VPC/subnet/security groups/EC2 instances and cloud-init k3s; speech and
chat gateways; llama.cpp image; three-image GHCR workflow; Helm deployments,
probes, requests/limits, CPU HPA, TLS ingress and NetworkPolicy; Prometheus
ServiceMonitors; Grafana dashboard; k6 load, pod-deletion recovery and cost tools.

Tests and local integration observations are recorded in `validation.json`.

Completed: real-model container integration; successful GitHub Actions builds and
GHCR publication of all three images; one-node AWS provisioning, TLS ingress,
monitoring/dashboard capture, HPA scale-up/down, stress/steady load and pod-deletion
tests, public price evidence and independently verified Terraform teardown.
The report states the tested models and bounded workload. Workspace GHCR pull
authorization returned 403, so the cluster imported the integrated local images;
registry push and cluster pull are separate observations.

One two-node attempt was interrupted by development-host disk exhaustion; its
automatic destruction was verified. It is retained separately and excluded from
comparisons. The rerun completed using RAM-backed evidence, reserved cleanup
disk space and automatic teardown. Its measurements are now on persistent
storage and both instances, disks, VPC and key registration were independently
confirmed removed, including a later recheck after EC2 expired instance records.
Two-node dashboard capture failed; all eleven Prometheus query groups were
exported and the real one-node dashboard screenshot remains available.

The actual selected fine-tuned tiny int8 model has now passed a local FastAPI
gateway check with real Yoruba audio: readiness, authentication, nonempty
transcription, duration and audio metrics. Hashes and the precise code state are
recorded in `fine-tuned-local-integration.json`. This is not a new container or
AWS deployment result. New request-budget regression tests pass. Both locked
Python runtime dependency sets passed the recorded pip-audit check; this does
not audit operating-system packages, native binaries or undisclosed issues.

Pending: final model container/cluster integration and repeated load/failure
checks, the other production sign-off gates in `production-readiness.md`, and
final report/CV claims after the cross-project measurements are complete.
