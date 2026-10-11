import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from region_comparison.bundle import build_bundle
from region_comparison.cli import main
from region_comparison.paths import ROOT, artifact_path, new_run_id, output_path


@pytest.mark.parametrize(
    "path",
    [ROOT, ROOT / "docs" / "findings.md", ROOT.parent / "escape.zip", "../escape.md", "output"],
)
def test_reject_artifact_paths_outside_output(path):
    with pytest.raises(ValueError, match="inside project output"):
        output_path(path)


@pytest.mark.parametrize("command", ["report", "bundle", "fetch"])
def test_cli_rejects_output_escape(command, capsys):
    assert main([command, "--output", str(ROOT / "docs" / "escape.md")]) == 1
    assert "inside project output" in capsys.readouterr().err
    assert not (ROOT / "docs" / "escape.md").exists()


def test_unique_run_ids_even_when_created_immediately():
    identifiers = {new_run_id() for _ in range(1000)}
    assert len(identifiers) == 1000


def test_reporting_defaults_and_explicit_output_from_other_cwd(tmp_path, monkeypatch, capsys):
    before = subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)
    monkeypatch.chdir(tmp_path)
    paths = []
    for _ in range(2):
        assert main(["report"]) == 0
        result = json.loads(capsys.readouterr().out)
        paths.append(result["report"])
        assert Path(result["report"]).is_relative_to(ROOT / "output" / "reports")
        assert Path(result["quality"]).is_file()
    assert paths[0] != paths[1]
    identifier = new_run_id()
    target = f"output/reports/{identifier}/custom.md"
    assert main(["report", "--output", target]) == 0
    assert output_path(target).is_file()
    assert subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT) == before


def test_bundle_explicit_evidence_hashes_exclusions_and_working_tree(tmp_path):
    identifier = new_run_id()
    run_root = artifact_path("codex_runs", identifier)
    run_root.mkdir(parents=True)
    (run_root / "CODEX_RUN.md").write_text("Controlled nonsecret evidence", encoding="utf-8")
    (run_root / "not-selected.txt").write_text("Do not bundle", encoding="utf-8")
    (run_root / "nested.zip").write_bytes(b"excluded")
    before = subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)
    result = build_bundle(identifier=identifier, evidence=["CODEX_RUN.md"])
    archive_path = Path(result["bundle"])
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert "src/region_comparison/cli.py" in names
        assert "tests/test_analytics.py" in names
        assert "data/sample/observations.csv" in names
        assert "evidence/CODEX_RUN.md" in names
        assert "evidence/not-selected.txt" not in names
        assert not any(Path(name).suffix == ".zip" or name.startswith("output/") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        assert manifest["source_state"] in {"clean", "dirty"}
        assert manifest["dataset_sha256"]
        assert manifest["methodology_sha256"]
    assert result["sha256"] in archive_path.with_suffix(".sha256").read_text("utf-8")
    assert subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT) == before
    for rejected in ["nested.zip", "../outside.txt"]:
        with pytest.raises(ValueError):
            build_bundle(identifier=identifier, evidence=[rejected])


@pytest.mark.skipif(
    sys.platform != "win32", reason="PowerShell behavior executes on Windows matrix"
)
def test_power_shell_scripts_parse_and_reuse_from_alternate_cwd(tmp_path):
    script = ROOT / "scripts" / "refresh-data.ps1"
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "RemoteSigned",
            "-File",
            str(script),
            "-Mode",
            "reuse",
            "-Snapshot",
            str(ROOT / "data" / "sample"),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert '"operation": "reuse"' in result.stdout
    assert '"valid": true' in result.stdout
