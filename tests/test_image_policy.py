import pytest

from scripts.audit_image_report import summarize


def test_fixable_high_findings_block_images_without_hiding_unfixed_findings():
    report = {
        "Metadata": {"OS": {"Family": "debian"}},
        "Results": [
            {
                "Class": "os-pkgs",
                "Vulnerabilities": [
                    {"VulnerabilityID": "CVE-test-fixed", "Severity": "HIGH", "FixedVersion": "2"},
                    {"VulnerabilityID": "CVE-test-unfixed", "Severity": "HIGH"},
                ],
            }
        ],
    }
    result = summarize(report)
    assert result["fixable_high_critical"] == 1
    assert result["package_findings_by_severity"]["HIGH"] == 2
    assert result["production_clearance"] is False


def test_missing_scanner_coverage_never_counts_as_zero_vulnerabilities():
    with pytest.raises(ValueError, match="coverage"):
        summarize({"Results": []})
