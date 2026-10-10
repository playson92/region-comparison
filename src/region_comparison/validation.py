"""Source semantics and explicit, non-imputing dataset quality checks."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

ADMISSIBLE_STATUSES = frozenset({"valid", "true_zero"})
QUALITY_STATUSES = ADMISSIBLE_STATUSES | frozenset(
    {
        "missing",
        "unavailable",
        "below_precision",
        "incomplete",
        "definition_mismatch",
        "comparability_break",
        "low_precision",
        "preliminary",
        "unknown_attribute",
    }
)

# These codes are taken from the versioned BDL attribute dictionary bundled with a snapshot.
# Combined source meanings remain combined; they do not identify a specific disclosure cause.
ATTRIBUTE_RULES: dict[str, tuple[str, str]] = {
    "0": ("valid", "observed"),
    "1": ("valid", "observed"),
    "3": ("incomplete", "incomplete_aggregate"),
    "4": ("unavailable", "unavailable_or_confidential_or_not_applicable"),
    "7": ("below_precision", "below_presentation_precision"),
    "9": ("preliminary", "preliminary_data"),
    "11": ("comparability_break", "methodology_change"),
    "13": ("comparability_break", "methodology_change_and_incomplete_aggregate"),
    "14": ("comparability_break", "methodology_change_and_unavailable"),
    "15": ("comparability_break", "scope_change"),
    "17": ("comparability_break", "methodology_change_and_below_precision"),
    "20": ("low_precision", "low_precision"),
    "21": ("low_precision", "low_precision"),
    "50": ("missing", "not_yet_available"),
    "91": ("unavailable", "unavailable_or_confidential_or_not_applicable"),
    "94": ("valid", "significant_zero"),
    "97": ("definition_mismatch", "joint_city_and_surrounding_powiat"),
    "98": ("comparability_break", "methodology_change_zero"),
}


def attribute_id(item: dict[str, Any]) -> str:
    return str(item.get("id", item.get("attr_id", item.get("attribute_id", ""))))


def indicator_id(item: dict[str, Any]) -> str:
    return str(item.get("indicator_id", item.get("bdl_variable_id", item.get("id", ""))))


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or bool(pd.isna(value))


def interpret_observation(
    raw_value: Any, raw_attr_id: Any, attributes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Interpret the value/attribute pair; never convert an unavailable zero into a real zero."""
    code = "" if _is_missing(raw_attr_id) else str(raw_attr_id)
    if not code and _is_missing(raw_value):
        return {
            "semantic_value": None,
            "quality_status": "missing",
            "reason_code": "source_value_missing",
        }
    known = {attribute_id(item) for item in attributes}
    if code not in known or code not in ATTRIBUTE_RULES:
        return {
            "semantic_value": None,
            "quality_status": "unknown_attribute",
            "reason_code": "unknown_source_attribute",
        }
    status, reason = ATTRIBUTE_RULES[code]
    if _is_missing(raw_value):
        return {
            "semantic_value": None,
            "quality_status": "missing",
            "reason_code": "source_value_missing" if status == "valid" else reason,
        }
    try:
        numeric = float(raw_value)
    except (ValueError, TypeError):
        return {
            "semantic_value": None,
            "quality_status": "missing",
            "reason_code": "non_numeric_source_value",
        }
    if not math.isfinite(numeric):
        return {
            "semantic_value": None,
            "quality_status": "missing",
            "reason_code": "non_finite_source_value",
        }
    if code in {"0", "94"} and numeric != 0:
        return {
            "semantic_value": None,
            "quality_status": "definition_mismatch",
            "reason_code": "zero_attribute_nonzero_value",
        }
    if status in ADMISSIBLE_STATUSES | {"low_precision", "preliminary"}:
        if status == "valid" and numeric == 0:
            status, reason = "true_zero", "observed_zero"
        return {"semantic_value": numeric, "quality_status": status, "reason_code": reason}
    return {"semantic_value": None, "quality_status": status, "reason_code": reason}


@dataclass
class ValidationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": self.counts,
        }


def validate_dataset(dataset: Any, require_complete: bool = True) -> ValidationReport:
    """Validate response completeness separately from authentic source-value missingness."""
    errors: list[str] = []
    warnings: list[str] = []
    manifest, units, observations = dataset.manifest, dataset.units, dataset.observations
    state = manifest.get("state", manifest.get("status", manifest.get("import_state")))
    if require_complete and state != "complete":
        errors.append(f"Snapshot state is {state!r}; a complete download is required.")
    unit_required = {"bdl_unit_id", "name", "kind"}
    obs_required = {
        "unit_id",
        "year",
        "indicator_id",
        "raw_value",
        "raw_attr_id",
        "semantic_value",
        "quality_status",
        "reason_code",
        "source_file",
        "source_record",
    }
    if not unit_required.issubset(units.columns):
        errors.append(f"Missing unit columns: {sorted(unit_required - set(units.columns))}")
    if not obs_required.issubset(observations.columns):
        errors.append(
            f"Missing observation columns: {sorted(obs_required - set(observations.columns))}"
        )
    if errors and (
        not unit_required.issubset(units.columns) or not obs_required.issubset(observations.columns)
    ):
        return ValidationReport(False, errors)
    unit_ids = set(units["bdl_unit_id"].astype(str))
    if len(units) != len(unit_ids):
        errors.append("Duplicate BDL unit identifiers.")
    if not units["kind"].astype(str).isin({"1", "2", "3"}).all():
        errors.append(
            "Only complete gminas of kinds 1/2/3 are in the reference region; parts 4/5 are excluded."
        )
    if not units["bdl_unit_id"].astype(str).str.fullmatch(r"\d{12}").all():
        errors.append("Invalid BDL unit identifier; identifiers must retain 12 digits.")
    expected_units = manifest.get("unit_ids", manifest.get("selected_units"))
    if expected_units is not None and set(map(str, expected_units)) != unit_ids:
        errors.append("Unit dictionary differs from the manifest's regional scope.")
    expected_count = manifest.get("unit_count", manifest.get("expected_unit_count"))
    if expected_count is not None and len(units) != int(expected_count):
        errors.append("Regional unit count differs from manifest.")
    definitions = {indicator_id(item): item for item in dataset.indicators}
    if len(definitions) != len(dataset.indicators) or "" in definitions:
        errors.append("Indicator definitions have missing or duplicated identifiers.")
    selected_indicators = manifest.get("indicator_ids", manifest.get("selected_variables"))
    if selected_indicators is not None and set(map(str, selected_indicators)) != set(definitions):
        errors.append("Indicator definitions differ from the manifest's selected variables.")
    attrs = {attribute_id(item) for item in dataset.attributes}
    if len(attrs) != len(dataset.attributes) or "" in attrs:
        errors.append("Attribute dictionary has missing or duplicated identifiers.")
    obs = observations.copy()
    for column in ("unit_id", "indicator_id", "raw_attr_id"):
        obs[column] = obs[column].fillna("").astype(str)
    if obs.duplicated(["unit_id", "year", "indicator_id"]).any():
        errors.append("Duplicate unit/year/indicator observations.")
    if not set(obs["unit_id"]).issubset(unit_ids):
        errors.append("Observations reference units outside the region dictionary.")
    if not set(obs["indicator_id"]).issubset(definitions):
        errors.append("Observations reference missing indicator definitions.")
    if not (set(obs["raw_attr_id"]) - {""}).issubset(attrs):
        errors.append("Observations contain attributes absent from their source dictionary.")
    years = set(map(int, manifest.get("years", [])))
    parsed_years = pd.to_numeric(obs["year"], errors="coerce")
    if parsed_years.isna().any() or ((parsed_years % 1) != 0).any():
        errors.append("Observation years must be integers.")
    elif not set(parsed_years.astype(int)).issubset(years):
        errors.append("Observations contain years outside the manifest.")
    numeric = pd.to_numeric(obs["semantic_value"], errors="coerce")
    nonempty = obs["semantic_value"].notna() & (obs["semantic_value"].astype(str) != "")
    if (nonempty & numeric.isna()).any() or numeric.dropna().map(
        lambda v: not math.isfinite(v)
    ).any():
        errors.append("Semantic values must be finite numbers or NULL.")
    if (numeric.dropna() < 0).any():
        errors.append("Negative counts or rates are invalid in this indicator contract.")
    if not set(obs["quality_status"]).issubset(QUALITY_STATUSES):
        errors.append("Unknown quality status.")
    semantic_errors = 0
    for row in obs.itertuples(index=False):
        expected = interpret_observation(row.raw_value, row.raw_attr_id, dataset.attributes)
        actual = None if _is_missing(row.semantic_value) else float(row.semantic_value)
        if (
            actual != expected["semantic_value"]
            or row.quality_status != expected["quality_status"]
            or row.reason_code != expected["reason_code"]
        ):
            semantic_errors += 1
    if semantic_errors:
        errors.append(
            f"{semantic_errors} value/attribute interpretations disagree with source semantics."
        )
    if (obs["quality_status"] == "unknown_attribute").any():
        errors.append("Unknown source attributes cannot be activated.")
    for iid, definition in definitions.items():
        declared = definition.get("years")
        if declared is not None:
            used = set(
                pd.to_numeric(obs.loc[obs.indicator_id == iid, "year"], errors="coerce")
                .dropna()
                .astype(int)
            )
            if not used.issubset(set(map(int, declared))):
                errors.append(f"Indicator {iid} is used outside its definition years.")
    expected_cells = len(units) * len(years) * len(definitions)
    if len(obs) != expected_cells:
        errors.append(
            f"Observation grid is incomplete: expected {expected_cells}, received {len(obs)}."
        )
    if obs[["source_file", "source_record", "reason_code"]].isna().any().any():
        errors.append("Missing observation provenance or reason codes.")
    manifest_files = manifest.get("files", manifest.get("file_hashes"))
    if manifest_files is not None:
        covered = (
            set(manifest_files)
            if isinstance(manifest_files, dict)
            else {item["path"] for item in manifest_files}
        )
        if not set(obs["source_file"]).issubset(covered):
            errors.append("Observation provenance references files outside the verified manifest.")
    pages_expected = manifest.get("pages_expected")
    pages_received = manifest.get("pages_received")
    if pages_expected is not None and pages_expected != pages_received:
        errors.append("Not all expected API pages were downloaded.")
    counts = {
        "units": len(units),
        "years": len(years),
        "indicators": len(definitions),
        "observations": len(obs),
        "expected_observations": expected_cells,
        "admissible_observations": int(obs.quality_status.isin(ADMISSIBLE_STATUSES).sum()),
        "quality_statuses": dict(Counter(obs.quality_status)),
        "reason_codes": dict(Counter(obs.reason_code)),
    }
    if counts["admissible_observations"] != len(obs):
        warnings.append(
            "Authentic flagged/missing observations are retained and block dependent analysis."
        )
    return ValidationReport(not errors, errors, warnings, counts)
