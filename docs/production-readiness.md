# Release readiness

Status: **not signed off for production**. The repositories and measured AWS
experiments establish a working research system. They do not establish model
quality, continuous availability or a finished four-project release.

## Completed evidence

- Authenticated model gateways, non-root containers, read-only roots, resource
  limits, private sidecar access, probes and metrics.
- GitHub container builds/publication and one-/two-node AWS load, autoscaling
  and pod-deletion experiments; known experiment resources destroyed.
- Gateway upload admission now checks authentication before consuming input,
  enforces actual byte limits even without Content-Length, times out uploads
  after 30 seconds and holds one model slot through the response/disconnect.
  Excess inference requests return 429 with Retry-After. Limits are per worker;
  the supplied image uses one worker. Chat uploads are limited to 256 KiB;
  speech to 20 MiB and 120 seconds of mono/stereo 8–48 kHz WAV/FLAC.
- Regression checks cover oversized declared and chunked bodies, auth before
  parsing, slow uploads, concurrent streams and cancellation releasing capacity.

## Gates before sign-off

| Gate | Evidence still required |
| --- | --- |
| Model suitability | Finish Project 1 compression scoring and error review. Current fine-tuned tiny has 88.76% test WER; it must not be presented as an accurate production recognizer. Publish intended-use limits and an explicit quality decision. |
| Final integration | Deploy the exact selected CT2 and GGUF artifacts; verify hashes on every node before loading, and retain the artifact/image manifest. |
| Final performance | Repeat bounded load, overload, scaling and recovery checks with the final images/models. Historical tests do not validate newly changed admission behavior. Declare workload and availability/latency targets. |
| Reproducible installation | Complete an independent clean setup using released artifacts, then an upgrade and rollback. CI registry publication is verified; authenticated cluster registry pull remains a separate unverified path. |
| Dependency and image review | Record vulnerability/license review for the final locked packages and images; investigate relevant findings before release. Passing unit tests is not a vulnerability audit. |
| Operations | Document and exercise key rotation, model/image rollback, monitoring/alert response and restore/re-provisioning. Keep credentials and Terraform state outside git. |
| Exposure | If publicly hosted, use the actual intended domain and a trusted, renewed TLS certificate. Current private/admin-CIDR tests do not verify public DNS or certificate renewal. |
| Availability and storage | State that the current k3s topology has one control-plane server, host-path models and possible downtime on single-replica rollout. Validate model distribution/restore and define the supported availability target. |
| Research release | Finish Projects 1/2 scoring, cost evidence and reports; complete Project 4 translations, reviews, model matrix and independent judge calibration. No invented results or harmful-output publication. |

## Operating scope

The original request requires experiment resources to be torn down. This remains
the default: no perpetual paid service is started by a readiness pass. A release
can be securely deployable and reproducible while its research servers remain
off. An always-on production installation needs its own operating budget,
availability target, domain and runbook; these cannot be inferred from free
research credits.

The three consent-based language review packets can proceed now. Hausa remains
pending; independent human labelling of 100 safety outputs happens after model
runs. These human judgments cannot be filled in by the implementation agent.
