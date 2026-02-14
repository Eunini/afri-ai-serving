"""Finish one known experiment and destroy its Terraform resources even on failure."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--tools-dir", type=Path, required=True)
    p.add_argument("--hourly-usd", type=float, required=True)
    p.add_argument("--account-id", required=True)
    a = p.parse_args()
    if shutil.disk_usage(a.out).free < 256 * 1024**2:
        raise RuntimeError("Insufficient scratch space for the finite experiment")
    inventory = json.loads((a.out / "resource-inventory.json").read_text())
    expected_ids = sorted(i["id"] for i in inventory["instances"])
    env = os.environ.copy()
    env["PATH"] = str(a.tools_dir) + os.pathsep + env["PATH"]
    env["TF_DATA_DIR"] = str(a.state_dir / "terraform")
    stages = []

    def run(name, command, timeout):
        started = datetime.now(timezone.utc).isoformat()
        status = subprocess.run(command, env=env, timeout=timeout).returncode
        stages.append({"stage": name, "started_at": started, "return_code": status})
        (a.out / "controller-status.json").write_text(json.dumps(stages, indent=2) + "\n")
        if status:
            raise RuntimeError("Experiment stage failed: " + name)

    try:
        run(
            "stress-and-failure",
            [
                sys.executable,
                "-m",
                "scripts.run_cloud_validation",
                "--out",
                str(a.out),
                "--base-url",
                "https://afri-bench.internal",
                "--key-file",
                str(a.state_dir / "api-key"),
                "--tls-ca",
                str(a.state_dir / "benchmark-tls.crt"),
                "--k6-config",
                str(a.state_dir / "k6-config.json"),
                "--audio",
                str(a.audio),
                "--k6-binary",
                str(a.tools_dir / "k6"),
                "--kubectl",
                str(a.tools_dir / "kubectl"),
            ],
            3600,
        )
        run(
            "steady-capacity",
            [
                sys.executable,
                "-m",
                "scripts.run_capacity",
                "--out",
                str(a.out),
                "--base-url",
                "https://afri-bench.internal",
                "--state-dir",
                str(a.state_dir),
                "--audio",
                str(a.audio),
                "--k6-binary",
                str(a.tools_dir / "k6"),
                "--kubectl",
                str(a.tools_dir / "kubectl"),
                "--hourly-usd",
                str(a.hourly_usd),
            ],
            1500,
        )
        started = min(i["launch_time"] for i in inventory["instances"])
        run(
            "monitoring-export",
            [
                sys.executable,
                "-m",
                "scripts.capture_monitoring",
                "--started-at",
                started,
                "--out",
                str(a.out / "monitoring-series.json"),
            ],
            180,
        )
        # Wait for a measured legend before taking a screenshot; an empty loading
        # frame must never be passed off as monitoring evidence.
        capture = a.state_dir / "capture-dashboard.js"
        start = int(datetime.fromisoformat(started).timestamp() * 1000)
        end = int(datetime.now(timezone.utc).timestamp() * 1000)
        url = f"http://127.0.0.1:13000/d/afri-ai-serving/african-language-ai-serving?from={start}&to={end}&kiosk&refresh=1h"
        capture.write_text(
            "async page => { await page.goto("
            + json.dumps(url)
            + "); await page.getByText('afri-ai-speech', {exact:true}).first().waitFor({state:'visible',timeout:60000}); await page.screenshot({path:"
            + json.dumps(str((a.out / "dashboard-final.png").absolute()))
            + ",fullPage:true}); }"
        )
        # UI capture failure is recorded, while measured metrics remain available.
        ui_status = subprocess.run(
            ["playwright-cli", "-s=afri-dashboard", "run-code", "--filename=" + str(capture)],
            env=env,
            timeout=90,
        ).returncode
        stages.append({"stage": "dashboard-capture", "return_code": ui_status})
    finally:
        # Release our explicitly reserved disk space before Terraform must write
        # its state/logs, even if another workspace operation filled the disk.
        (a.state_dir / "cleanup-reserve.bin").unlink(missing_ok=True)
        # This state directory is exclusive to the task. Refuse a changed
        # instance set rather than deleting an experiment another process replaced.
        ids = json.loads(
            subprocess.check_output(
                [str(a.tools_dir / "terraform"), "-chdir=infra", "output", "-json", "instance_ids"],
                env=env,
            )
        )
        if sorted(ids) != expected_ids:
            raise RuntimeError("Terraform instance set changed; cleanup refused")
        logpath = a.state_dir / (a.out.name + "-destroy.log")
        with logpath.open("w") as log:
            status = subprocess.run(
                [
                    "bash",
                    "scripts/terraform.sh",
                    "destroy",
                    "-auto-approve",
                    "-var-file=" + str(a.state_dir / "research.tfvars"),
                    "-no-color",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
            ).returncode
        stages.append({"stage": "terraform-destroy", "return_code": status})
        (a.out / "controller-status.json").write_text(json.dumps(stages, indent=2) + "\n")
        if status:
            raise RuntimeError("Terraform destroy failed; inspect the external log")
        run(
            "teardown-verification",
            [
                sys.executable,
                "-m",
                "scripts.verify_teardown",
                "--inventory",
                str(a.out / "resource-inventory.json"),
                "--out",
                str(a.out / "teardown.json"),
                "--account-id",
                a.account_id,
            ],
            120,
        )


if __name__ == "__main__":
    main()
