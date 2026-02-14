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
comparisons. A rerun uses RAM-backed evidence, reserved cleanup disk space and
automatic teardown. Pending: completion/review of that comparison, integration
of the actual selected fine-tuned Project 1 model, and final report/CV claims.
