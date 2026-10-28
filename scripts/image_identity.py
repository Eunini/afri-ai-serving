"""Compare OCI manifest/configuration identities without conflating their hashes."""

import hashlib
import json
import re


def verify_imported_image(expected, manifest_digest, manifest_bytes, cri_status):
    if not all(re.fullmatch(r"sha256:[a-f0-9]{64}", d) for d in (expected, manifest_digest)):
        raise ValueError("Require SHA256 image identities")
    actual = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    if actual != manifest_digest:
        raise ValueError("Imported manifest bytes differ from the tag's target digest")
    manifest = json.loads(manifest_bytes)
    config_digest = manifest.get("config", {}).get("digest", "")
    if (
        not re.fullmatch(r"sha256:[a-f0-9]{64}", config_digest)
        or manifest.get("schemaVersion") != 2
    ):
        raise ValueError("Require a single-platform OCI/Docker v2 manifest")
    # Docker's classic store reports configuration IDs; its containerd store can
    # report manifest IDs. CRI's ID need not be the same type as Docker's ID.
    if expected not in {manifest_digest, config_digest}:
        raise ValueError("Imported manifest/configuration differs from the integrated image")
    cri_id = cri_status.get("id")
    if cri_id not in {manifest_digest, config_digest}:
        raise ValueError("CRI image ID does not identify the verified manifest/configuration")
    return {
        "integrated_docker_image_id": expected,
        "imported_manifest_sha256": manifest_digest,
        "imported_config_sha256": config_digest,
        "cri_image_id": cri_id,
        "manifest_bytes_hash_verified": True,
    }
