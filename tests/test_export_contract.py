import json
from copy import deepcopy

import pandas as pd
import pytest

from region_comparison.config import DEFAULT_SNAPSHOT, read_indicators
from region_comparison.exports import export_config, replay_config
from region_comparison.methodology import validate_derived_definitions
from region_comparison.metrics import build_metrics
from region_comparison.scoring import evaluate
from region_comparison.storage import load_snapshot


@pytest.fixture(scope="module")
def scenario():
    dataset = load_snapshot(DEFAULT_SNAPSHOT)
    result = evaluate(build_metrics(dataset), 2025, {"places_per_1000": 0, "children_share_pct": 1})
    return dataset, result, json.loads(export_config(dataset, result, list(result.cohort_ids[:4])))


def test_replay_preserves_components_weights_cohort_and_ties(scenario):
    dataset, result, configuration = scenario
    actual = replay_config(dataset, configuration)
    pd.testing.assert_frame_equal(actual.frame, result.frame)
    assert actual.weights == result.weights
    assert actual.cohort_ids == result.cohort_ids


@pytest.mark.parametrize("values", [(35, 65), (55, 45), (45, 55), (1, 2), (1e308, 1e308)])
def test_replay_preserves_nontrivial_normalized_weights_exactly(values):
    dataset = load_snapshot(DEFAULT_SNAPSHOT)
    result = evaluate(
        build_metrics(dataset),
        2025,
        dict(zip(("places_per_1000", "children_share_pct"), values, strict=True)),
    )
    configuration = json.loads(export_config(dataset, result, list(result.cohort_ids[:3])))
    replayed = replay_config(dataset, configuration)
    assert replayed.weights == result.weights
    pd.testing.assert_frame_equal(replayed.frame, result.frame)


@pytest.mark.parametrize(
    "field,value",
    [
        ("export_schema_version", "999"),
        ("methodology_version", "999"),
        ("score_precision", 2),
        ("normalization", "min-max"),
        ("tie_rule", "first"),
        ("source_metrics", {}),
        ("components", {}),
        ("indicator_definitions", []),
        ("derived_definitions", []),
        ("attributes", []),
        ("cohort_sha256", "0" * 64),
        ("cohort_ids", []),
        ("dataset_sha256", "0" * 64),
        ("snapshot_manifest", {}),
        ("snapshot_id", "other"),
        ("year", 2024),
        ("selected_ids", []),
        ("weights", {"places_per_1000": 1, "children_share_pct": 0}),
        ("methodology_sha256", "0" * 64),
        ("scenario_sha256", "0" * 64),
        ("comparison_scope", "selected"),
        ("eligibility_rule", "zero weight relaxes"),
        ("source", "other"),
    ],
)
def test_each_interpretation_field_is_checked(scenario, field, value):
    dataset, _, original = scenario
    configuration = deepcopy(original)
    configuration[field] = value
    with pytest.raises(ValueError):
        replay_config(dataset, configuration)


def test_unknown_and_missing_fields_rejected(scenario):
    dataset, _, original = scenario
    for configuration in (
        {**original, "unknown_method": "x"},
        {k: v for k, v in original.items() if k != "weights"},
    ):
        with pytest.raises(ValueError):
            replay_config(dataset, configuration)


@pytest.mark.parametrize(
    "metric,field,value",
    [
        ("places_per_1000", "formula", "eval(user_input)"),
        ("children_share_pct", "denominator", "453372"),
        ("care_facilities", "input_ids", ["377234"]),
        ("places_per_1000", "cross_check_absolute_tolerance", 100),
        ("places_per_1000", "missing_policy", "Replace missing inputs with zero."),
        ("children_share_pct", "direction", "lower is higher"),
        ("care_facilities", "facility_scope", "all facilities"),
    ],
)
def test_yaml_formula_contract_must_match_execution(metric, field, value):
    config = read_indicators()
    next(item for item in config["derived"] if item["metric_id"] == metric)[field] = value
    with pytest.raises(ValueError, match="Unsupported derived definition"):
        validate_derived_definitions(config)
