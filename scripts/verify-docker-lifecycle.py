"""Isolated Compose probe with a source-consistent, explicitly synthetic snapshot B."""

import hashlib
import json
import os
import shutil
import sys

import pandas as pd

from region_comparison.config import DEFAULT_SNAPSHOT
from region_comparison.paths import OUTPUT, new_run_id
from region_comparison.storage import import_snapshot, load_database

URL = os.environ["DATABASE_URL"]
PROBE = OUTPUT / "tmp" / "docker-lifecycle-probe.json"


def main():
    stage = sys.argv[1]
    if stage == "activate-newer":
        destination = OUTPUT / "snapshots" / ("docker-fixture-" + new_run_id())
        shutil.copytree(DEFAULT_SNAPSHOT, destination)
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["snapshot_id"] = destination.name
        observations = pd.read_csv(
            destination / "observations.csv", dtype=str, keep_default_na=False
        )
        mask = (
            (observations.unit_id == "030210564011")
            & (observations.year == "2025")
            & (observations.indicator_id == "1649554")
        )
        row = observations.loc[mask].iloc[0]
        observations.loc[mask, ["raw_value", "semantic_value"]] = "1"
        observations.to_csv(destination / "observations.csv", index=False)
        source = destination / row.source_file
        response = json.loads(source.read_text(encoding="utf-8"))
        entry = next(item for item in response["results"] if str(item["id"]) == row.unit_id)
        next(item for item in entry["values"] if int(item["year"]) == 2025)["val"] = 1
        source.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
        sidecar = source.with_suffix(".json.meta.json")
        if sidecar.exists():
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            metadata["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        manifest["files"] = {
            name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
            for name in manifest["files"]
        }
        manifest["fixture_basis"] = "synthetic lifecycle regression; no live GUS request"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        sid = import_snapshot(URL, destination)
        PROBE.parent.mkdir(parents=True, exist_ok=True)
        PROBE.write_text(json.dumps({"snapshot_id": sid}), encoding="utf-8")
        print("PASS: synthetic newer B activated", sid)
    elif stage == "assert-preserved":
        expected = json.loads(PROBE.read_text(encoding="utf-8"))["snapshot_id"]
        dataset = load_database(URL)
        assert dataset.snapshot_id == expected
        row = dataset.observations.loc[
            (dataset.observations.unit_id == "030210564011")
            & (dataset.observations.year == 2025)
            & (dataset.observations.indicator_id == "1649554")
        ].iloc[0]
        assert row.semantic_value == 1
        print("PASS: B and changed value retained across Compose down/up", expected)
    elif stage == "activate-seed":
        sid = import_snapshot(URL, DEFAULT_SNAPSHOT)
        assert load_database(URL).snapshot_id == sid
        print("PASS: explicit activation of seed A", sid)
    else:
        raise ValueError("Unknown lifecycle probe stage")


if __name__ == "__main__":
    main()
