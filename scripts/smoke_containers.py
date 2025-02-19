"""Exercise three real containers and optionally a clearly labelled local LLM pilot."""

import argparse
import hashlib
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
import uuid
import tempfile
from pathlib import Path

import httpx


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asr-model", type=Path, required=True)
    p.add_argument("--llm-model", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--docker-prefix", default="docker")
    p.add_argument("--out", type=Path, default=Path("docs/container-smoke.json"))
    p.add_argument("--benchmark-repo", type=Path)
    p.add_argument("--benchmark-limit", type=int, default=0)
    a = p.parse_args()
    a.asr_model = a.asr_model.resolve(strict=True)
    a.llm_model = a.llm_model.resolve(strict=True)
    a.audio = a.audio.resolve(strict=True)
    if not (a.asr_model / "config.json").exists():
        raise ValueError("ASR artifact must be a real CTranslate2 model directory")
    docker = shlex.split(a.docker_prefix)
    network = "afri-research-" + uuid.uuid4().hex[:8]
    ids = []
    env = {**os.environ, "API_KEY": secrets.token_urlsafe(32)}
    key_file = tempfile.NamedTemporaryFile(mode="w", prefix="afri-research-key-", delete=False)
    key_file.write("API_KEY=" + env["API_KEY"] + "\n")
    key_file.close()
    result = {
        "scope": "local real-model container integration; not a cloud capacity benchmark",
        "asr_artifact": "pretrained faster-whisper-tiny, int8 compute",
        "llm_artifact": a.llm_model.name,
        "checks": {},
        "status": "running",
    }

    def call(*args):
        return subprocess.check_output([*docker, *args], text=True, env=env).strip()

    def start(image, extra):
        # sudo normally resets environment variables; a private temporary file
        # passes this ephemeral key without placing it in command arguments.
        extra = list(extra)
        for i in range(len(extra) - 1):
            if extra[i : i + 2] == ["-e", "API_KEY"]:
                extra[i : i + 2] = ["--env-file", key_file.name]
        value = call(
            "run",
            "-d",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--network",
            network,
            "--label",
            "research.portfolio=african-language-ai",
            *extra,
            image,
        )
        ids.append(value)
        return value

    def port(container, internal):
        for _ in range(20):
            info = json.loads(call("inspect", container))[0]
            binding = info["NetworkSettings"].get("Ports", {}).get(f"{internal}/tcp")
            if binding:
                return int(binding[0]["HostPort"])
            if info["State"]["Status"] == "exited":
                # Only this experiment's logs; the API key is redacted before display.
                log = subprocess.run(
                    [*docker, "logs", "--tail", "25", container], capture_output=True, text=True
                )
                import re

                safe = re.sub(r"https?://\S+", "[URL omitted]", log.stderr + log.stdout)
                print(safe.replace(env["API_KEY"], "[redacted]"), flush=True)
                raise RuntimeError("Container exited before publishing its port")
            time.sleep(0.25)
        raise RuntimeError("Container port binding did not become available")

    def ready(url):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                if httpx.get(url, timeout=3).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise RuntimeError("Container readiness timed out")

    call("network", "create", "--label", "research.portfolio=african-language-ai", network)
    try:
        asr = a.asr_model.resolve()
        cache = asr.parents[2] if asr.parent.name == "snapshots" else asr
        inside = "/asr/" + str(asr.relative_to(cache))
        llm = start(
            "afri-research-llama:local",
            [
                "--network-alias",
                "llama",
                "-p",
                "127.0.0.1::8081",
                "-v",
                f"{a.llm_model.resolve()}:/models/model.gguf:ro",
            ],
        )
        speech = start(
            "afri-research-speech:local",
            [
                "-p",
                "127.0.0.1::8000",
                "-e",
                "API_KEY",
                "-e",
                f"ASR_MODEL={inside}",
                "-v",
                f"{cache}:/asr:ro",
            ],
        )
        chat = start(
            "afri-research-chat:local",
            ["-p", "127.0.0.1::8000", "-e", "API_KEY", "-e", "LLAMA_URL=http://llama:8081"],
        )
        speech_url = f"http://127.0.0.1:{port(speech, 8000)}"
        chat_url = f"http://127.0.0.1:{port(chat, 8000)}"
        llm_url = f"http://127.0.0.1:{port(llm, 8081)}"
        for url in [speech_url + "/ready", chat_url + "/ready", llm_url + "/health"]:
            ready(url)
        headers = {"Authorization": "Bearer " + env["API_KEY"]}
        with httpx.Client(timeout=180) as client:
            unauthorized = client.post(speech_url + "/transcribe", content=b"test")
            assert unauthorized.status_code == 401
            invalid = client.post(speech_url + "/transcribe", content=b"not audio", headers=headers)
            assert invalid.status_code == 415
            response = client.post(
                speech_url + "/transcribe", content=a.audio.read_bytes(), headers=headers
            )
            response.raise_for_status()
            output = response.json()
            assert isinstance(output["text"], str) and output["audio_seconds"] > 0
            chat_body = {
                "model": "local",
                "messages": [{"role": "user", "content": "Reply with hello."}],
                "max_tokens": 16,
            }
            answer = client.post(chat_url + "/v1/chat/completions", json=chat_body, headers=headers)
            answer.raise_for_status()
            assert answer.json()["choices"][0]["message"]["content"]
            metrics = client.get(speech_url + "/metrics").text
            assert "afri_audio_seconds_total" in metrics
            result["checks"] = {
                "readiness": True,
                "unauthorized_401": True,
                "invalid_audio_415": True,
                "real_transcription_200": True,
                "real_chat_200": True,
                "prometheus_audio_counter": True,
            }
            result["transcription_sha256"] = hashlib.sha256(output["text"].encode()).hexdigest()
            result["audio_seconds"] = output["audio_seconds"]
        if a.benchmark_repo and a.benchmark_limit:
            pid = json.loads(call("inspect", llm))[0]["State"]["Pid"]
            provenance = json.loads(a.llm_model.with_suffix(".provenance.json").read_text())
            command = [
                sys.executable,
                "-m",
                "bench.run",
                "--endpoint",
                llm_url + "/v1",
                "--model",
                "local",
                "--label",
                "Qwen2.5-1.5B-Q4_K_M-local-pilot",
                "--model-revision",
                provenance["sha256"],
                "--placement",
                "local",
                "--device",
                "shared Linux x86_64 development host, 8 vCPU, 23 GiB RAM",
                "--server-pid",
                str(pid),
                "--limit",
                str(a.benchmark_limit),
                "--max-tokens",
                "64",
                "--out",
                "report/runs/qwen-q4-local-pilot.jsonl",
            ]
            subprocess.run(command, cwd=a.benchmark_repo, check=True)
            result["pilot_items_requested"] = a.benchmark_limit
        result["status"] = "passed"
    finally:
        Path(key_file.name).unlink(missing_ok=True)
        for container in reversed(ids):
            subprocess.run([*docker, "rm", "-f", container], check=False, capture_output=True)
        subprocess.run([*docker, "network", "rm", network], check=False, capture_output=True)
        result["temporary_containers_and_network_removed"] = True
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
