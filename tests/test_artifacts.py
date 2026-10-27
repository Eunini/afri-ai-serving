import hashlib

import pytest

from services.artifacts import manifests, verify


def test_changed_model_never_passes_reviewed_manifest(tmp_path):
    (tmp_path / "model.bin").write_bytes(b"reviewed weights")
    (tmp_path / "config.json").write_text("{}")
    gguf = tmp_path / "selected.gguf"
    gguf.write_bytes(b"GGUFtest")
    expected = manifests(tmp_path, gguf)["speech"]["modelHashes"]
    assert verify(tmp_path, expected) == 2
    (tmp_path / "model.bin").write_bytes(b"different weights")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify(tmp_path, expected)


@pytest.mark.parametrize(
    "manifest",
    [{}, {"model.bin": "invalid"}, {"../outside": "0" * 64}, {"/tmp/elsewhere": "0" * 64}],
)
def test_missing_or_unsafe_model_manifest_fails_closed(tmp_path, manifest):
    with pytest.raises(ValueError):
        verify(tmp_path, manifest)


def test_symlink_cannot_escape_model_volume(tmp_path):
    volume = tmp_path / "models"
    volume.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"weights")
    (volume / "model.bin").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        verify(volume, {"model.bin": hashlib.sha256(b"weights").hexdigest()})
