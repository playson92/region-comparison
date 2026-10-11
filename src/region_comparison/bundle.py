"""Review archives with an explicit current-run evidence list and byte hashes."""

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

from region_comparison.config import DEFAULT_SNAPSHOT
from region_comparison.exports import dataset_fingerprint, methodology_fingerprint
from region_comparison.paths import ROOT, artifact_path, output_path, run_id
from region_comparison.storage import load_snapshot

SECRET_PATTERNS = (
    rb"gh[pousr]_[A-Za-z0-9]{30,}",
    rb"AKIA[0-9A-Z]{16}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
)


def git(*arguments) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *arguments], cwd=ROOT, text=True
    ).strip()


def _safe_file(path: Path, name: str) -> bytes:
    parts = Path(name).parts
    if any(p in {".git", ".venv", ".cache", "__pycache__", "cache", "tmp"} for p in parts):
        raise ValueError(f"Private or cached file cannot be bundled: {name}")
    if path.suffix.lower() == ".zip" or (
        path.name.startswith(".env") and path.name != ".env.example"
    ):
        raise ValueError(f"Private or nested archive cannot be bundled: {name}")
    raw = path.read_bytes()
    if any(re.search(pattern, raw) for pattern in SECRET_PATTERNS):
        raise ValueError(f"Secret pattern in selected file: {name}")
    return raw


def build_bundle(output: Path | None = None, *, identifier=None, evidence=None) -> dict:
    identifier = run_id(identifier)
    output = output_path(output or artifact_path("review", identifier, "REVIEW_BUNDLE.zip"))
    run_root = artifact_path("codex_runs", identifier)
    if evidence is None:
        evidence = [
            name
            for name in ("CODEX_RUN.md", "verification.json", "review.md")
            if (run_root / name).is_file()
        ]
    files = {}
    for name in git("ls-files").splitlines():
        path = ROOT / name
        if name.startswith("output/"):
            raise ValueError("Tracked output artifact detected")
        if path.is_file():
            files[name] = _safe_file(path, name)
    for name in evidence:
        path = (run_root / name).resolve()
        if not path.is_relative_to(run_root.resolve()) or not path.is_file():
            raise ValueError("Evidence must be an existing file in the selected run directory")
        relative = path.relative_to(run_root).as_posix()
        files[f"evidence/{relative}"] = _safe_file(path, relative)
    dataset = load_snapshot(DEFAULT_SNAPSHOT)
    verification = run_root / "verification.json"
    checks = (
        json.loads(verification.read_text(encoding="utf-8-sig")) if verification.exists() else {}
    )
    status = git("status", "--porcelain")
    manifest = {
        "bundle_schema_version": "1.1",
        "repo": git("remote", "get-url", "origin"),
        "branch": git("branch", "--show-current"),
        "commit": git("rev-parse", "HEAD"),
        "source_state": "dirty" if status else "clean",
        "working_tree_changes": status.splitlines(),
        "snapshot_id": dataset.snapshot_id,
        "dataset_sha256": dataset_fingerprint(dataset),
        "methodology_sha256": methodology_fingerprint(),
        "methodology_version": checks.get("methodology_version", "1.0.0"),
        "run_id": identifier,
        "checks": checks,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return {
        "bundle": str(output),
        "sha256": digest,
        "commit": manifest["commit"],
        "source_state": manifest["source_state"],
        "bytes": output.stat().st_size,
    }
