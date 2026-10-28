"""Capture a measured dashboard headlessly; keep login state outside the repo."""

import argparse
import base64
import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--started-at", required=True)
    args = parser.parse_args()
    state, output = args.state_dir.resolve(), args.out.resolve()
    if state.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Browser authentication state must remain outside the repository")
    os.umask(0o077)
    browser = "afri-dashboard-" + uuid.uuid4().hex[:8]
    auth_file = state / "dashboard-browser-auth.json"
    config = state / "dashboard-browser-config.json"
    config.write_text(json.dumps({"browser": {"launchOptions": {"headless": True}}}))
    log = (state / "dashboard-capture.log").open("ab")
    forward = subprocess.Popen(
        [
            args.kubectl,
            "-n",
            "monitoring",
            "port-forward",
            "--address",
            "127.0.0.1",
            "service/monitoring-grafana",
            "23000:80",
        ],
        stdout=log,
        stderr=log,
    )

    def cli(*command, check=True):
        subprocess.run(
            ["playwright-cli", "-s=" + browser, *command],
            cwd=state,
            stdout=log,
            stderr=log,
            timeout=100,
            check=check,
        )

    def interrupted(*_):
        raise SystemExit("Dashboard capture interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        with httpx.Client(base_url="http://127.0.0.1:23000", timeout=15, trust_env=False) as client:
            for _ in range(30):
                try:
                    client.get("/api/health").raise_for_status()
                    break
                except httpx.HTTPError:
                    if forward.poll() is not None:
                        raise RuntimeError("Grafana forwarding failed") from None
                    time.sleep(1)
            else:
                raise TimeoutError("Grafana did not become reachable")
            # This response contains credentials: capture only in memory, never log it.
            secret = json.loads(
                subprocess.check_output(
                    [
                        args.kubectl,
                        "-n",
                        "monitoring",
                        "get",
                        "secret",
                        "monitoring-grafana",
                        "-o",
                        "json",
                    ],
                    timeout=20,
                )
            )["data"]
            response = client.post(
                "/login",
                json={
                    "user": base64.b64decode(secret["admin-user"]).decode(),
                    "password": base64.b64decode(secret["admin-password"]).decode(),
                },
            )
            response.raise_for_status()
            client.get("/api/user").raise_for_status()
            cookies = [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": "127.0.0.1",
                    "path": c.path or "/",
                    "expires": c.expires if c.expires is not None else -1,
                    "httpOnly": True,
                    "secure": False,
                    "sameSite": "Lax",
                }
                for c in client.cookies.jar
            ]
            if not cookies:
                raise ValueError("Grafana did not create a browser session")
            auth_file.write_text(json.dumps({"cookies": cookies, "origins": []}))
        cli("open", "about:blank", "--config=" + str(config))
        cli("state-load", str(auth_file))
        auth_file.unlink()
        cli("resize", "1500", "1100")
        start = int(datetime.fromisoformat(args.started_at).timestamp() * 1000)
        url = f"http://127.0.0.1:23000/d/afri-ai-serving/african-language-ai-serving?from={start}&to=now&refresh=1h&kiosk"
        # Scroll all panels into view before full-page capture; Grafana loads lazily.
        titles = [
            p["title"]
            for p in json.loads(Path("monitoring/grafana-dashboard.json").read_text())["panels"]
        ]
        code = (
            "async page => { await page.goto("
            + json.dumps(url)
            + ",{waitUntil:'domcontentloaded'}); await page.getByText('afri-ai-speech',{exact:true}).first().waitFor({state:'visible',timeout:60000}); for (const title of "
            + json.dumps(titles)
            + ") { await page.getByText(title,{exact:true}).scrollIntoViewIfNeeded(); } await page.waitForLoadState('networkidle',{timeout:15000}); await page.evaluate(() => window.scrollTo(0,0)); await page.screenshot({path:"
            + json.dumps(str(output / "dashboard-final.png"))
            + ",fullPage:true}); }"
        )
        script = state / "capture-measured-dashboard.js"
        script.write_text(code)
        cli("run-code", "--filename=" + str(script))
        screenshot = output / "dashboard-final.png"
        if screenshot.stat().st_size < 10000:
            raise ValueError("Dashboard screenshot is unexpectedly small")
        (output / "dashboard-capture.json").write_text(
            json.dumps(
                {
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "status": "captured",
                    "started_at": args.started_at,
                    "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                    "scope": "Live Grafana panels after measured traffic; private localhost forwarding; authentication files excluded. Streaming-only panels may have no series for the nonstreaming workload.",
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        auth_file.unlink(missing_ok=True)
        try:
            cli("close", check=False)
        except (OSError, subprocess.SubprocessError):
            pass
        forward.terminate()
        try:
            forward.wait(timeout=10)
        except subprocess.TimeoutExpired:
            forward.kill()
            forward.wait(timeout=10)
        log.close()
    print("Measured dashboard screenshot saved; private browser session closed.")


if __name__ == "__main__":
    main()
