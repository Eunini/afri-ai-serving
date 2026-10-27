"""Fail CI on fixable high/critical CVEs while preserving all scanner findings."""

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(scan):
    results = scan.get("Results", [])
    if not scan.get("Metadata", {}).get("OS") or not any(
        r.get("Class") == "os-pkgs" for r in results
    ):
        raise ValueError("Image scan lacks operating-system package coverage")
    findings = [v for r in results for v in r.get("Vulnerabilities", [])]
    fixable = [
        v for v in findings if v.get("Severity") in {"HIGH", "CRITICAL"} and v.get("FixedVersion")
    ]
    return {
        "image_id": scan["Metadata"].get("ImageID"),
        "package_findings_by_severity": dict(Counter(v["Severity"] for v in findings)),
        "unique_cves": len({v["VulnerabilityID"] for v in findings}),
        "fixable_high_critical": len(fixable),
        "fixable_identifiers": sorted({v["VulnerabilityID"] for v in fixable}),
        "production_clearance": False,
        "scope": "CI rejects fixable high/critical findings. Unfixed vulnerabilities, native code coverage and license obligations still require release review.",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("report", type=Path)
    p.add_argument("--summary", type=Path, required=True)
    a = p.parse_args()
    result = summarize(json.loads(a.report.read_text()))
    a.summary.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["fixable_high_critical"]:
        raise SystemExit("Image publication blocked by fixable high/critical vulnerabilities")
