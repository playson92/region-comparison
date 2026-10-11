"""Explicit command-line operations with safe artifact paths and no secret diagnostics."""

import argparse
import json
import os
import platform
import sys
from pathlib import Path

from region_comparison.bundle import build_bundle
from region_comparison.config import DEFAULT_SNAPSHOT, ROOT, read_indicators
from region_comparison.paths import OUTPUT, artifact_path, output_path, run_id


def _dataset(snapshot: Path, database_url: str | None = None):
    from region_comparison.storage import load_database, load_snapshot

    return load_database(database_url) if database_url else load_snapshot(snapshot)


def _emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RegionComparison reproducible data operations")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "doctor",
        "discover",
        "fetch",
        "validate",
        "load",
        "initialize",
        "report",
        "bundle",
        "replay",
    ):
        command = subcommands.add_parser(name)
        command.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
        command.add_argument("--run-id")
        if name in {"doctor", "load", "initialize", "report"}:
            command.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
        if name == "doctor":
            command.add_argument("--require-database", action="store_true")
        if name in {"discover", "fetch"}:
            command.add_argument("--config", type=Path, default=ROOT / "config" / "indicators.yml")
        if name == "discover":
            command.add_argument("--live", action="store_true")
        if name in {"fetch", "report", "bundle", "replay"}:
            command.add_argument("--output", type=Path)
        if name == "fetch":
            command.add_argument(
                "--mode", choices=("refresh", "resume", "reuse"), default="refresh"
            )
        if name == "bundle":
            command.add_argument(
                "--evidence", action="append", help="Relative file under selected codex_runs run"
            )
        if name == "replay":
            command.add_argument("--configuration", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        identifier = run_id(args.run_id)
        if args.command == "bundle":
            _emit(build_bundle(args.output, identifier=identifier, evidence=args.evidence))
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
            if args.mode != "refresh" and args.output:
                raise ValueError("Use --snapshot for resume/reuse, --output only for a new refresh")
            path = args.output if args.mode == "refresh" else args.snapshot
            path = fetch_snapshot(config, path, mode=args.mode)
            _emit(
                {
                    "snapshot": path,
                    "state": "complete",
                    "operation": args.mode,
                    "cache_policy": "fresh_network" if args.mode == "refresh" else args.mode,
                }
            )
            return 0
        if args.command == "discover":
            config = read_indicators(args.config)
            if args.live:
                from region_comparison.ingestion import BDLClient

                with BDLClient(cache_dir=OUTPUT / "cache" / "bdl") as client:
                    _emit(
                        [
                            client.get_json(f"variables/{i['indicator_id']}", {"format": "json"})
                            for i in config["indicators"]
                        ]
                    )
            else:
                _emit({"mode": "verified_committed_metadata", "config": config})
            return 0
        if args.command in {"load", "initialize"}:
            from region_comparison.storage import import_snapshot, initialize_database

            if not args.database_url:
                raise ValueError(
                    "Set DATABASE_URL or pass --database-url for PostgreSQL operations"
                )
            operation = import_snapshot if args.command == "load" else initialize_database
            snapshot_id = operation(args.database_url, args.snapshot)
            _emit(
                {
                    "snapshot_id": snapshot_id,
                    "state": "active",
                    "operation": args.command,
                    "adapter": "postgres",
                }
            )
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
            raise ValueError("Dataset validation failed; no artifact generated")
        if args.command == "replay":
            from region_comparison.exports import replay_config

            configuration = json.loads(args.configuration.read_text(encoding="utf-8-sig"))
            result = replay_config(dataset, configuration)
            output = output_path(
                args.output or artifact_path("exports", identifier, "replayed.csv")
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            result.frame.to_csv(output, index=False, sep=";", na_rep="")
            _emit(
                {"replay": str(output), "cohort_ids": result.cohort_ids, "weights": result.weights}
            )
            return 0
        from region_comparison.reporting import findings, write_quality

        output = output_path(args.output or artifact_path("reports", identifier, "findings.md"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(findings(dataset), encoding="utf-8")
        quality_path = output.with_name("data-quality.md")
        write_quality(dataset, quality_path)
        _emit(
            {
                "report": str(output),
                "quality": str(quality_path),
                "snapshot_id": dataset.snapshot_id,
            }
        )
        return 0
    except Exception as error:
        from region_comparison.storage import StorageError

        safe = (
            str(error)
            if isinstance(error, (ValueError, FileNotFoundError, StorageError))
            else type(error).__name__
        )
        print(f"Operation failed: {safe}. See docs/windows-setup.md.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
