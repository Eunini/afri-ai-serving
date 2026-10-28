import hashlib
import json

import pytest

from scripts.image_identity import verify_imported_image


def test_manifest_and_configuration_ids_are_related_but_not_interchangeable():
    config = "sha256:" + "a" * 64
    raw = json.dumps({"schemaVersion": 2, "config": {"digest": config}, "layers": []}).encode()
    manifest = "sha256:" + hashlib.sha256(raw).hexdigest()
    proof = verify_imported_image(manifest, manifest, raw, {"id": config})
    assert proof["imported_manifest_sha256"] != proof["cri_image_id"]
    assert proof["manifest_bytes_hash_verified"]
    assert verify_imported_image(config, manifest, raw, {"id": config})
    with pytest.raises(ValueError, match="manifest bytes"):
        verify_imported_image(manifest, manifest, raw + b" ", {"id": config})
    with pytest.raises(ValueError, match="integrated image"):
        verify_imported_image("sha256:" + "b" * 64, manifest, raw, {"id": config})
    with pytest.raises(ValueError, match="CRI"):
        verify_imported_image(manifest, manifest, raw, {"id": "sha256:" + "b" * 64})
