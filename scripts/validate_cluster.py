"""Provision a finite, isolated real-model validation and destroy its own state.

Credentials, kubeconfig, TLS private key and command logs remain outside Git.
The public run directory receives only explicitly selected, sanitized evidence.
This is an administrator-only research deployment, not an always-on service.
"""

import argparse
import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import secrets
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def empty_state(path):
    return not path.exists() or not any(
        r.get("mode", "managed") == "managed"
        for r in json.loads(path.read_text()).get("resources", [])
    )


def bounded_price(prices, nodes, hours, budget):
    age = (
        datetime.now(timezone.utc) - datetime.fromisoformat(prices["checked_at"])
    ).total_seconds()
    if (
        nodes not in (1, 2)
        or not 1 <= hours <= 8
        or prices["region"] != "us-east-1"
        or not 0 <= age <= 172800
    ):
        raise ValueError("Require one/two nodes, 1–8 hours and fresh us-east-1 prices")
    topology = "1xm7i-flex.large" if nodes == 1 else "2xc7i-flex.large"
    hourly = prices["topologies"][topology]["cluster_usd_per_hour"]
    if not 0 < hourly * hours <= budget:
        raise ValueError("Compute/storage/IPv4 budget exceeded")
    return topology, hourly


def main():
    import boto3
    import httpx

    from services.artifacts import manifests
    from scripts.image_identity import verify_imported_image
    from scripts.cluster_readiness import model_pod_states

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--provider-cache", type=Path)
    parser.add_argument("--asr-dir", type=Path, required=True)
    parser.add_argument("--llm-file", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--nodes", type=int, choices=[1, 2], default=1)
    parser.add_argument("--max-hours", type=float, default=4)
    parser.add_argument("--budget-usd", type=float, default=1)
    parser.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/afri-ai")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.out = args.out.resolve()
    args.state_dir = args.state_dir.resolve()
    args.tools_dir = args.tools_dir.resolve(strict=True)
    if not args.out.is_relative_to(root / "docs/runs") or args.state_dir.is_relative_to(root):
        parser.error(
            "Keep sanitized evidence in docs/runs and private state outside the repository"
        )
    for name in ("asr_dir", "llm_file", "audio", "prices", "ssh_key"):
        setattr(args, name, getattr(args, name).expanduser().resolve(strict=True))
    prices = json.loads(args.prices.read_text())
    topology, hourly = bounded_price(prices, args.nodes, args.max_hours, args.budget_usd)
    proof = json.loads((root / "docs/fine-tuned-container-integration.json").read_text())
    models = manifests(args.asr_dir, args.llm_file)
    if models["speech"]["modelHashes"] != proof["model_hashes"]["asr"] or models["chat"][
        "modelHashes"
    ] != {"model.gguf": proof["model_hashes"]["llm"]}:
        raise ValueError("Model bytes differ from the real-model integration evidence")
    for name, digest in proof["source_files_sha256"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Gateway source changed; repeat image integration first")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "infra",
            "scripts",
            "services",
            "k8s",
            "monitoring",
            "loadtest",
        ],
        cwd=root,
        text=True,
    ).strip():
        raise ValueError("Commit validation sources before provisioning")
    session = boto3.Session(profile_name="afri-research", region_name="us-east-1")
    if session.client("sts").get_caller_identity()["Account"] != args.account_id:
        raise ValueError("Unexpected AWS account")
    os.umask(0o077)
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (args.state_dir / "controller.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = args.state_dir / "terraform.tfstate"
    if not empty_state(state) or (args.out / "controller.json").exists():
        raise ValueError("Use empty dedicated state and a new evidence directory")
    args.out.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.state_dir).free < 512 * 1024**2:
        raise RuntimeError("Insufficient private scratch space for validation and cleanup")
    reserve = args.state_dir / "cleanup-reserve.bin"
    with reserve.open("wb") as stream:
        os.posix_fallocate(stream.fileno(), 0, 32 * 1024**2)
    receipt = {
        "started_at": now(),
        "source_commit": revision,
        "status": "preflight",
        "topology": topology,
        "max_hours": args.max_hours,
        "hourly_usd": hourly,
        "maximum_compute_storage_ipv4_usd": hourly * args.max_hours,
        "cost_exclusions": "Tax and traffic; remaining credits not independently accessible",
        "stages": [],
    }
    env = {
        **os.environ,
        "TF_DATA_DIR": str(args.state_dir / "terraform"),
        "TF_IN_AUTOMATION": "1",
        "KUBECONFIG": str(args.state_dir / "kubeconfig"),
        "PATH": str(args.tools_dir) + os.pathsep + os.environ["PATH"],
    }
    deadline = time.monotonic() + args.max_hours * 3600
    children, applied, inventory = [], False, None
    tf = [str(args.tools_dir / "terraform"), "-chdir=" + str(root / "infra")]
    kubectl = [str(args.tools_dir / "kubectl")]
    helm = [str(args.tools_dir / "helm")]
    varfile = args.state_dir / "research.tfvars.json"

    def save():
        write(args.out / "controller.json", receipt)

    def stop(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                process.wait(timeout=10)
                return
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)

    def run(name, command, timeout=600, *, data=None, capture=False, check=True, cleanup=False):
        if not cleanup and time.monotonic() + 5 >= deadline:
            raise TimeoutError("Finite validation deadline reached")
        with (args.state_dir / (name + ".log")).open("ab") as log:
            proc = subprocess.Popen(
                command,
                cwd=root,
                env=env,
                start_new_session=True,
                stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture else log,
                stderr=log,
            )
            children.append(proc)
            try:
                stdout, _ = proc.communicate(
                    data,
                    timeout=timeout
                    if cleanup
                    else min(timeout, max(1, deadline - time.monotonic())),
                )
            except BaseException:
                stop(proc)
                raise
        receipt["stages"].append({"name": name, "at": now(), "exit_code": proc.returncode})
        save()
        if check and proc.returncode:
            raise RuntimeError("Validation stage failed: " + name)
        return stdout if capture else proc.returncode

    ssh = [
        "ssh",
        "-i",
        str(args.ssh_key),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=" + str(args.state_dir / "known_hosts"),
    ]

    def remote(host, command, **kwargs):
        return run("remote", ssh + ["ubuntu@" + host, command], **kwargs)

    def outputs():
        values = json.loads(
            run("terraform-output", tf + ["output", "-json"], capture=True, cleanup=True)
        )
        return {k: v["value"] for k, v in values.items()}

    def interrupt(*_):
        raise SystemExit("Validation interrupted; cleaning owned resources")

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        client = json.loads(
            run("kubectl-version", kubectl + ["version", "--client", "-o", "json"], capture=True)
        )
        if client["clientVersion"]["gitVersion"] != "v1.36.5":
            raise ValueError("Use kubectl v1.36.5 for the pinned fresh-cluster validation")
        receipt["kubectl_version"] = client["clientVersion"]["gitVersion"]
        images = {}
        for service in ("speech", "chat", "llama"):
            tag = f"afri-research-{service}:local"
            found = json.loads(
                run(
                    "image-inspect-" + service,
                    ["sudo", "-n", "docker", "image", "inspect", tag],
                    capture=True,
                )
            )[0]["Id"]
            if found != proof["images"][service]:
                raise ValueError("Local image differs from integrated/scanned image: " + service)
            images[service] = {"tag": "docker.io/library/" + tag, "id": found}
        request = urllib.request.Request(
            "https://checkip.amazonaws.com", headers={"User-Agent": "afri-ai-validation"}
        )
        admin = str(
            ipaddress.IPv4Address(
                urllib.request.urlopen(request, timeout=15).read().decode().strip()
            )
        )
        write(
            varfile,
            {
                "aws_account_id": args.account_id,
                "admin_cidr": admin + "/32",
                "node_count": args.nodes,
                "instance_type": "m7i-flex.large" if args.nodes == 1 else "c7i-flex.large",
                "ssh_public_key_path": str(args.ssh_key) + ".pub",
                "research_lifetime_hours": args.max_hours,
            },
        )
        init = tf + [
            "init",
            "-input=false",
            "-reconfigure",
            "-no-color",
            "-backend-config=path=" + str(state),
        ]
        if args.provider_cache:
            init.append("-plugin-dir=" + str(args.provider_cache.resolve(strict=True)))
        run("terraform-init", init)
        applied = True
        run(
            "terraform-apply",
            tf
            + ["apply", "-auto-approve", "-input=false", "-no-color", "-var-file=" + str(varfile)],
            timeout=900,
        )
        values = outputs()
        ids, hosts = values["instance_ids"], values["public_ips"]
        ec2 = session.client("ec2")
        instances = [
            i
            for r in ec2.describe_instances(InstanceIds=ids)["Reservations"]
            for i in r["Instances"]
        ]
        if len(instances) != args.nodes or any(
            i["Tags"] is None
            or {t["Key"]: t["Value"] for t in i["Tags"]}.get("Project") != "afri-ai-research"
            for i in instances
        ):
            raise ValueError("Unexpected provisioned instance inventory")
        inventory = {
            "vpc_id": instances[0]["VpcId"],
            "key_name": instances[0]["KeyName"],
            "instances": [
                {
                    "id": i["InstanceId"],
                    "launch_time": i["LaunchTime"].isoformat(),
                    "type": i["InstanceType"],
                    "ami": i["ImageId"],
                    "volume_ids": [v["Ebs"]["VolumeId"] for v in i["BlockDeviceMappings"]],
                }
                for i in instances
            ],
        }
        write(args.out / "resource-inventory.json", inventory)
        receipt["status"] = "bootstrapping"
        save()
        for host in hosts:
            host = str(ipaddress.IPv4Address(host))
            for _ in range(120):
                if remote(host, "true", timeout=15, check=False) == 0:
                    break
                time.sleep(5)
            else:
                raise TimeoutError("SSH unavailable on a new node")
            code = remote(host, "sudo cloud-init status --wait", timeout=1200, check=False)
            if code not in (0, 2):
                raise RuntimeError("Cloud-init did not finish")
            remote(host, "systemctl is-active afri-cluster-expiry.timer")
            remote(host, "sudo k3s --version")
        receipt["expiry_timers_verified"] = True
        # Stream the exact local images directly to each node; no extra multi-GB archive.
        imported_images = []
        for host in hosts:
            with (args.state_dir / "image-transfer.log").open("ab") as log:
                producer = subprocess.Popen(
                    ["sudo", "-n", "docker", "image", "save", *[v["tag"] for v in images.values()]],
                    stdout=subprocess.PIPE,
                    stderr=log,
                    start_new_session=True,
                )
                children.append(producer)
                consumer = subprocess.Popen(
                    ssh + ["ubuntu@" + host, "sudo k3s ctr --namespace k8s.io images import -"],
                    stdin=producer.stdout,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                children.append(consumer)
                producer.stdout.close()
                try:
                    consumer.wait(timeout=min(1200, max(1, deadline - time.monotonic())))
                    producer.wait(timeout=30)
                finally:
                    stop(producer)
                    stop(consumer)
                if producer.returncode or consumer.returncode:
                    raise RuntimeError("Image transfer failed")
            for service, image in images.items():
                listing = remote(
                    host, "sudo k3s ctr --namespace k8s.io images list", capture=True
                ).decode()
                matches = [
                    line.split()
                    for line in listing.splitlines()
                    if line.split() and line.split()[0] == image["tag"]
                ]
                if len(matches) != 1 or len(matches[0]) < 3:
                    raise ValueError("Imported tag missing or ambiguous: " + service)
                digest = matches[0][2]
                raw_manifest = remote(
                    host,
                    "sudo k3s ctr --namespace k8s.io content get " + shlex.quote(digest),
                    capture=True,
                )
                status = json.loads(
                    remote(
                        host,
                        "sudo k3s crictl inspecti -o json " + shlex.quote(image["tag"]),
                        capture=True,
                    )
                )
                identity = verify_imported_image(
                    image["id"], digest, raw_manifest, status["status"]
                )
                imported_images.append(
                    {
                        "node_index": hosts.index(host),
                        "service": service,
                        "tag": image["tag"],
                        **identity,
                    }
                )
                write(args.out / "image-import-verification.json", imported_images)
        run(
            "stage-models",
            [
                sys.executable,
                "-m",
                "scripts.stage_models",
                "--asr-dir",
                str(args.asr_dir),
                "--llm-file",
                str(args.llm_file),
                "--hosts",
                *hosts,
                "--ssh-key",
                str(args.ssh_key),
                "--values-out",
                str(args.state_dir / "model-values.json"),
            ],
            timeout=1200,
        )
        # kubectl converts its own configuration; secrets stay in memory/private files.
        (args.state_dir / "kubeconfig").write_bytes(
            remote(hosts[0], "sudo cat /etc/rancher/k3s/k3s.yaml", capture=True)
        )
        config = json.loads(
            run(
                "kubeconfig-json", kubectl + ["config", "view", "--raw", "-o", "json"], capture=True
            )
        )
        for cluster in config["clusters"]:
            cluster["cluster"]["server"] = "https://127.0.0.1:36443"
        write(args.state_dir / "kubeconfig", config)
        # Refuse occupied loopback ports; never displace an unrelated process.
        for port in (36443, 34443, 23000, 29090):
            with socket.socket() as guard:
                guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                guard.bind(("127.0.0.1", port))
        tunnel_log = (args.state_dir / "tunnels.log").open("ab")
        tunnel = subprocess.Popen(
            ssh
            + [
                "-N",
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                "127.0.0.1:36443:127.0.0.1:6443",
                "-L",
                "127.0.0.1:34443:127.0.0.1:443",
                "ubuntu@" + hosts[0],
            ],
            stdout=tunnel_log,
            stderr=tunnel_log,
            start_new_session=True,
        )
        children.append(tunnel)
        time.sleep(3)
        if tunnel.poll() is not None:
            raise RuntimeError("SSH tunnel failed")
        for _ in range(120):
            joined = json.loads(
                run("nodes-joining", kubectl + ["get", "nodes", "-o", "json"], capture=True)
            )
            if len(joined["items"]) == args.nodes:
                break
            time.sleep(5)
        else:
            raise TimeoutError("Expected node count did not join the cluster")
        run(
            "nodes-ready",
            kubectl + ["wait", "--for=condition=Ready", "node", "--all", "--timeout=600s"],
            timeout=620,
        )
        node_info = json.loads(run("nodes", kubectl + ["get", "nodes", "-o", "json"], capture=True))
        if len(node_info["items"]) != args.nodes or any(
            n["status"]["nodeInfo"]["kubeletVersion"] != "v1.36.5+k3s1" for n in node_info["items"]
        ):
            raise ValueError("Cluster nodes/version disagree with the pinned topology")
        run("namespace", kubectl + ["create", "namespace", "afri-ai"])
        api_key = secrets.token_urlsafe(32)
        (args.state_dir / "api-key").write_text(api_key + "\n")
        secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "afri-ai-api", "namespace": "afri-ai"},
            "data": {"api-key": base64.b64encode(api_key.encode()).decode()},
        }
        run("api-secret", kubectl + ["apply", "-f", "-"], data=json.dumps(secret).encode())
        run(
            "tls-certificate",
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-keyout",
                str(args.state_dir / "benchmark-tls.key"),
                "-out",
                str(args.state_dir / "benchmark-tls.crt"),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
        )
        tls = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "kubernetes.io/tls",
            "metadata": {"name": "afri-benchmark-tls", "namespace": "afri-ai"},
            "data": {
                "tls.crt": base64.b64encode(
                    (args.state_dir / "benchmark-tls.crt").read_bytes()
                ).decode(),
                "tls.key": base64.b64encode(
                    (args.state_dir / "benchmark-tls.key").read_bytes()
                ).decode(),
            },
        }
        run("tls-secret", kubectl + ["apply", "-f", "-"], data=json.dumps(tls).encode())
        write(args.state_dir / "k6-config.json", {"hosts": {"localhost": "127.0.0.1"}})
        run(
            "monitoring-repo",
            helm
            + [
                "repo",
                "add",
                "prometheus-community",
                "https://prometheus-community.github.io/helm-charts",
                "--force-update",
            ],
        )
        run(
            "monitoring-install",
            helm
            + [
                "upgrade",
                "--install",
                "monitoring",
                "prometheus-community/kube-prometheus-stack",
                "--version",
                "92.13.1",
                "--namespace",
                "monitoring",
                "--create-namespace",
                "-f",
                "monitoring/values.yaml",
                "--wait",
                "--timeout",
                "15m",
            ],
            timeout=920,
        )
        dashboard = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "afri-ai-dashboard",
                "namespace": "monitoring",
                "labels": {"grafana_dashboard": "1"},
            },
            "data": {"afri-ai.json": (root / "monitoring/grafana-dashboard.json").read_text()},
        }
        run("dashboard", kubectl + ["apply", "-f", "-"], data=json.dumps(dashboard).encode())
        values_path = args.state_dir / "deployment-values.json"
        write(
            values_path,
            {
                **models,
                "imagePullPolicy": "Never",
                "speech": {**models["speech"], "image": images["speech"]["tag"]},
                "chat": {
                    **models["chat"],
                    "image": images["chat"]["tag"],
                    "llamaImage": images["llama"]["tag"],
                },
                "ingress": {
                    "enabled": True,
                    "host": "localhost",
                    "tlsSecretName": "afri-benchmark-tls",
                },
                "monitoring": {"enabled": True},
            },
        )
        install = helm + [
            "upgrade",
            "--install",
            "afri-ai",
            "k8s/afri-ai",
            "--namespace",
            "afri-ai",
            "-f",
            "k8s/values-free-plan.yaml",
            "-f",
            str(values_path),
            "--wait",
            "--timeout",
            "15m",
        ]
        run("application-install", install, timeout=920)
        # Readiness requires verified init containers, not merely a created Deployment.
        for _ in range(120):
            pods = json.loads(
                run(
                    "application-pods",
                    kubectl + ["-n", "afri-ai", "get", "pods", "-o", "json"],
                    capture=True,
                )
            )
            verified, ready, fatal = model_pod_states(pods["items"])
            # Preserve diagnostic states before checking, including pending replicas.
            write(args.out / "model-init-verification.json", verified)
            if fatal:
                raise ValueError("A final-model pod failed its init hash verification")
            if ready:
                break
            time.sleep(5)
        else:
            raise TimeoutError("Final-model pods did not all become verified and ready")
        run(
            "network-policy-verification",
            [
                sys.executable,
                "-m",
                "loadtest.network_policy",
                "--kubectl",
                str(args.tools_dir / "kubectl"),
                "--image",
                images["chat"]["tag"],
                "--out",
                str(args.out / "network-policy-verification.json"),
            ],
            timeout=240,
        )
        base = "https://localhost:34443"
        context = ssl.create_default_context(cafile=str(args.state_dir / "benchmark-tls.crt"))

        def smoke():
            checks = {}
            with httpx.Client(verify=context, timeout=180, trust_env=False) as client:
                checks["unauthorized_401"] = (
                    client.post(
                        base + "/v1/chat/completions",
                        json={
                            "messages": [{"role": "user", "content": "Say hello."}],
                            "max_tokens": 8,
                        },
                    ).status_code
                    == 401
                )
                response = client.post(
                    base + "/v1/chat/completions",
                    headers={"Authorization": "Bearer " + api_key},
                    json={"messages": [{"role": "user", "content": "Say hello."}], "max_tokens": 8},
                )
                checks["chat_200"] = response.status_code == 200 and bool(
                    response.json().get("choices")
                )
                audio = client.post(
                    base + "/transcribe",
                    headers={"Authorization": "Bearer " + api_key, "Content-Type": "audio/wav"},
                    content=args.audio.read_bytes(),
                )
                checks["transcription_200"] = audio.status_code == 200 and isinstance(
                    audio.json().get("text"), str
                )
            if not all(checks.values()):
                raise RuntimeError("Final-cluster smoke checks failed")
            return checks

        receipt["smoke_checks"] = smoke()
        # Exercise an actual chart upgrade and rollback before the load experiment.
        run("upgrade", install + ["--set", "speech.threads=1"], timeout=920)
        run(
            "rollback",
            helm
            + ["rollback", "afri-ai", "1", "--namespace", "afri-ai", "--wait", "--timeout", "15m"],
            timeout=920,
        )
        receipt["post_rollback_smoke_checks"] = smoke()
        write(
            args.out / "run.json",
            {
                "started_at": receipt["started_at"],
                "source_commit": revision,
                "topology": topology,
                "k3s_version": "v1.36.5+k3s1",
                "monitoring_chart": "kube-prometheus-stack 92.13.1",
                "models": proof["model_hashes"],
                "asr_artifact": proof["asr_artifact"],
                "images": images,
                "hourly_usd": hourly,
                "price_evidence_sha256": hashlib.sha256(args.prices.read_bytes()).hexdigest(),
                "scope": "Administrator-only TLS ingress via SSH; research-only fine-tuned model; source-built exact images imported without registry credentials",
            },
        )
        save()
        receipt["status"] = "measuring"
        save()
        # k6 resolves localhost explicitly; no system-wide DNS/hosts modification.
        measurement_url = "https://localhost:34443"
        run(
            "load-and-failure",
            [
                sys.executable,
                "-m",
                "scripts.run_cloud_validation",
                "--out",
                str(args.out),
                "--base-url",
                measurement_url,
                "--key-file",
                str(args.state_dir / "api-key"),
                "--tls-ca",
                str(args.state_dir / "benchmark-tls.crt"),
                "--k6-config",
                str(args.state_dir / "k6-config.json"),
                "--audio",
                str(args.audio),
                "--k6-binary",
                str(args.tools_dir / "k6"),
                "--kubectl",
                str(args.tools_dir / "kubectl"),
            ],
            timeout=3600,
        )
        run(
            "steady-capacity",
            [
                sys.executable,
                "-m",
                "scripts.run_capacity",
                "--out",
                str(args.out),
                "--base-url",
                measurement_url,
                "--state-dir",
                str(args.state_dir),
                "--audio",
                str(args.audio),
                "--k6-binary",
                str(args.tools_dir / "k6"),
                "--kubectl",
                str(args.tools_dir / "kubectl"),
                "--hourly-usd",
                str(hourly),
            ],
            timeout=1500,
        )
        prometheus_log = (args.state_dir / "prometheus-forward.log").open("ab")
        forward = subprocess.Popen(
            kubectl
            + [
                "-n",
                "monitoring",
                "port-forward",
                "--address",
                "127.0.0.1",
                "service/monitoring-kube-prometheus-prometheus",
                "29090:9090",
            ],
            env=env,
            cwd=root,
            stdout=prometheus_log,
            stderr=prometheus_log,
            start_new_session=True,
        )
        children.append(forward)
        time.sleep(3)
        run(
            "monitoring-export",
            [
                sys.executable,
                "-m",
                "scripts.capture_monitoring",
                "--started-at",
                receipt["started_at"],
                "--endpoint",
                "http://127.0.0.1:29090",
                "--out",
                str(args.out / "monitoring-series.json"),
            ],
            timeout=180,
        )
        try:
            receipt["dashboard_capture_exit_code"] = run(
                "dashboard-capture",
                [
                    sys.executable,
                    "-m",
                    "scripts.capture_dashboard",
                    "--kubectl",
                    str(args.tools_dir / "kubectl"),
                    "--state-dir",
                    str(args.state_dir),
                    "--out",
                    str(args.out),
                    "--started-at",
                    receipt["started_at"],
                ],
                timeout=240,
                check=False,
            )
        except subprocess.TimeoutExpired:
            receipt["dashboard_capture_error_type"] = "TimeoutExpired"
        receipt["status"] = "measurements_complete"
    except BaseException as error:
        receipt.update(status="stopped", error_type=type(error).__name__)
        raise
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        reserve.unlink(missing_ok=True)
        for process in reversed(children):
            stop(process)
        if applied:
            if inventory and sorted(outputs().get("instance_ids", [])) != sorted(
                i["id"] for i in inventory["instances"]
            ):
                raise RuntimeError("Owned instance set changed; cleanup refused")
            run(
                "terraform-destroy",
                tf
                + [
                    "destroy",
                    "-auto-approve",
                    "-input=false",
                    "-no-color",
                    "-var-file=" + str(varfile),
                ],
                timeout=1200,
                cleanup=True,
            )
            receipt["managed_state_empty"] = empty_state(state)
            if inventory:
                run(
                    "teardown-verification",
                    [
                        sys.executable,
                        "-m",
                        "scripts.verify_teardown",
                        "--inventory",
                        str(args.out / "resource-inventory.json"),
                        "--out",
                        str(args.out / "teardown.json"),
                        "--account-id",
                        args.account_id,
                    ],
                    timeout=120,
                    cleanup=True,
                )
                receipt["teardown_verified"] = json.loads((args.out / "teardown.json").read_text())[
                    "destroy_verified"
                ]
        receipt["finished_at"] = now()
        save()


if __name__ == "__main__":
    main()
