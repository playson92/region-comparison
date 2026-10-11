"""CI policy guard: inspect actual tracked artifacts and exercise write-path rejection."""

import subprocess

from region_comparison.paths import ROOT, output_path

RUN_ARTIFACTS = {
    "CODEX_RUN.md",
    "verification-results.json",
    "live-fetch-verification.json",
    "browser-check.json",
    "implementation-status.md",
    "REVIEW_BUNDLE.zip",
}
FORBIDDEN_LEGACY = {"docs/review.md", "docs/tooling-verification.md"}
# Maintained findings, quality policy, concise review guide and sample inputs are intentional.


def main():
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    forbidden = [
        name
        for name in tracked
        if name.startswith("output/")
        or name in FORBIDDEN_LEGACY
        or name.endswith((".zip", ".log"))
        or (name.split("/")[-1] in RUN_ARTIFACTS and not name.startswith("data/sample/"))
    ]
    if forbidden:
        raise ValueError("Tracked run artifacts: " + ", ".join(forbidden))
    for invalid in (ROOT, ROOT / "docs" / "report.md", ROOT.parent / "escape.zip"):
        try:
            output_path(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Output escape accepted: {invalid}")
    probes = [
        "output/review/probe/REVIEW_BUNDLE.zip",
        "output/codex_runs/probe/CODEX_RUN.md",
        "output/reports/probe/findings.md",
        "output/exports/probe/scenario.json",
    ]
    for probe in probes:
        subprocess.check_call(["git", "check-ignore", "-q", probe], cwd=ROOT)
    print(
        "PASS: output untracked, generated run files untracked, escape rejection and ignore probes"
    )


if __name__ == "__main__":
    main()
