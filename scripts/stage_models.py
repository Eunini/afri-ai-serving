"""Stage reviewed model artifacts on every new research node before Helm deployment."""

import argparse
import ipaddress
import shlex
import subprocess
import json
from pathlib import Path

from services.artifacts import manifests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asr-dir", type=Path, required=True)
    p.add_argument("--llm-file", type=Path, required=True)
    p.add_argument("--hosts", nargs="+", required=True)
    p.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/afri-ai")
    p.add_argument("--values-out", type=Path, default=Path("model-values.json"))
    a = p.parse_args()
    if not (a.asr_dir / "config.json").is_file() or not (a.asr_dir / "model.bin").is_file():
        raise ValueError("Provide a CTranslate2 model directory")
    with a.llm_file.open("rb") as source:
        if source.read(4) != b"GGUF":
            raise ValueError("Language model file is not GGUF")
    values = manifests(a.asr_dir, a.llm_file)
    ssh = [
        "ssh",
        "-i",
        str(a.ssh_key),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    for host in a.hosts:
        host = str(ipaddress.IPv4Address(host))
        target = "ubuntu@" + host
        subprocess.run(
            [
                *ssh,
                target,
                "sudo install -d -o ubuntu -g ubuntu /opt/afri-models/asr /opt/afri-models/llm",
            ],
            check=True,
        )
        subprocess.run(
            [
                "rsync",
                "-aL",
                "--exclude=.cache",
                "-e",
                shlex.join(ssh),
                str(a.asr_dir.resolve()) + "/",
                target + ":/opt/afri-models/asr/",
            ],
            check=True,
        )
        subprocess.run(
            [
                "rsync",
                "-a",
                "-e",
                shlex.join(ssh),
                str(a.llm_file.resolve()),
                target + ":/opt/afri-models/llm/model.gguf",
            ],
            check=True,
        )
        subprocess.run(
            [*ssh, target, "cd /opt/afri-models && sha256sum --check --strict -"],
            input="".join(
                checksum + "  " + kind + "/" + name + "\n"
                for service, kind in [("speech", "asr"), ("chat", "llm")]
                for name, checksum in values[service]["modelHashes"].items()
            ),
            text=True,
            check=True,
        )
        subprocess.run(
            [
                *ssh,
                target,
                "sudo chown -R 10001:10001 /opt/afri-models && sudo chmod -R a+rX /opt/afri-models",
            ],
            check=True,
        )
    a.values_out.parent.mkdir(parents=True, exist_ok=True)
    a.values_out.write_text(json.dumps(values, indent=2) + "\n")
    print("Model artifacts staged and hash-verified on all specified nodes.")
    print("Include the generated --values-out file in every Helm install or upgrade.")


if __name__ == "__main__":
    main()
