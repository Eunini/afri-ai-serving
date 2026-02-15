"""Verify this experiment's known resources are gone; never inspect billing."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from scripts.resource_states import instance_gone


def absent(call, missing_code, **kwargs):
    try:
        call(**kwargs)
        return False
    except ClientError as error:
        if error.response["Error"]["Code"] == missing_code:
            return True
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", type=Path, required=True, help="Sanitized pre-destroy inventory")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--profile", default="afri-research")
    p.add_argument("--account-id", required=True)
    a = p.parse_args()
    session = boto3.Session(profile_name=a.profile, region_name="us-east-1")
    if session.client("sts").get_caller_identity()["Account"] != a.account_id:
        raise ValueError("AWS identity differs from the intended account")
    ec2 = session.client("ec2")
    original = json.loads(a.inventory.read_text())
    checks = {}
    for instance in original["instances"]:
        try:
            found = ec2.describe_instances(InstanceIds=[instance["id"]])["Reservations"]
            checks[instance["id"]] = instance_gone(found)
        except ClientError as error:
            if error.response["Error"]["Code"] != "InvalidInstanceID.NotFound":
                raise
            checks[instance["id"]] = True
        for volume in instance["volume_ids"]:
            checks[volume] = absent(
                ec2.describe_volumes, "InvalidVolume.NotFound", VolumeIds=[volume]
            )
    checks[original["vpc_id"]] = absent(
        ec2.describe_vpcs, "InvalidVpcID.NotFound", VpcIds=[original["vpc_id"]]
    )
    checks[original["key_name"]] = absent(
        ec2.describe_key_pairs, "InvalidKeyPair.NotFound", KeyNames=[original["key_name"]]
    )
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "region": "us-east-1",
        "checks": checks,
        "destroy_verified": all(checks.values()),
        "scope": "Known experiment instances, boot volumes, VPC and registered public key. Does not assert the whole account is empty or query billing.",
    }
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if not result["destroy_verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
