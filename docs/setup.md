# AWS setup and teardown

Use the dedicated `afri-research` AWS profile, with credentials outside git.
The account owner has selected AWS free credits for this experiment. Verify
remaining credits and region-specific prices before provisioning; the code does
not assume EC2 is permanently free.

Install Terraform 1.13.4, Helm 3.19.0, kubectl matching k3s, Docker, AWS CLI and k6.
New installations pin k3s `v1.36.5+k3s1` and verify the release-tagged installer
against a recorded SHA256 before executing it. Change the version and checksum
together. This does not upgrade an existing cluster or alter historical runs,
which used `v1.33.5+k3s1`. The new default awaits a fresh cluster validation;
see [the official release notes](https://docs.k3s.io/release-notes/v1.36.X).
Credentials belong in `~/.aws/credentials` under `[afri-research]`, or use an
appropriately scoped temporary profile. Keep its session token outside the repo.
Check the intended identity without printing credentials:

```bash
aws sts get-caller-identity --profile afri-research
ssh-keygen -t ed25519 -f ~/.ssh/afri-ai
cp infra/terraform.tfvars.example infra/local.tfvars
```

Set a restricted administrator IPv4 CIDR, the intended AWS account ID, and the selected AWS region. The provider rejects a different account. The
Terraform AMI lookup uses Canonical's Ubuntu 24.04 x86_64 images. The configuration
creates a dedicated VPC, public subnet, internet route, security group, SSH public
key registration, encrypted 30-GB gp3 root volumes and one or two EC2 instances.
It creates no NAT gateway, paid cloud load balancer or Elastic IP reservation.
Public IPv4 and EBS still have prices and must be included in the cost report.
The checked public list prices are saved in `docs/aws-public-prices.json`.
Refresh them with `pip install -e '.[pricing]'` then
`python scripts/fetch_prices.py --out docs/aws-public-prices.json`.
The script streams AWS's unauthenticated public offer files; billing permissions
are not required. At the 2026-10-26 check, one m7i-flex.large with 30 GB gp3 and one
public IPv4 costs $0.1040477/hour; two c7i-flex.large nodes with the same per-node
disk and IPv4 allocation cost $0.1861553/hour. These are list-price estimates before
credits, tax and traffic. The owner reports $100 in credits valid for six months;
the scoped IAM profile cannot independently confirm the balance or expiry date.

Use the wrapper so Terraform state and the k3s join token remain outside git:

```bash
bash scripts/terraform.sh plan -var-file=local.tfvars
bash scripts/terraform.sh apply -var-file=local.tfvars
```

For a finite research experiment, set `research_lifetime_hours = 6` in the
external variable file. Cloud-final queues an asynchronous expiry timer; EC2
terminates the instance on guest shutdown. Verify `afri-cluster-expiry.timer`
is active on every node before measuring. The controller must still run
`terraform destroy`: the timer only removes compute and its boot disk, while
Terraform also removes the VPC, firewall and SSH registration. The default zero
leaves lifetime management to the operator for an ongoing deployment.

The wrapper uses `infra/` and a dedicated external AWS state directory.
The default AWS topology is one `m7i-flex.large` (2 vCPU, 8 GiB).
For a free-plan topology comparison, destroy it and run two `c7i-flex.large`
instances (2 vCPU, 4 GiB each). Record actual AMI, instance IDs, public list prices,
credit coverage and elapsed time. This matches aggregate RAM but doubles aggregate vCPU count in the two-node case.
Flex instance performance is variable; report this confound and the bounded run
window. A matched CPU/RAM one-m7i.xlarge/two-m7i.large comparison remains a
separate paid-plan experiment; the current free account rejects those shapes.

Wait for cloud-init on each server. Node 0 is the k3s server; node 1 is an agent.
The two-node arrangement does not provide control-plane high availability.
Security groups restrict SSH, HTTP/TLS and Kubernetes access to the administrator
CIDR; internal cluster traffic is allowed only among the experiment's nodes.

## Kubernetes access

Copy `/etc/rancher/k3s/k3s.yaml` over authenticated SSH into
`~/.kube/afri-ai.yaml`, mode 600. Keep it outside this repository. Create an SSH
tunnel from localhost:6443 to the server's localhost:6443, so the kubeconfig's
localhost certificate remains valid. Select that kubeconfig and check:

```bash
export KUBECONFIG="$HOME/.kube/afri-ai.yaml"
kubectl get nodes
kubectl create namespace afri-ai
```

The default k3s installation supplies metrics-server, Traefik and ServiceLB.
ServiceLB publishes Traefik on node ports 80/443 without creating a paid cloud
load balancer; the security group still restricts access to the administrator CIDR.
Use `kubectl port-forward` for local experiments, or point the selected ingress
host at the node public IP. Terraform does not create public DNS or a TLS certificate.

## Models and authentication

Copy the Project 1 CTranslate2 artifact to `/opt/afri-models/asr` and the chosen
Project 2 GGUF file to `/opt/afri-models/llm/model.gguf` on every node. Use `python scripts/stage_models.py --asr-dir /path/to/ct2 --llm-file /path/to/model.gguf --hosts NODE_IP...` before deploying. Give UID/GID
10001 read access to directories/files. Record source revision and SHA256. Do
not substitute a base model while describing it as the fine-tuned checkpoint.
The staging command verifies SHA256 on every node after transfer and writes
`model-values.json`. Pass that file to Helm. Each pod verifies these same hashes
in a read-only init container before loading its model. Empty or mismatched
`modelHashes` prevent startup; never disable verification to bypass a failed
artifact transfer. Retain the values alongside the exact image and model revisions.

Create the API key secret from an environment value without putting it in a
committed file or command output:

```bash
python - <<'PY' | kubectl -n afri-ai apply -f -
import base64, json, os
print(json.dumps({"apiVersion":"v1","kind":"Secret","metadata":{"name":"afri-ai-api"},
                  "data":{"api-key":base64.b64encode(os.environ['API_KEY'].encode()).decode()}}))
PY
```

The pipe sends the generated secret directly to kubectl; do not run the Python
part alone or save its stdout. Export `API_KEY` securely in the local shell first.

## Monitoring and deployment

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --version 92.13.1 --namespace monitoring --create-namespace -f monitoring/values.yaml
kubectl -n monitoring create configmap afri-ai-dashboard \
  --from-file=monitoring/grafana-dashboard.json
kubectl -n monitoring label configmap afri-ai-dashboard grafana_dashboard=1
helm upgrade --install afri-ai k8s/afri-ai --namespace afri-ai \
  -f k8s/values-free-plan.yaml \
  -f model-values.json \
  --set speech.image=ghcr.io/OWNER/afri-ai-serving-speech:COMMIT \
  --set chat.image=ghcr.io/OWNER/afri-ai-serving-chat:COMMIT \
  --set chat.llamaImage=ghcr.io/OWNER/afri-ai-serving-llama:COMMIT \
  --set monitoring.enabled=true
kubectl -n afri-ai rollout status deployment/afri-ai-speech --timeout=600s
kubectl -n afri-ai rollout status deployment/afri-ai-chat --timeout=600s
kubectl -n afri-ai get hpa
```

Record the installed kube-prometheus-stack chart version in the run manifest;
the application Helm chart itself has no floating chart dependencies.
The repository is public, but recorded anonymous GHCR manifest checks returned
HTTP 401 for all three images (`registry-access.json`). Package access is a
separate setting. Use a registry pull secret outside git and `imagePullSecrets`,
or build the images from this public source, import them into k3s/containerd and
use `imagePullPolicy: Never` with local names. The integration check used
source-built images; anonymous registry access has not been established.
See [GitHub's package-access documentation](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

Port-forward each gateway for local measurement. Forward Grafana separately,
authenticate locally and save a dashboard screenshot only after metrics exist.
For TLS ingress, provide a TLS Secret and set `ingress.enabled`, `ingress.host`
and `ingress.tlsSecretName`; public DNS and exposure are separate prerequisites.

## Measurement and teardown

For the final-artifact fresh-cluster validation, `scripts.validate_cluster`
checks the integrated local image IDs, gateway source hashes and model hashes,
then provisions a new dedicated Terraform state. It streams the source-built
images into each node, verifies imported identities, stages/hashes models,
installs monitoring and the application, checks real TLS requests, upgrades and
rolls back the chart, and runs the existing bounded load/failure/capacity tests.
It exports monitoring before destroying its own resources and checking teardown.
The new controller still awaits its first completed cloud run.

The hardened profile checks DNS and blocked public TCP egress from the actual
model pods against unselected controls on the same nodes. Traefik and Prometheus
are the admitted namespace/pod peers; change `monitoring.namespace` if installing
monitoring elsewhere. Models are mounted locally, so their pods need no internet
download. The speech API accepts integer PCM WAV or FLAC; compressed and float
WAV are rejected before native parsing. Runtime images retain project/upstream
notices; vulnerability and license findings still require review.

For dashboard capture, install `playwright-cli` and its headless browser on the
operator host. The optional capture logs in through private localhost forwarding,
keeps temporary browser authentication outside Git, scrolls lazy panels into view
and closes its own session. Capture failure is recorded while measured Prometheus
exports remain available. `scripts.final_report` only reports matching final-model
runs after completed measurements, policy checks and independently verified
teardown; it preserves all capacity rows and states the 5% error/30-second p95
eligibility targets.

Use kubectl **v1.36.5** in the supplied tools directory, alongside Terraform,
Helm and k6. Build/tag the three images as `afri-research-{speech,chat,llama}:local`
and repeat real-model integration/image review first if their IDs or gateway
sources differ from `fine-tuned-container-integration.json`. Supply actual local
artifact paths and refreshed prices:

```bash
python -m scripts.validate_cluster \
  --out docs/runs/final-one-node-YYYYMMDD \
  --state-dir "$HOME/.local/state/afri-ai-serving/final-one-node-YYYYMMDD" \
  --tools-dir /absolute/tools-with-kubectl-1.36.5 \
  --asr-dir /absolute/selected-tiny-ct2-int8 \
  --llm-file /absolute/qwen-q4.gguf --audio /absolute/test.wav \
  --prices docs/aws-public-prices.json --account-id YOUR_ACCOUNT_ID \
  --nodes 1 --max-hours 4 --budget-usd 1
```

The state directory contains credentials/configuration and must stay outside
Git; its command logs are private. Public evidence is limited to selected run
metadata, model/image IDs, measurements and teardown checks. Local forwarding
uses ports 36443, 34443 and 29090 and refuses occupied ports. TLS uses a temporary
private research certificate for localhost, trusted explicitly by the clients;
this does not establish public-domain certificate renewal. Guest expiry and
controller teardown are independent safeguards. A new run needs empty dedicated
state and a fresh evidence directory. The controller never imports registry
credentials or queries billing.

Initial/post-rollback serving probes have a bounded readiness window, with every
attempt/status retained separately in `smoke-attempts.jsonl`. Temporary ingress
unavailability is not a load-test sample. Authentication/response-contract
failures are fatal and cannot be hidden by a successful retry. These probes do
not establish zero-downtime rollback. Secret creation output is discarded to keep
secret-bearing error payloads out of command logs.

```bash
export BASE_URL=http://127.0.0.1:8000
k6 run --out json=docs/chat-load.ndjson loadtest/traffic.js
python -m loadtest.failure --namespace afri-ai --selector app=afri-ai-chat
# Run the failure command while the load test is active in another terminal.
```

For speech, set `MODE=speech`, `AUDIO_FILE` to a representative real recording,
and forward the speech gateway. Record the UTC start timestamp, workload/audio
length, HPA replica observations before/during/after load, model hashes and
actual chart/image versions. `loadtest.summarize` produces time-window statistics.

The measured protocol uses `scripts.run_cloud_validation` for stress, HPA and
pod deletion, then `scripts.run_capacity` for 0.1/0.2/0.5-request/s steady
plateaus. `scripts.complete_cloud_run --help` wraps those stages, monitoring
export and unconditional Terraform teardown for a recorded instance inventory.
Use a scratch directory with at least 256 MiB available and keep Terraform state
on persistent private storage. RAM-backed evidence can be archived after cleanup
with `python -m scripts.preserve_cloud_run --source SCRATCH_RUN --archive RUN.tar.gz
--wait-seconds 7200`. Extract the archive before reanalysing raw JSON/NDJSON files.

```bash
bash scripts/terraform.sh destroy -var-file=local.tfvars
bash scripts/terraform.sh state list
```

Save sanitized teardown evidence and verify the console resource inventory.
Terraform destroy must also remove boot volumes; if it does not, delete only
this experiment's identified resources and record the exception. Do not retain
authentication material in evidence files.
