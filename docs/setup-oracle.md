# Setup and teardown

## Credentials and capacity

Install Terraform 1.13.4, Helm 3.19.0, kubectl matching k3s, Docker and k6. Configure
Oracle authentication in `~/.oci/config`; keep its private signing key outside the
repository. Generate a dedicated SSH key outside the repository:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/afri-ai
cp infra/terraform.tfvars.example infra/local.tfvars
```

Set home region, compartment, availability domain, an Ubuntu 24.04 ARM image,
public key path and restricted administrator IP/CIDR. Check existing tenancy
usage against the free/credited quota. A1 availability is not guaranteed. The
two-node comparison may require free credits beyond the default quota.

Use the wrapper to keep Terraform state, including the k3s join token, outside
the repository with restricted permissions:

```bash
CLOUD=oci bash scripts/terraform.sh plan -var-file=local.tfvars
CLOUD=oci bash scripts/terraform.sh apply -var-file=local.tfvars
```

Wait for cloud-init to finish on each server. The one-node topology has a single
control plane. With two nodes, the second is an agent; this is not a highly
available Kubernetes control plane. Host firewall and VCN rules restrict cluster
access. Flannel/kubelet traffic is permitted only within the private VCN.

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
load balancer; the VCN firewall still restricts access to the administrator CIDR.
Use `kubectl port-forward` for local experiments, or point the selected ingress
host at the node public IP. Terraform does not create public DNS or a TLS certificate.

## Models and authentication

Copy the Project 1 CTranslate2 artifact to `/opt/afri-models/asr` and the chosen
Project 2 GGUF file to `/opt/afri-models/llm/model.gguf` on every node. Give UID/GID
10001 read access to directories/files. Record source revision and SHA256. Do
not substitute a base model while describing it as the fine-tuned checkpoint.

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
  --namespace monitoring --create-namespace -f monitoring/values.yaml
kubectl -n monitoring create configmap afri-ai-dashboard \
  --from-file=monitoring/grafana-dashboard.json
kubectl -n monitoring label configmap afri-ai-dashboard grafana_dashboard=1
helm upgrade --install afri-ai k8s/afri-ai --namespace afri-ai \
  --set speech.image=ghcr.io/OWNER/afri-ai-serving-speech:COMMIT \
  --set chat.image=ghcr.io/OWNER/afri-ai-serving-chat:COMMIT \
  --set chat.llamaImage=ghcr.io/OWNER/afri-ai-serving-llama:COMMIT \
  --set monitoring.enabled=true
kubectl -n afri-ai rollout status deployment/afri-ai-speech --timeout=600s
kubectl -n afri-ai rollout status deployment/afri-ai-chat --timeout=600s
kubectl -n afri-ai get hpa
```

Record the installed kube-prometheus-stack chart version in the run manifest;
the application Helm chart itself has no floating chart dependencies. If GHCR
packages are private, create a registry pull secret outside git and configure
`imagePullSecrets` in the chart. For a local image smoke test, import images into
k3s/containerd and use `imagePullPolicy: Never` with local image names.

Port-forward each gateway for local measurement. Forward Grafana separately,
authenticate locally and save a dashboard screenshot only after metrics exist.
For TLS ingress, provide a TLS Secret and set `ingress.enabled`, `ingress.host`
and `ingress.tlsSecretName`; public DNS and exposure are separate prerequisites.

## Measurement and teardown

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

```bash
CLOUD=oci bash scripts/terraform.sh destroy -var-file=local.tfvars
CLOUD=oci bash scripts/terraform.sh state list
```

Save sanitized teardown evidence and verify the console resource inventory.
Terraform destroy must also remove boot volumes; if it does not, delete only
this experiment's identified resources and record the exception. Do not retain
authentication material in evidence files.
