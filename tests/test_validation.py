"""Contract tests for authentic zero/missing semantics and reference-region integrity."""

from copy import deepcopy

import pandas as pd
import pytest

from region_comparison.storage import Dataset
from region_comparison.validation import interpret_observation, validate_dataset


@pytest.fixture
def attributes():
    return [
        {"id": code, "name": "source dictionary entry"}
        for code in (0, 1, 3, 4, 7, 9, 11, 13, 14, 15, 17, 20, 21, 50, 91, 94, 97, 98)
    ]


@pytest.mark.parametrize(
    ("raw", "attr", "value", "status", "reason"),
    [
        (0, 0, 0, "true_zero", "observed_zero"),
        (0, 4, None, "unavailable", "unavailable_or_confidential_or_not_applicable"),
        (0, 91, None, "unavailable", "unavailable_or_confidential_or_not_applicable"),
        (0, 7, None, "below_precision", "below_presentation_precision"),
        (123, 11, None, "comparability_break", "methodology_change"),
        (123, 20, 123, "low_precision", "low_precision"),
        (123, 97, None, "definition_mismatch", "joint_city_and_surrounding_powiat"),
        (123, 999, None, "unknown_attribute", "unknown_source_attribute"),
        (None, None, None, "missing", "source_value_missing"),
        (123, 9, 123, "preliminary", "preliminary_data"),
    ],
)
def test_attribute_pair_semantics(attributes, raw, attr, value, status, reason):
    assert interpret_observation(raw, attr, attributes) == {
        "semantic_value": value,
        "quality_status": status,
        "reason_code": reason,
    }


@pytest.fixture
def dataset(attributes):
    units = [
        {"bdl_unit_id": "030201011011", "name": "A", "kind": "1"},
        {"bdl_unit_id": "030201011022", "name": "B", "kind": "2"},
    ]
    observations = [
        {
            "unit_id": unit["bdl_unit_id"],
            "year": 2023,
            "indicator_id": "7",
            "raw_value": 0,
            "raw_attr_id": "0",
            "semantic_value": 0,
            "quality_status": "true_zero",
            "reason_code": "observed_zero",
            "source_file": "source.json",
            "source_record": str(index),
        }
        for index, unit in enumerate(units)
    ]
    return Dataset(
        {
            "snapshot_id": "test",
            "state": "complete",
            "years": [2023],
            "unit_ids": [unit["bdl_unit_id"] for unit in units],
        },
        pd.DataFrame(units),
        pd.DataFrame(observations),
        [{"id": "7", "years": [2023]}],
        attributes,
    )


def test_complete_download_with_authentic_missing_value_is_valid(dataset):
    dataset.observations.loc[
        0, ["raw_value", "raw_attr_id", "semantic_value", "quality_status", "reason_code"]
    ] = [0, "4", None, "unavailable", "unavailable_or_confidential_or_not_applicable"]
    report = validate_dataset(dataset)
    assert report.valid
    assert report.counts["admissible_observations"] == 1
    assert report.counts["reason_codes"]["unavailable_or_confidential_or_not_applicable"] == 1


def test_no_gmina_parts_or_duplicate_names_join(dataset):
    dataset.units.loc[1, "name"] = "A"
    assert validate_dataset(dataset).valid
    dataset.units.loc[1, "kind"] = "4"
    assert not validate_dataset(dataset).valid


@pytest.mark.parametrize(
    "mutation", ["duplicate", "incomplete", "year", "unknown", "wrong_zero", "negative", "partial"]
)
def test_invalid_contracts_block_activation(dataset, mutation):
    dataset = deepcopy(dataset)
    if mutation == "duplicate":
        dataset.observations = pd.concat([dataset.observations, dataset.observations.iloc[[0]]])
    elif mutation == "incomplete":
        dataset.observations = dataset.observations.iloc[:1]
    elif mutation == "year":
        dataset.observations.loc[0, "year"] = 2024
    elif mutation == "unknown":
        dataset.observations.loc[0, "raw_attr_id"] = "999"
    elif mutation == "wrong_zero":
        dataset.observations.loc[0, "raw_attr_id"] = "4"
    elif mutation == "negative":
        dataset.observations.loc[0, "semantic_value"] = -2
    elif mutation == "partial":
        dataset.manifest["state"] = "partial"
    assert not validate_dataset(dataset).valid
