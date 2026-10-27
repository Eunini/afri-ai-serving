"""Verify reviewed model bytes before a pod starts either model service."""

import hashlib
import json
import os
import re
from pathlib import Path


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root, expected):
    root = Path(root).resolve(strict=True)
    if not isinstance(expected, dict) or not expected:
        raise ValueError(
            "Supply reviewed modelHashes; generate values with scripts/stage_models.py"
        )
    for name, checksum in expected.items():
        if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Model manifest paths must remain inside the model volume")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Model manifest needs SHA256 values")
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Model artifact is outside the model volume")
        if sha256(path) != checksum:
            raise ValueError("Model artifact checksum mismatch: " + name)
    return len(expected)


def manifests(asr_dir, llm_file):
    folder = Path(asr_dir)
    files = sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix in {".json", ".bin", ".txt"}
    )
    if not {"config.json", "model.bin"}.issubset({p.name for p in files}):
        raise ValueError("Supply the selected CTranslate2 model directory")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p.name) for p in files):
        raise ValueError("Model manifest filenames must be simple basenames")
    return {
        "speech": {"modelHashes": {p.name: sha256(p) for p in files}},
        "chat": {"modelHashes": {"model.gguf": sha256(llm_file)}},
    }


if __name__ == "__main__":
    n = verify(os.environ.get("MODEL_ROOT", "/models"), json.loads(os.environ["MODEL_HASHES"]))
    print(f"Verified {n} reviewed model artifacts")
