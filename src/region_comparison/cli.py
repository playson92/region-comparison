"""Explicit command-line operations, with no secret-bearing diagnostics."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

from region_comparison.config import DEFAULT_SNAPSHOT, METHODOLOGY_VERSION, ROOT, read_indicators


def _dataset(snapshot: Path, database_url: str | None = None):
    from region_comparison.storage import load_database, load_snapshot

    return load_database(database_url) if database_url else load_snapshot(snapshot)


def _emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_bundle(output: Path) -> None:
    from region_comparison.storage import load_snapshot

    def git(*arguments):
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT.as_posix()}", *arguments],
            cwd=ROOT,
            text=True,
        ).strip()

    tracked = git("ls-files").splitlines()
    files = [ROOT / name for name in tracked if (ROOT / name).is_file()]
    if output.resolve() in [path.resolve() for path in files]:
        raise ValueError("Review archive cannot include itself")
    dataset = load_snapshot(DEFAULT_SNAPSHOT)
    checks_path = ROOT / "docs" / "verification-results.json"
    checks = json.loads(checks_path.read_text(encoding="utf-8")) if checks_path.exists() else {}
    manifest = {
        "repo": git("remote", "get-url", "origin"),
        "branch": git("branch", "--show-current"),
        "commit": git("rev-parse", "HEAD"),
        "snapshot_id": dataset.snapshot_id,
        "methodology_version": METHODOLOGY_VERSION,
        "checks": checks,
        "files": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            if any(
                part in {".git", ".venv", ".cache", "__pycache__"} for part in Path(relative).parts
            ):
                raise ValueError(f"Private/generated artifact in tracked files: {relative}")
            if Path(relative).name == ".env":
                raise ValueError("Private environment file cannot be bundled")
            bundle.write(path, relative)
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    _emit(
        {
            "bundle": str(output.resolve()),
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "commit": manifest["commit"],
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RegionComparison reproducible data operations")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "discover", "fetch", "validate", "load", "report", "bundle"):
        command = subcommands.add_parser(name)
        command.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
        if name in {"doctor", "load", "report"}:
            command.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
        if name == "doctor":
            command.add_argument("--require-database", action="store_true")
        if name in {"discover", "fetch"}:
            command.add_argument("--config", type=Path, default=ROOT / "config" / "indicators.yml")
        if name == "discover":
            command.add_argument("--live", action="store_true")
        if name in {"fetch", "report", "bundle"}:
            defaults = {
                "fetch": ROOT / "data/raw/latest",
                "report": ROOT / "docs/findings.md",
                "bundle": ROOT / "REVIEW_BUNDLE.zip",
            }
            command.add_argument("--output", type=Path, default=defaults[name])
    args = parser.parse_args(argv)
    try:
        if args.command == "bundle":
            build_bundle(args.output)
            return 0
        if args.command == "fetch":
            from region_comparison.ingestion import fetch_snapshot

            config = read_indicators(args.config)
            config["units"] = json.loads(
                (ROOT / config["unit_registry"]).read_text(encoding="utf-8")
            )
            config["attributes"] = json.loads(
                (ROOT / config["attributes_path"]).read_text(encoding="utf-8")
            )
            path = fetch_snapshot(config, args.output)
            _emit({"snapshot": path, "state": "complete"})
            return 0
        if args.command == "discover":
            config = read_indicators(args.config)
            if args.live:
                from region_comparison.ingestion import BDLClient

                client = BDLClient(cache_dir=ROOT / ".cache" / "bdl")
                result = [
                    client.get_json(f"variables/{i['indicator_id']}", {"format": "json"})
                    for i in config["indicators"]
                ]
                _emit(result)
            else:
                _emit({"mode": "verified_committed_metadata", "config": config})
            return 0
        if args.command == "load":
            from region_comparison.storage import import_snapshot

            if not args.database_url:
                raise ValueError("Set DATABASE_URL or pass --database-url for PostgreSQL import")
            snapshot_id = import_snapshot(args.database_url, args.snapshot)
            _emit({"snapshot_id": snapshot_id, "state": "active", "adapter": "postgres"})
            return 0
        from region_comparison.validation import validate_dataset

        database_url = getattr(args, "database_url", None)
        if args.command == "doctor" and args.require_database and not database_url:
            raise ValueError("DATABASE_URL required for full-path verification")
        if args.command == "validate":
            from region_comparison.storage import load_snapshot

            dataset = load_snapshot(args.snapshot, allow_partial=True)
        else:
            dataset = _dataset(args.snapshot, database_url)
        quality = validate_dataset(dataset)
        if args.command in {"doctor", "validate"}:
            _emit(
                {
                    "python": platform.python_version(),
                    "snapshot_id": dataset.snapshot_id,
                    "adapter": "postgres" if database_url else "snapshot",
                    "years": dataset.years,
                    "units": len(dataset.units),
                    "observations": len(dataset.observations),
                    "valid": quality.valid,
                    "counts": quality.counts,
                    "errors": quality.errors,
                    "warnings": quality.warnings,
                }
            )
            return 0 if quality.valid else 1
        if not quality.valid:
            raise ValueError("Dataset validation failed; report not generated")
        from region_comparison.reporting import findings, write_quality

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(findings(dataset), encoding="utf-8")
        if args.output.parent == ROOT / "docs":
            write_quality(dataset, ROOT / "docs" / "data-quality.md")
        _emit({"report": str(args.output), "snapshot_id": dataset.snapshot_id})
        return 0
    except Exception as error:
        # Connection errors can contain URLs/passwords. Emit a class and a safe task message.
        safe = (
            str(error)
            if isinstance(error, (ValueError, FileNotFoundError))
            else type(error).__name__
        )
        print(f"Operation failed: {safe}. See docs/windows-setup.md.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
