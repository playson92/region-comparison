"""Shared, working-directory independent paths for all project-created artifacts."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(os.environ.get("REGION_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
OUTPUT = ROOT / "output"


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:12]


def run_id(value: str | None = None) -> str:
    value = value or os.environ.get("REGION_RUN_ID") or new_run_id()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", value):
        raise ValueError("run_id must be a safe identifier (letters, digits, _ and -)")
    return value


def output_path(value: str | Path) -> Path:
    """Resolve relative arguments against project root and reject escapes, including symlinks."""
    path = Path(value)
    resolved = (path if path.is_absolute() else ROOT / path).resolve()
    if resolved == OUTPUT.resolve() or not resolved.is_relative_to(OUTPUT.resolve()):
        raise ValueError(f"Artifact path must be inside project output: {OUTPUT}")
    return resolved


def artifact_path(category: str, identifier: str, name: str | None = None) -> Path:
    identifier = run_id(identifier)
    path = OUTPUT / category / identifier
    return output_path(path / name if name else path)
