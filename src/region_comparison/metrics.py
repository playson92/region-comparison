"""Strict metric construction: a missing input never becomes zero."""

import math

import pandas as pd

from region_comparison.config import SOURCE_METRICS
from region_comparison.methodology import RATIO_TOLERANCE, validate_derived_definitions

ACCEPTED = frozenset({"valid", "true_zero"})


def strict_sum(values: list[float | None]) -> float | None:
    """Sum ages 0+1+2 or facilities only when every input is finite."""
    if not values or any(v is None or not math.isfinite(float(v)) for v in values):
        return None
    return sum(float(v) for v in values)


def safe_ratio(numerator: float | None, denominator: float | None, scale: float = 1):
    if numerator is None or denominator is None:
        return None, "missing_input"
    if not math.isfinite(float(numerator)) or not math.isfinite(float(denominator)):
        return None, "nonfinite_input"
    if denominator <= 0:
        return None, "zero_denominator" if denominator == 0 else "negative_denominator"
    return scale * numerator / denominator, ""


def validate_ratio_definition(numerator: dict, denominator: dict) -> None:
    """A source ratio must refer to a population age and reference period explicitly."""
    if denominator.get("age") != "0-2":
        raise ValueError("Demographic denominator must exclude children aged 3")
    if numerator.get("reference_period") != denominator.get("reference_period"):
        raise ValueError("Reference periods do not match")
    if numerator.get("facility_type") != "nurseries_and_child_clubs":
        raise ValueError("Facility definitions do not match the childcare contract")


def build_metrics(dataset) -> pd.DataFrame:
    """Return the complete municipality-year grid, retaining per-metric quality."""
    validate_derived_definitions()
    definitions = {str(item["indicator_id"]): item for item in dataset.indicators}
    expected = {
        "population_total": (26, "all ages", "none"),
        "children_0_2": (26, "0–2 inclusive; excludes age 3", "none"),
        "care_places": (
            64,
            "facility capacity; not age-specific enrolment",
            "nurseries and children's clubs",
        ),
        "children_in_care": (
            26,
            "all attendees; not restricted to ages 0–2",
            "nurseries and children's clubs",
        ),
        "nurseries": (35, "not applicable", "nurseries"),
        "child_clubs": (35, "not applicable", "children's clubs"),
        "gus_places_per_1000": (
            1,
            "denominator ages 0–2; capacity numerator not age-specific",
            "nurseries and children's clubs",
        ),
    }
    for metric, (measure, age, facilities) in expected.items():
        definition = definitions.get(SOURCE_METRICS[metric])
        if definition is None:
            raise ValueError(f"Missing required source definition: {metric}")
        contract = (
            definition.get("measure_unit_id"),
            definition.get("age_scope"),
            definition.get("facility_scope"),
            definition.get("reference_period"),
            definition.get("sex_scope"),
            definition.get("level"),
        )
        if contract != (measure, age, facilities, "31 December", "both sexes", 6):
            raise ValueError(f"Incompatible unit, age, facilities or reference period: {metric}")
    for metric, age_dimension in (("children_0_2", "0-2"), ("population_total", "ogółem")):
        if definitions[SOURCE_METRICS[metric]].get("source_dimensions") != {
            "n1": age_dimension,
            "n2": "ogółem",
            "n3": "ogółem",
        }:
            raise ValueError(f"Incompatible source demographic dimensions: {metric}")
    for definition in definitions.values():
        if not set(dataset.years).issubset(set(definition.get("years", []))):
            raise ValueError("Selected years are outside the pinned indicator definition")
    observations = dataset.observations.copy()
    observations["indicator_id"] = observations["indicator_id"].astype(str)
    observations["unit_id"] = observations["unit_id"].astype(str)
    lookup = observations.set_index(["unit_id", "year", "indicator_id"])
    if not lookup.index.is_unique:
        raise ValueError("Duplicate observations in analytical input")
    units = dataset.units.copy()
    id_column = "bdl_unit_id" if "bdl_unit_id" in units else "unit_id"
    years = sorted(int(y) for y in dataset.manifest["years"])
    rows = []
    for unit in units.to_dict("records"):
        unit_id = str(unit[id_column])
        for year in years:
            row = {"unit_id": unit_id, "year": year, "name": unit.get("name", unit_id)}
            for field in ("kind", "powiat", "teryt", "parent_id"):
                row[field] = unit.get(field)
            for metric, indicator_id in SOURCE_METRICS.items():
                key = (unit_id, year, indicator_id)
                if key not in lookup.index:
                    value, status, reason = None, "missing", "source_observation_absent"
                else:
                    source = lookup.loc[key]
                    value = source["semantic_value"]
                    status = str(source["quality_status"])
                    reason = str(source.get("reason_code", "") or "")
                    if reason == "nan":
                        reason = ""
                    if pd.isna(value) or status not in ACCEPTED:
                        value = None
                    else:
                        value = float(value)
                row[metric] = value
                row[f"{metric}_status"] = status
                row[f"{metric}_reason"] = reason
            for metric, numerator, denominator, scale in (
                ("children_share_pct", "children_0_2", "population_total", 100),
                ("places_per_1000", "care_places", "children_0_2", 1000),
            ):
                value, reason = safe_ratio(row[numerator], row[denominator], scale)
                row[metric] = value
                row[f"{metric}_status"] = (
                    "missing" if value is None else "true_zero" if value == 0 else "valid"
                )
                row[f"{metric}_reason"] = reason
                if reason == "missing_input":
                    row[f"{metric}_reason"] += ":" + ";".join(
                        f"{name}={row[f'{name}_status']}:{row[f'{name}_reason']}"
                        for name in (numerator, denominator)
                        if row[name] is None
                    )
            facilities = strict_sum([row["nurseries"], row["child_clubs"]])
            row["care_facilities"] = facilities
            row["care_facilities_status"] = (
                "missing" if facilities is None else "true_zero" if facilities == 0 else "valid"
            )
            row["care_facilities_reason"] = "missing_input" if facilities is None else ""
            if row["places_per_1000"] is not None and row["gus_places_per_1000"] is not None:
                row["ratio_difference"] = row["places_per_1000"] - row["gus_places_per_1000"]
            else:
                row["ratio_difference"] = None
            rows.append(row)
    if rows:
        return pd.DataFrame(rows)
    columns = ["unit_id", "year", "name", "kind", "powiat", "teryt", "parent_id"]
    for metric in [*SOURCE_METRICS, "children_share_pct", "places_per_1000", "care_facilities"]:
        columns.extend([metric, f"{metric}_status", f"{metric}_reason"])
    return pd.DataFrame(columns=[*columns, "ratio_difference"])


def ratio_summary(metrics: pd.DataFrame) -> dict:
    differences = metrics["ratio_difference"].abs().dropna()
    return {
        "paired_cells": len(differences),
        "outside_tolerance": int((differences > RATIO_TOLERANCE).sum()),
        "max_absolute_difference": float(differences.max()) if len(differences) else None,
        "tolerance": RATIO_TOLERANCE,
    }
