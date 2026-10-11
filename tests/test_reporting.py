"""Correctly interpreted fixture cells exercise missingness rather than synthetic NaN alone."""

import re

import pytest

from region_comparison.config import DEFAULT_SNAPSHOT, SOURCE_METRICS
from region_comparison.reporting import findings, write_quality
from region_comparison.storage import load_snapshot
from region_comparison.validation import interpret_observation, validate_dataset


@pytest.fixture
def dataset():
    data = load_snapshot(DEFAULT_SNAPSHOT)
    return data


def set_cell(data, name, year, metric, raw, attribute):
    uid = data.units.loc[data.units.name == name, "bdl_unit_id"].iloc[0]
    mask = (
        (data.observations.unit_id == uid)
        & (data.observations.year == year)
        & (data.observations.indicator_id == SOURCE_METRICS[metric])
    )
    interpreted = interpret_observation(raw, attribute, data.attributes)
    for key, value in {"raw_value": raw, "raw_attr_id": attribute, **interpreted}.items():
        data.observations.loc[mask, key] = value


@pytest.mark.parametrize("years", [(2023,), (2025,), (2023, 2025), (2024,)])
def test_missing_children_at_endpoints_and_middle(dataset, tmp_path, years):
    for year in years:
        set_cell(dataset, "Wrocław", year, "children_0_2", None, None)
    assert validate_dataset(dataset).valid
    text = findings(dataset)
    assert "brak wartości" in text
    assert "source_value_missing" in text
    assert "trend niepełny lub lata nieporównywalne" in text
    assert "contains missing or flagged observations" in text
    assert not re.search(r"\b(?:nan|inf|traceback)\b", text, re.IGNORECASE)
    write_quality(dataset, tmp_path / "quality.md")
    assert "No excluded source cells" not in (tmp_path / "quality.md").read_text("utf-8")


def test_true_zero_baseline_and_missing_places(dataset):
    set_cell(dataset, "Wrocław", 2023, "children_0_2", "0", "0")
    set_cell(dataset, "Wrocław", 2024, "care_places", "0", "4")
    assert validate_dataset(dataset).valid
    text = findings(dataset)
    assert "dzieci 0–2: 0 →" in text
    assert "niewyznaczalna (zero_denominator)" in text
    assert "unavailable_or_confidential_or_not_applicable" in text
    assert not re.search(r"\b(?:nan|inf)\b", text, re.IGNORECASE)


def test_no_qualifying_municipalities(dataset):
    mask = (dataset.observations.year == 2025) & (
        dataset.observations.indicator_id == SOURCE_METRICS["children_0_2"]
    )
    interpreted = interpret_observation(None, None, dataset.attributes)
    for key, value in {"raw_value": None, "raw_attr_id": None, **interpreted}.items():
        dataset.observations.loc[mask, key] = value
    assert validate_dataset(dataset).valid
    text = findings(dataset)
    assert "Qualifying municipalities in 2025: **0**" in text
    assert "scores and ranks unavailable" in text
    assert not re.search(r"\b(?:nan|inf)\b", text, re.IGNORECASE)


def test_empty_analyzed_group_and_empty_grid(dataset):
    dataset.units["name"] = "Other municipality"
    assert "No analyzed demonstration municipalities" in findings(dataset)
    dataset.units = dataset.units.iloc[:0]
    dataset.observations = dataset.observations.iloc[:0]
    text = findings(dataset)
    assert "Qualifying municipalities in 2025: **0**" in text
    assert "brak wartości" in text


def test_complete_snapshot_reports_actual_completeness(dataset):
    text = findings(dataset)
    assert "No excluded source cells in this snapshot" in text
    assert "Qualifying municipalities in 2025: **169**" in text
