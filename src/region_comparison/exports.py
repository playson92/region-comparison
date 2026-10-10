"""UTF-8 BOM CSV and complete reproducible scenario definitions."""

import hashlib
import json

from region_comparison.config import (
    COMPONENTS,
    METHODOLOGY_VERSION,
    SOURCE_METRICS,
    read_indicators,
)
from region_comparison.scoring import SCORE_PRECISION


def dataset_fingerprint(dataset) -> str:
    """Canonical adapter-independent content digest; metadata identity alone is insufficient."""
    observations = dataset.observations.copy()
    observations["semantic_value"] = observations["semantic_value"].astype(float)
    observations["year"] = observations["year"].astype(int)
    payload = {
        "units": json.loads(dataset.units.sort_values("bdl_unit_id").to_json(orient="records")),
        "observations": json.loads(
            observations.sort_values(["unit_id", "year", "indicator_id"]).to_json(
                orient="records", double_precision=15
            )
        ),
        "indicators": sorted(dataset.indicators, key=lambda item: str(item["indicator_id"])),
        "attributes": sorted(dataset.attributes, key=lambda item: str(item["id"])),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def scenario_config(dataset, result, selected_ids) -> dict:
    return {
        "export_schema_version": "1.0",
        "snapshot_id": dataset.manifest["snapshot_id"],
        "snapshot_manifest": dataset.manifest,
        "dataset_sha256": dataset_fingerprint(dataset),
        "methodology_version": METHODOLOGY_VERSION,
        "year": result.year,
        "selected_ids": list(selected_ids),
        "cohort_ids": list(result.cohort_ids),
        "cohort_sha256": hashlib.sha256("\n".join(result.cohort_ids).encode()).hexdigest(),
        "weights": result.weights,
        "components": COMPONENTS,
        "score_precision": SCORE_PRECISION,
        "tie_rule": "descending min/max rank of score rounded to 6 decimals",
        "normalization": "(average_rank - 1) / (N - 1); constant = 0.5",
        "source_metrics": SOURCE_METRICS,
        "indicator_definitions": dataset.indicators,
        "derived_definitions": read_indicators()["derived"],
        "attributes": dataset.attributes,
        "source": "GUS Bank Danych Lokalnych; https://bdl.stat.gov.pl/api/v1/",
    }


def export_config(dataset, result, selected_ids) -> bytes:
    return json.dumps(
        scenario_config(dataset, result, selected_ids),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")


def export_csv(dataset, metrics, result, selected_ids) -> bytes:
    """Source cells with raw quality and local measures, all for the selected year."""
    source = dataset.observations.copy()
    source["unit_id"] = source["unit_id"].astype(str)
    source["indicator_id"] = source["indicator_id"].astype(str)
    source = source.loc[source.unit_id.isin(selected_ids) & (source.year == result.year)]
    definitions = {str(item["indicator_id"]): item for item in dataset.indicators}
    for column, metadata in (
        ("source_metric_id", "metric_id"),
        ("source_unit", "unit"),
        ("source_original_name", "original_name"),
        ("source_definition", "definition"),
        ("source_reference_period", "reference_period"),
    ):
        source[column] = source.indicator_id.map(lambda iid, key=metadata: definitions[iid][key])
    values = metrics.loc[metrics.year == result.year]
    output = source.merge(values, on=["unit_id", "year"], how="left", validate="many_to_one")
    analytical = ["unit_id", "eligible", "eligibility_reason", "score", "rank_min", "rank_max"]
    analytical += [f"{m}_{suffix}" for m in COMPONENTS for suffix in ("percentile", "contribution")]
    available = [c for c in analytical if c in result.frame]
    output = output.merge(result.frame[available], on="unit_id", how="left", validate="many_to_one")
    output["snapshot_id"] = dataset.manifest["snapshot_id"]
    output["methodology_version"] = METHODOLOGY_VERSION
    output["source_url"] = "https://bdl.stat.gov.pl/api/v1/"
    output["scenario_weights"] = json.dumps(result.weights, sort_keys=True)
    output["derived_definitions"] = json.dumps(read_indicators()["derived"], ensure_ascii=False)
    # pandas emits an empty cell for NA; true zero remains 0.0.
    return output.to_csv(index=False, sep=";", na_rep="").encode("utf-8-sig")


def replay_config(dataset, config: dict):
    from region_comparison.metrics import build_metrics
    from region_comparison.scoring import evaluate

    if config["snapshot_id"] != dataset.manifest["snapshot_id"]:
        raise ValueError("Snapshot does not match exported configuration")
    if config["methodology_version"] != METHODOLOGY_VERSION:
        raise ValueError("Unsupported methodology version")
    if config.get("snapshot_manifest") != dataset.manifest or config.get(
        "dataset_sha256"
    ) != dataset_fingerprint(dataset):
        raise ValueError("Snapshot content differs from exported configuration")
    if (
        config.get("derived_definitions") != read_indicators()["derived"]
        or config.get("components") != COMPONENTS
    ):
        raise ValueError("Analytical definitions differ from exported configuration")
    metrics = build_metrics(dataset)
    result = evaluate(metrics, config["year"], config["weights"])
    if list(result.cohort_ids) != config["cohort_ids"]:
        raise ValueError("Reference cohort differs from exported configuration")
    return result
