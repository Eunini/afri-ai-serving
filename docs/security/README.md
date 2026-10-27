# Runtime image audit

These reports identify the actual local amd64 images used for the selected
fine-tuned-model integration test. Trivy 0.76.1 was downloaded from its official
release and its archive checksum verified. Both vulnerability scanning and full
license scanning ran. Raw report hashes are retained with each condensed report.
Mounted model weights are not part of the image and have separate source/license
and SHA256 records.

| Image | Package vulnerability findings | HIGH | CRITICAL | Fixable HIGH/CRITICAL in this scan |
| --- | ---: | ---: | ---: | ---: |
| Speech gateway | 177 | 45 | 0 | 0 |
| Chat gateway | 170 | 44 | 0 | 0 |
| llama.cpp | 29 | 0 | 0 | 0 |

These are per-package findings, so the same CVE can appear for several binary
packages. Zero fixable high findings does not mean zero vulnerabilities. The
gateway high findings came from Debian OS packages, including util-linux and
libsndfile; the scanner supplied no fixed version. The earlier Python-lockfile
audit did not cover these components. Non-root users, dropped capabilities,
read-only roots, restricted networking and request limits reduce exposure but
do not establish that every finding is harmless. The audio parser is especially
relevant when processing untrusted files.

The license reports contain restricted and unknown classifications. These are
scanner categories, not a legal conclusion or an assertion that GPL software
cannot be used. Dependency notices and source-distribution obligations still
need review before a production distribution. The repository's MIT license
does not replace third-party package or model licenses.

CI now builds each image locally, scans its OS and language packages and full
license files, retains complete reports, and blocks registry publication when a
HIGH/CRITICAL vulnerability has an available fix. All unfixed findings remain
visible. Passing that CI policy is not production clearance. Native C/C++ code
coverage, unresolved findings and license obligations remain release gates.

Source: [Trivy license-scanning documentation](https://trivy.dev/docs/latest/scanner/license/).
Vulnerability records include each advisory's primary URL; consult the vendor
advisory before assigning exploitability or accepting an exception.
