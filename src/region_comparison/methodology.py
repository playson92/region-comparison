"""Canonical declarations of the formulas and method actually implemented in Python."""

import hashlib
import json

from region_comparison.config import (
    COMPONENTS,
    METHODOLOGY_VERSION,
    SOURCE_METRICS,
    read_indicators,
)

EXPORT_SCHEMA_VERSION = "1.1"
SCORE_PRECISION = 6
RATIO_TOLERANCE = 0.500000001  # GUS publishes this indicator rounded to integer places/1000.
NORMALIZATION = "(average_rank - 1) / (N - 1); constant = 0.5"
TIE_RULE = "descending min/max rank of score rounded to 6 decimals"
DERIVED = {
    "children_share_pct": {
        "formula": "100 * children_0_2 / population_total",
        "input_ids": ["453372", "453371"],
        "numerator": "453372",
        "denominator": "453371",
        "unit": "%",
    },
    "care_facilities": {
        "formula": "nurseries + child_clubs",
        "input_ids": ["377234", "377225"],
        "numerator": ["377234", "377225"],
        "denominator": None,
        "unit": "placówki",
    },
    "places_per_1000": {
        "formula": "1000 * care_places / children_0_2",
        "input_ids": ["1649554", "453372"],
        "numerator": "1649554",
        "denominator": "453372",
        "unit": "miejsca / 1000 dzieci",
        "cross_check_id": "1649860",
        "cross_check_absolute_tolerance": RATIO_TOLERANCE,
    },
}

MISSING_POLICY = (
    "Require every input semantically valid; nonpositive denominator is NULL; "
    "never impute or clamp ratios."
)
DERIVED_SEMANTICS = {
    "children_share_pct": ("0–2 inclusive", "none", "higher indicates stronger demographic signal"),
    "care_facilities": (
        "not applicable",
        "nurseries and children's clubs; excludes day carers",
        "profile only",
    ),
    "places_per_1000": (
        "denominator 0–2 inclusive; numerator overall capacity",
        "nurseries and children's clubs; excludes day carers",
        "lower indicates stronger comparative signal",
    ),
}


def validate_derived_definitions(configuration: dict | None = None) -> list[dict]:
    definitions = (configuration or read_indicators())["derived"]
    indexed = {item["metric_id"]: item for item in definitions}
    if len(definitions) != len(DERIVED) or set(indexed) != set(DERIVED):
        raise ValueError("Derived definitions differ from the executed methodology")
    for metric, fields in DERIVED.items():
        age, facilities, direction = DERIVED_SEMANTICS[metric]
        executed = {
            **fields,
            "kind": "derived",
            "missing_policy": MISSING_POLICY,
            "age_scope": age,
            "facility_scope": facilities,
            "direction": direction,
            "reference_period": "31 December",
            "years": [2023, 2024, 2025],
            "level": 6,
            "definition_version": "region-comparison-v1",
        }
        for field, expected in executed.items():
            if indexed[metric].get(field) != expected:
                raise ValueError(f"Unsupported derived definition: {metric}.{field}")
    return definitions


def method_contract() -> dict:
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "components": COMPONENTS,
        "score_precision": SCORE_PRECISION,
        "tie_rule": TIE_RULE,
        "normalization": NORMALIZATION,
        "source_metrics": SOURCE_METRICS,
        "derived_definitions": validate_derived_definitions(),
        "comparison_scope": "all eligible full municipalities of Lower Silesia; fixed per year",
        "eligibility_rule": "all score inputs admissible and finite, independent of weights; N >= 2",
    }


def content_digest(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def methodology_fingerprint() -> str:
    return content_digest(method_contract())
