"""Persist RAM-backed evidence once teardown is independently verified."""

import argparse
import json
import os
import tarfile
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--wait-seconds", type=int, default=0)
    a = p.parse_args()
    deadline = time.monotonic() + a.wait_seconds
    while True:
        try:
            verified = json.loads((a.source / "teardown.json").read_text()).get(
                "destroy_verified"
            ) is True
        except (FileNotFoundError, json.JSONDecodeError):
            verified = False
        if verified:
            break
        if time.monotonic() >= deadline:
            raise SystemExit("No verified teardown yet; source evidence retained")
        time.sleep(min(20, max(0, deadline - time.monotonic())))
    files = sorted(f for f in a.source.rglob("*") if f.is_file())
    for path in files:
        if path.is_symlink() or any(
            marker in path.name.lower()
            for marker in (".key", ".pem", ".tfstate", "credential", "api-key", "kubeconfig")
        ):
            raise ValueError("Unexpected private material in evidence directory")
    a.archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = a.archive.with_name(a.archive.name + ".part")
    with tarfile.open(temporary, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=str(Path(a.source.name) / path.relative_to(a.source)))
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary.replace(a.archive)
    print("Preserved", len(files), "evidence files after verified teardown:", a.archive)


if __name__ == "__main__":
    main()
