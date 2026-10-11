"""Source-pointer and unit-year regressions using semantically valid retained BDL evidence."""

import hashlib
import json
import runpy
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from region_comparison.paths import ROOT
from region_comparison.provenance import validate_provenance, validate_unit_years
from region_comparison.storage import Dataset, StorageError, load_snapshot
from region_comparison.validation import interpret_observation

UID = "030201011011"
OTHER_UID = "030201011022"


def source_dataset(path: Path, reference: str = "results[0].values[0]") -> Dataset:
    path.mkdir(parents=True)
    source = {
        "variableId": 7,
        "params": {"year": [2023]},
        "pages_expected": 1,
        "pages_received": 1,
        "records_expected": 2,
        "records_received": 2,
        "results": [
            {"id": UID, "values": [{"year": "2023", "val": 3, "attrId": 1}]},
            {"id": OTHER_UID, "values": [{"year": "2023", "val": 0, "attrId": 0}]},
        ],
    }
    attributes = [{"id": code, "name": f"Fixture attribute {code}"} for code in (0, 1, 4)]
    units = [
        {
            "bdl_unit_id": UID,
            "name": "Fixture",
            "kind": "1",
            "validity_basis": "observed_snapshot_coverage",
            "valid_from": 2023,
            "valid_to": 2023,
            "years": [2023],
        }
    ]
    observations = [
        {
            "unit_id": UID,
            "year": 2023,
            "indicator_id": "7",
            "raw_value": 3,
            "raw_attr_id": "1",
            **interpret_observation(3, "1", attributes),
            "source_file": "source.json",
            "source_record": reference,
        }
    ]
    indicators = [{"id": "7", "years": [2023]}]
    for name, contents in (
        ("source.json", source),
        ("units.json", units),
        ("indicators.json", indicators),
        ("attributes.json", attributes),
    ):
        (path / name).write_text(json.dumps(contents), encoding="utf-8")
    pd.DataFrame(observations).to_csv(path / "observations.csv", index=False)
    manifest = {"snapshot_id": "fixture", "state": "complete", "years": [2023]}
    dataset = Dataset(
        manifest, pd.DataFrame(units), pd.DataFrame(observations), indicators, attributes
    )
    save_dataset(path, dataset)
    return dataset


def save_dataset(path: Path, dataset: Dataset) -> None:
    dataset.observations.to_csv(path / "observations.csv", index=False)
    (path / "units.json").write_text(
        json.dumps(dataset.units.to_dict(orient="records")), encoding="utf-8"
    )
    dataset.manifest["files"] = {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in path.iterdir()
        if file.name != "manifest.json"
    }
    (path / "manifest.json").write_text(json.dumps(dataset.manifest), encoding="utf-8")


@pytest.mark.parametrize("reference", ["results[0].values[0]", f"{UID}/2023"])
@pytest.mark.parametrize("raw,attr", [(3, "1"), (0, "0"), (0, "4"), (None, "1")])
def test_both_reference_formats_preserve_zero_flagged_and_null_source_values(
    tmp_path, reference, raw, attr
):
    path = tmp_path / "snapshot"
    dataset = source_dataset(path, reference)
    source = json.loads((path / "source.json").read_text())
    source["results"][0]["values"][0].update(val=raw, attrId=int(attr))
    (path / "source.json").write_text(json.dumps(source), encoding="utf-8")
    for column, value in {
        "raw_value": raw,
        "raw_attr_id": attr,
        **interpret_observation(raw, attr, dataset.attributes),
    }.items():
        dataset.observations.loc[0, column] = value
    save_dataset(path, dataset)
    assert validate_provenance(dataset, path) == []
    assert load_snapshot(path).observations.quality_status.iloc[0] == (
        "valid"
        if raw == 3
        else "true_zero"
        if attr == "0"
        else "unavailable"
        if attr == "4"
        else "missing"
    )


@pytest.mark.parametrize(
    "column,value,message",
    [
        ("source_record", "results[99].values[0]", "cannot be resolved"),
        ("source_record", "results[1].values[0]", "different unit"),
        ("source_record", "../../../secret", "malformed reference"),
        ("source_record", f"{OTHER_UID}/2023", "observation unit/year"),
        ("year", 2024, "different year"),
        ("indicator_id", "8", "different indicator"),
        ("raw_value", 4, "raw_value differs"),
        ("raw_attr_id", "4", "raw_attr_id differs"),
    ],
)
def test_rehashed_invalid_observation_is_rejected_before_activation(
    tmp_path, column, value, message
):
    path = tmp_path / "snapshot"
    dataset = source_dataset(path)
    dataset.observations.loc[0, column] = value
    save_dataset(path, dataset)  # Every file hash is correct; source semantics still disagree.
    with pytest.raises(StorageError, match=message):
        load_snapshot(path)


@pytest.mark.parametrize("absence", ["unit", "year"])
def test_documented_absence_after_complete_pagination_is_allowed(tmp_path, absence):
    path = tmp_path / "snapshot"
    dataset = source_dataset(path)
    source = json.loads((path / "source.json").read_text())
    if absence == "unit":
        source["results"].pop(0)
        source.update(records_expected=1, records_received=1)
        suffix = "unit absent in complete response"
    else:
        source["results"][0]["values"] = []
        suffix = "year absent in complete unit response"
    (path / "source.json").write_text(json.dumps(source), encoding="utf-8")
    dataset.observations.loc[0, "source_record"] = f"{UID}/2023 ({suffix})"
    for column, value in {
        "raw_value": None,
        "raw_attr_id": None,
        **interpret_observation(None, None, dataset.attributes),
    }.items():
        dataset.observations.loc[0, column] = value
    save_dataset(path, dataset)
    assert validate_provenance(dataset, path) == []
    assert load_snapshot(path).observations.quality_status.iloc[0] == "missing"
    source["pages_received"] = 0
    (path / "source.json").write_text(json.dumps(source), encoding="utf-8")
    save_dataset(path, dataset)
    with pytest.raises(StorageError, match="complete-pagination evidence"):
        load_snapshot(path)


@pytest.mark.parametrize("mutation", ["existing", "unrequested_year", "wrong_status"])
def test_absence_claim_cannot_hide_existing_values_or_incomplete_request(tmp_path, mutation):
    path = tmp_path / "snapshot"
    dataset = source_dataset(path, f"{UID}/2023 (year absent in complete unit response)")
    source = json.loads((path / "source.json").read_text())
    if mutation != "existing":
        source["results"][0]["values"] = []
    if mutation == "unrequested_year":
        source["params"]["year"] = [2024]
    if mutation != "wrong_status":
        for column, value in {
            "raw_value": None,
            "raw_attr_id": None,
            **interpret_observation(None, None, dataset.attributes),
        }.items():
            dataset.observations.loc[0, column] = value
    (path / "source.json").write_text(json.dumps(source), encoding="utf-8")
    save_dataset(path, dataset)
    assert validate_provenance(dataset, path)
    with pytest.raises(StorageError):
        load_snapshot(path)


@pytest.mark.parametrize("total_records", [2, "1", True, None])
def test_documented_absence_rejects_conflicting_or_invalid_source_total_records(
    tmp_path, total_records
):
    path = tmp_path / "snapshot"
    dataset = source_dataset(path)
    source = json.loads((path / "source.json").read_text())
    source["results"].pop(0)
    source.update(records_expected=1, records_received=1, totalRecords=total_records)
    (path / "source.json").write_text(json.dumps(source), encoding="utf-8")
    dataset.observations.loc[0, "source_record"] = f"{UID}/2023 (unit absent in complete response)"
    for column, value in {
        "raw_value": None,
        "raw_attr_id": None,
        **interpret_observation(None, None, dataset.attributes),
    }.items():
        dataset.observations.loc[0, column] = value
    save_dataset(path, dataset)
    with pytest.raises(StorageError, match="complete-pagination evidence"):
        load_snapshot(path)
    source["totalRecords"] = 1
    (path / "source.json").write_text(json.dumps(source), encoding="utf-8")
    save_dataset(path, dataset)
    assert load_snapshot(path).observations.quality_status.iloc[0] == "missing"


@pytest.mark.parametrize("mutation", ["declared_years", "lower_bound", "upper_bound"])
def test_unit_declared_data_coverage_rejects_conflicting_observation_years(tmp_path, mutation):
    path = tmp_path / "snapshot"
    dataset = source_dataset(path)
    if mutation == "declared_years":
        dataset.units.at[0, "years"] = [2024]
    elif mutation == "lower_bound":
        dataset.units.at[0, "valid_from"] = 2024
    else:
        dataset.units.at[0, "valid_to"] = 2022
    assert validate_unit_years(dataset)
    save_dataset(path, dataset)
    with pytest.raises(StorageError, match="declared data"):
        load_snapshot(path)


def test_observed_coverage_and_metadata_coverage_keep_their_distinct_meaning(tmp_path):
    dataset = source_dataset(tmp_path / "snapshot")
    assert validate_unit_years(dataset) == []  # Only the data year is asserted.
    metadata = deepcopy(dataset)
    metadata.units.at[0, "validity_basis"] = "unit_metadata_years"
    metadata.units.at[0, "valid_from"] = 1995
    metadata.units.at[0, "valid_to"] = 2025
    assert validate_unit_years(metadata) == []


def test_builder_creates_fresh_identities_without_modifying_versioned_inputs(tmp_path, monkeypatch):
    build = runpy.run_path(str(ROOT / "data" / "sample" / "build_sample.py"))["main"]
    inputs = [
        path
        for path in (ROOT / "data" / "sample").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ] + [ROOT / "config" / "indicators.yml"]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    monkeypatch.chdir(tmp_path)
    first, second = build(), build(tmp_path / "second")
    left, right = load_snapshot(first), load_snapshot(second)
    assert first.is_relative_to(ROOT / "output") and second.is_relative_to(ROOT / "output")
    assert first.parent == ROOT / "output" / "snapshots"
    assert left.snapshot_id != right.snapshot_id
    pd.testing.assert_frame_equal(left.observations, right.observations)
    source_manifest = json.loads((ROOT / "data" / "sample" / "manifest.json").read_text())
    assert left.manifest["source_snapshot_id"] == source_manifest["snapshot_id"]
    assert left.manifest["assembly_performed_network_requests"] is False
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    with pytest.raises(FileExistsError):
        build(first)
    with pytest.raises(ValueError, match="inside project output"):
        build(ROOT / "docs" / "bad-snapshot")
