"""Stage reviewed model artifacts on every new research node before Helm deployment."""

import argparse
import ipaddress
import shlex
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asr-dir", type=Path, required=True)
    p.add_argument("--llm-file", type=Path, required=True)
    p.add_argument("--hosts", nargs="+", required=True)
    p.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/afri-ai")
    a = p.parse_args()
    if not (a.asr_dir / "config.json").is_file() or not (a.asr_dir / "model.bin").is_file():
        raise ValueError("Provide a CTranslate2 model directory")
    with a.llm_file.open("rb") as source:
        if source.read(4) != b"GGUF":
            raise ValueError("Language model file is not GGUF")
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
            [
                *ssh,
                target,
                "sudo chown -R 10001:10001 /opt/afri-models && sudo chmod -R a+rX /opt/afri-models",
            ],
            check=True,
        )
    print("Model artifacts staged on all specified nodes.")


if __name__ == "__main__":
    main()
