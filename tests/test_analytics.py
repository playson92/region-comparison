import json
import os

import pandas as pd
import pytest

from region_comparison.config import COMPONENTS
from region_comparison.metrics import safe_ratio, strict_sum, validate_ratio_definition
from region_comparison.scoring import apply_weights, evaluate, normalize_weights
from region_comparison.sensitivity import analyze


@pytest.fixture
def metrics():
    return pd.DataFrame(
        {
            "unit_id": ["a", "b", "c", "d"],
            "year": [2025] * 4,
            "places_per_1000": [0.0, 100.0, 100.0, None],
            "children_share_pct": [2.0, 2.0, 2.0, 5.0],
            "places_per_1000_reason": ["", "", "", "missing_source"],
        }
    )


def test_fixed_cohort_zero_weight_ties_constant_and_selection(metrics):
    result = evaluate(metrics, 2025)
    assert result.cohort_ids == ("a", "b", "c")
    assert result.constant_components == ("children_share_pct",)
    frame = result.frame.set_index("unit_id")
    assert frame.loc["a", "score"] == 75
    assert (frame.loc["b", "rank_min"], frame.loc["b", "rank_max"]) == (2, 3)
    assert pd.isna(frame.loc["d", "score"])
    selected = frame.loc[["a", "b"]]
    assert selected.loc["b", "rank_max"] == 3  # Display selection cannot renormalize.
    reweighted = apply_weights(result, dict(zip(COMPONENTS, [0, 1], strict=True)))
    assert reweighted.cohort_ids == result.cohort_ids
    assert not reweighted.frame.set_index("unit_id").loc["d", "eligible"]
    assert reweighted.frame.loc[:2, "rank_min"].tolist() == [1, 1, 1]
    assert reweighted.frame.loc[:2, "rank_max"].tolist() == [3, 3, 3]


@pytest.mark.parametrize("values", [[-1, 2], [0, 0], [float("nan"), 1], [1, float("inf")]])
def test_reject_invalid_weights(values):
    with pytest.raises(ValueError):
        normalize_weights(dict(zip(COMPONENTS, values, strict=True)))


def test_weight_normalization_avoids_finite_input_overflow():
    weights = normalize_weights(dict.fromkeys(COMPONENTS, 1e308))
    assert list(weights.values()) == [0.5, 0.5]


def test_small_reference_set_no_ranking(metrics):
    result = evaluate(metrics.iloc[:1], 2025)
    assert result.frame.score.isna().all()
    assert result.frame.rank_min.isna().all()


def test_sensitivity_deterministic_tie_envelopes(metrics):
    result = evaluate(metrics, 2025)
    first, second = analyze(result), analyze(result)
    pd.testing.assert_frame_equal(first.scenarios, second.scenarios)
    assert first.count == 11
    assert first.summary.set_index("unit_id").loc["a", "rank_max"] == 3
    assert first.pairwise("b", "c") == {"above": 0, "below": 0, "tied": 11, "count": 11}
    assert first.pairwise("a", "b")["above"] == 10
    assert first.pairwise("a", "d")["count"] == 0
    arbitrary = apply_weights(result, dict(zip(COMPONENTS, [1, 2], strict=True)))
    assert analyze(arbitrary).count == 12


def test_ratio_and_complete_sum_contract():
    assert strict_sum([1, None, 2]) is None
    assert strict_sum([0, 0, 0]) == 0
    assert safe_ratio(0, 20, 1000) == (0, "")
    assert safe_ratio(None, 20)[0] is None
    assert safe_ratio(10, 0) == (None, "zero_denominator")
    assert safe_ratio(30, 20, 1000)[0] == 1500
    denominator = {"age": "0-2", "reference_period": "31 December"}
    numerator = {"facility_type": "nurseries_and_child_clubs", "reference_period": "31 December"}
    validate_ratio_definition(numerator, denominator)
    for wrong in [
        {**denominator, "age": "0-3"},
        {**denominator, "reference_period": "annual flow"},
    ]:
        with pytest.raises(ValueError):
            validate_ratio_definition(numerator, wrong)


def test_export_replay_and_statuses():
    from region_comparison.config import DEFAULT_SNAPSHOT
    from region_comparison.exports import export_config, export_csv, replay_config
    from region_comparison.metrics import build_metrics
    from region_comparison.storage import load_snapshot

    dataset = load_snapshot(DEFAULT_SNAPSHOT)
    metrics = build_metrics(dataset)
    result = evaluate(metrics, max(dataset.years))
    selected = list(result.cohort_ids[:3])
    encoded = export_config(dataset, result, selected)
    configuration = json.loads(encoded)
    reproduced = replay_config(dataset, configuration)
    pd.testing.assert_frame_equal(result.frame, reproduced.frame)
    csv = export_csv(dataset, metrics, result, selected)
    assert csv.startswith(b"\xef\xbb\xbf")
    for column in [
        "raw_attr_id",
        "quality_status",
        "reason_code",
        "snapshot_id",
        "places_per_1000",
        "rank_max",
        "scenario_weights",
        "source_unit",
        "source_original_name",
        "derived_definitions",
    ]:
        assert column in csv.decode("utf-8-sig")
    assert configuration["derived_definitions"][0]["formula"]
    # A reused snapshot ID is not proof that the underlying data is unchanged.
    dataset.observations.loc[0, "semantic_value"] += 1
    with pytest.raises(ValueError, match="Snapshot content differs"):
        replay_config(dataset, configuration)


@pytest.mark.parametrize(
    "metric,field,value",
    [
        ("population_total", "reference_period", "30 June"),
        ("population_total", "sex_scope", "female only"),
        ("children_0_2", "age_scope", "0–3 inclusive"),
        ("care_places", "facility_scope", "day carers"),
        ("child_clubs", "facility_scope", "day carers"),
        ("nurseries", "measure_unit_id", 26),
        ("children_in_care", "reference_period", "annual flow"),
        ("gus_places_per_1000", "age_scope", "ages 0–3"),
    ],
)
def test_all_metric_input_definitions_are_checked(metric, field, value):
    from region_comparison.config import DEFAULT_SNAPSHOT
    from region_comparison.metrics import build_metrics
    from region_comparison.storage import load_snapshot

    dataset = load_snapshot(DEFAULT_SNAPSHOT)
    definition = next(item for item in dataset.indicators if item["metric_id"] == metric)
    definition[field] = value
    with pytest.raises(ValueError, match="Incompatible"):
        build_metrics(dataset)


@pytest.mark.postgres
def test_export_configuration_replays_across_real_adapters():
    from region_comparison.config import DEFAULT_SNAPSHOT
    from region_comparison.exports import dataset_fingerprint, export_config, replay_config
    from region_comparison.metrics import build_metrics
    from region_comparison.storage import import_snapshot, load_database, load_snapshot

    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for real PostgreSQL verification")
    from sqlalchemy.engine import make_url

    database = make_url(database_url).database or ""
    assert database.endswith("_test") or database.startswith("test"), "Use a dedicated test DB"
    snapshot = load_snapshot(DEFAULT_SNAPSHOT)
    import_snapshot(database_url, DEFAULT_SNAPSHOT)
    postgres = load_database(database_url, snapshot.snapshot_id)
    assert dataset_fingerprint(snapshot) == dataset_fingerprint(postgres)
    result = evaluate(build_metrics(snapshot), 2025)
    config = json.loads(export_config(snapshot, result, result.cohort_ids[:3]))
    actual = replay_config(postgres, config)
    pd.testing.assert_series_equal(result.frame.score, actual.frame.score)
