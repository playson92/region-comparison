"""Rebuild the public sample from its immutable, downloaded GUS responses.

This script performs no network requests. For live refreshes use the package CLI.
Run with the project's Python interpreter; PyYAML is a locked project dependency.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RAW = HERE / "source_responses"
YEARS = [2023, 2024, 2025]
SOURCES = [
    ("453371", "population_total", "Ludność ogółem", "osoby", "all ages", "none"),
    (
        "453372",
        "children_0_2",
        "Dzieci w wieku 0–2 lata",
        "osoby",
        "0–2 inclusive; excludes age 3",
        "none",
    ),
    (
        "1649554",
        "care_places",
        "Miejsca w żłobkach i klubach",
        "miejsca",
        "facility capacity; not age-specific enrolment",
        "nurseries and children's clubs",
    ),
    (
        "1649557",
        "children_in_care",
        "Dzieci w placówkach · 31 grudnia",
        "osoby",
        "all attendees; not restricted to ages 0–2",
        "nurseries and children's clubs",
    ),
    ("377234", "nurseries", "Żłobki", "placówki", "not applicable", "nurseries"),
    ("377225", "child_clubs", "Kluby dziecięce", "placówki", "not applicable", "children's clubs"),
    (
        "1649860",
        "gus_places_per_1000",
        "Miejsca na 1000 dzieci · GUS",
        "miejsca / 1000 dzieci",
        "denominator ages 0–2; capacity numerator not age-specific",
        "nurseries and children's clubs",
    ),
]


def read(name: str) -> dict:
    return json.loads((RAW / name).read_text(encoding="utf-8-sig"))


def write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    territorial = []
    for page in range(3):
        response = read(f"units-page-{page}.json")
        assert response["totalRecords"] == 294
        territorial.extend(response["results"])
    assert len(territorial) == len({row["id"] for row in territorial}) == 294
    territory_provenance = {
        row["id"]: (f"source_responses/units-page-{page}.json", f"results[{index}]")
        for page in range(3)
        for index, row in enumerate(read(f"units-page-{page}.json")["results"])
    }
    counties = {row["id"]: row for row in read("powiats.json")["results"]}
    units = []
    historical = []
    for row in territorial:
        if row["kind"] not in {"1", "2", "3"}:
            continue
        detail_path = RAW / f"unit-{row['id']}.json"
        detail = read(detail_path.name) if detail_path.exists() else row
        if "years" in detail and not all(year in detail["years"] for year in YEARS):
            historical.append(row["id"])
            continue
        units.append(
            {
                "bdl_unit_id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "parent_id": row["parentId"],
                "powiat": counties[row["parentId"]]["name"],
                "valid_from": min(detail.get("years", YEARS)),
                "valid_to": max(detail.get("years", YEARS)),
                "validity_basis": "unit_metadata_years"
                if "years" in detail
                else "observed_snapshot_coverage",
                "years": YEARS,
                "teryt": None,
                "description": detail.get("description", ""),
                "source_file": f"source_responses/unit-{row['id']}.json"
                if detail_path.exists()
                else territory_provenance[row["id"]][0],
                "source_record": "$"
                if detail_path.exists()
                else territory_provenance[row["id"]][1],
            }
        )
    units.sort(key=lambda row: row["bdl_unit_id"])
    assert len(units) == 169 and len(historical) == 9
    unit_ids = {row["bdl_unit_id"] for row in units}
    observations = []
    indicators = []
    pages = []
    for indicator_id, metric_id, label, display_unit, age, facility in SOURCES:
        metadata = read(f"variable-{indicator_id}.json")
        assert metadata["level"] == 6 and all(year in metadata["years"] for year in YEARS)
        subject = metadata["subjectId"]
        indicators.append(
            {
                "indicator_id": indicator_id,
                "id": indicator_id,
                "metric_id": metric_id,
                "kind": "source",
                "label": label,
                "name": " / ".join(metadata[key] for key in ("n1", "n2", "n3") if key in metadata),
                "original_name": " / ".join(
                    metadata[key] for key in ("n1", "n2", "n3") if key in metadata
                ),
                "source_dimensions": {
                    key: metadata[key] for key in ("n1", "n2", "n3") if key in metadata
                },
                "subject_id": subject,
                "topic_path": ["K3", "G7", subject]
                if subject == "P3447"
                else ["K22", "G266", subject],
                "definition": label
                + "; "
                + age
                + "; both sexes; full municipality; year-end stock.",
                "unit": display_unit,
                "measure_unit_id": metadata["measureUnitId"],
                "original_unit": metadata["measureUnitName"],
                "age_scope": age,
                "sex_scope": "both sexes",
                "facility_scope": facility,
                "territorial_basis": "residents"
                if subject == "P3447"
                else "location of facility, not residence of attendees",
                "reference_period": "31 December",
                "years": YEARS,
                "source_available_years": metadata["years"],
                "level": 6,
                "definition_version": "gus-bdl-2026-10-10",
                "source_url": f"https://bdl.stat.gov.pl/api/v1/variables/{indicator_id}?format=json",
                "metadata_url": f"https://bdl.stat.gov.pl/bdl/metadane/cechy/{subject[1:]}",
                "attribute_policy": "bdl-attributes-v1; accept only unflagged 0/1 or verified significant zero 94 for scoring",
                "rationale": "demographic context"
                if subject == "P3447"
                else "institutional care profile"
                if subject == "P3219"
                else "independent rounded cross-check of the local ratio",
                "source_file": f"source_responses/variable-{indicator_id}.json",
            }
        )
        collected = []
        for page in range(3):
            source_file = f"source_responses/data-{indicator_id}-page-{page}.json"
            response = read(Path(source_file).name)
            assert response["totalRecords"] == 285
            collected.extend(response["results"])
            meta = read(Path(source_file).name + ".meta.json")
            pages.append(
                {
                    **meta,
                    "file": source_file,
                    "page": page,
                    "records_expected_total": 285,
                    "records_received": len(response["results"]),
                    "variable_id": indicator_id,
                }
            )
            for record_index, record in enumerate(response["results"]):
                if record["id"] not in unit_ids:
                    continue
                for value_index, value in enumerate(record["values"]):
                    assert value["attrId"] in (0, 1), "Unexpected source flag requires review"
                    raw_value = value["val"]
                    assert raw_value >= 0
                    observations.append(
                        {
                            "unit_id": record["id"],
                            "year": int(value["year"]),
                            "indicator_id": indicator_id,
                            "raw_value": raw_value,
                            "raw_attr_id": value["attrId"],
                            "semantic_value": raw_value,
                            "quality_status": "true_zero" if raw_value == 0 else "valid",
                            "reason_code": "observed_zero" if raw_value == 0 else "observed",
                            "source_file": source_file,
                            "source_record": f"results[{record_index}].values[{value_index}]",
                        }
                    )
        assert len(collected) == len({row["id"] for row in collected}) == 285
        assert unit_ids <= {row["id"] for row in collected}
    assert len(observations) == 169 * 3 * 7
    assert len({(row["unit_id"], row["year"], row["indicator_id"]) for row in observations}) == len(
        observations
    )
    observations.sort(key=lambda row: (row["unit_id"], row["year"], row["indicator_id"]))
    with (HERE / "observations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(observations[0]))
        writer.writeheader()
        writer.writerows(observations)
    derived = [
        {
            "metric_id": "children_share_pct",
            "kind": "derived",
            "label": "Udział dzieci 0–2",
            "formula": "100 * children_0_2 / population_total",
            "input_ids": ["453372", "453371"],
            "numerator": "453372",
            "denominator": "453371",
            "unit": "%",
            "age_scope": "0–2 inclusive",
            "facility_scope": "none",
            "reference_period": "31 December",
            "direction": "higher indicates stronger demographic signal",
        },
        {
            "metric_id": "care_facilities",
            "kind": "derived",
            "label": "Placówki opieki łącznie",
            "formula": "nurseries + child_clubs",
            "input_ids": ["377234", "377225"],
            "numerator": ["377234", "377225"],
            "denominator": None,
            "unit": "placówki",
            "age_scope": "not applicable",
            "facility_scope": "nurseries and children's clubs; excludes day carers",
            "reference_period": "31 December",
            "direction": "profile only",
        },
        {
            "metric_id": "places_per_1000",
            "kind": "derived",
            "label": "Miejsca na 1000 dzieci 0–2",
            "formula": "1000 * care_places / children_0_2",
            "input_ids": ["1649554", "453372"],
            "numerator": "1649554",
            "denominator": "453372",
            "unit": "miejsca / 1000 dzieci",
            "age_scope": "denominator 0–2 inclusive; numerator overall capacity",
            "facility_scope": "nurseries and children's clubs; excludes day carers",
            "reference_period": "31 December",
            "direction": "lower indicates stronger comparative signal",
            "cross_check_id": "1649860",
            "cross_check_absolute_tolerance": 0.500000001,
        },
    ]
    for metric in derived:
        metric["missing_policy"] = (
            "Require every input semantically valid; nonpositive denominator is NULL; never impute or clamp ratios."
        )
        metric["years"] = YEARS
        metric["level"] = 6
        metric["definition_version"] = "region-comparison-v1"
    write("units.json", units)
    write("indicators.json", indicators)
    write("attributes.json", read("attributes.json")["results"])
    wide = {}
    for row in observations:
        wide.setdefault((row["unit_id"], row["year"]), {})[row["indicator_id"]] = row[
            "semantic_value"
        ]
    differences = [
        abs(1000 * values["1649554"] / values["453372"] - values["1649860"])
        for values in wide.values()
    ]
    assert max(differences) <= 0.500000001
    age_checks = []
    for sample in ("wroclaw", "kobierzyce", "siechnice"):
        response = read(f"sample-{sample}.json")
        sample_values = {
            (str(variable["id"]), int(value["year"])): value
            for variable in response["results"]
            for value in variable["values"]
        }
        for year in YEARS:
            inputs = [sample_values[(str(age_id), year)] for age_id in (71, 72, 73)]
            assert all(value["attrId"] == 1 for value in inputs)
            population_sum = sum(value["val"] for value in inputs)
            population_group = sample_values[("453372", year)]["val"]
            assert population_sum == population_group
            age_checks.append(
                {
                    "unit_id": response["unitId"],
                    "year": year,
                    "age_0_plus_1_plus_2": population_sum,
                    "group_0_2": population_group,
                    "source_file": f"source_responses/sample-{sample}.json",
                    "matches": True,
                }
            )
    yearly_checks = []
    for year in YEARS:
        values = [value for (_, cell_year), value in wide.items() if cell_year == year]
        yearly_checks.append(
            {
                "year": year,
                "municipalities": len(values),
                "zero_care_places": sum(value["1649554"] == 0 for value in values),
                "population_total": sum(value["453371"] for value in values),
                "children_0_2": sum(value["453372"] for value in values),
                "care_places": sum(value["1649554"] for value in values),
                "children_in_care": sum(value["1649557"] for value in values),
                "ratios_above_1000": sum(
                    1000 * value["1649554"] / value["453372"] > 1000 for value in values
                ),
            }
        )
    write(
        "source-verification.json",
        {
            "age_cross_checks": age_checks,
            "ratio_cross_check_count": len(differences),
            "ratio_max_absolute_difference": max(differences),
            "ratio_absolute_tolerance": 0.500000001,
            "ratio_tolerance_basis": "GUS variable 1649860 presents integer values; half a display unit",
            "ratio_cross_check_passed": True,
            "yearly_checks": yearly_checks,
            "missing_source_cells": 0,
        },
    )
    config = {
        "config_version": "1.0.0",
        "region_id": "030200000000",
        "region_name": "Dolnośląskie",
        "years": YEARS,
        "unit_level": 6,
        "accepted_kinds": ["1", "2", "3"],
        "unit_registry": "data/sample/units.json",
        "attributes_path": "data/sample/attributes.json",
        "indicators": indicators,
        "derived": derived,
    }
    (ROOT / "config" / "indicators.yml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )
    write("configuration.json", config)
    metas = []
    for path in RAW.glob("*.meta.json"):
        meta = read(path.name)
        original = path.with_name(path.name.removesuffix(".meta.json"))
        assert meta["sha256"] == sha(original), f"Altered source response: {original.name}"
        params = {}
        for key, value in parse_qsl(urlsplit(meta["url"]).query):
            params.setdefault(key, []).append(value)
        meta["params"] = params
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        metas.append(meta)
    times = sorted(meta["retrieved_at_utc"] for meta in metas)
    files = {
        str(path.relative_to(HERE)).replace("\\", "/"): sha(path)
        for path in sorted(HERE.rglob("*"))
        if path.is_file() and path.name != "manifest.json" and "__pycache__" not in path.parts
    }
    existing_manifest = HERE / "manifest.json"
    assembled_at = (
        json.loads(existing_manifest.read_text(encoding="utf-8"))["assembled_at_utc"]
        if existing_manifest.exists()
        else datetime.now(UTC).isoformat()
    )
    manifest = {
        "manifest_schema_version": "1.0",
        "snapshot_id": "bdl-dolnoslaskie-2023-2025-20261010",
        "state": "complete",
        "status": "complete",
        "started_at_utc": times[0],
        "completed_at_utc": times[-1],
        "assembled_at_utc": assembled_at,
        "region_id": "030200000000",
        "years": YEARS,
        "unit_ids": sorted(unit_ids),
        "unit_count": len(units),
        "indicator_ids": [source[0] for source in SOURCES],
        "indicator_count": len(SOURCES),
        "expected_observation_count": 3549,
        "received_observation_count": len(observations),
        "source_page_count": len(pages),
        "source_pages": pages,
        "source_total_records_per_variable": 285,
        "territorial_dictionary_total_records": 294,
        "excluded_part_count": 116,
        "excluded_historical_unit_ids": historical,
        "attributes_observed": dict(Counter(str(row["raw_attr_id"]) for row in observations)),
        "quality_counts": dict(Counter(row["quality_status"] for row in observations)),
        "missing_observation_count": 0,
        "errors": [],
        "files": files,
        "config_sha256": sha(ROOT / "config" / "indicators.yml"),
        "code_version": "source-contract-v1",
        "data_license": "CC-BY-4.0",
        "attribution": "Source: Statistics Poland (GUS), Local Data Bank (BDL); downloaded 10 October 2026; local derived metrics are identified separately.",
        "source_url": "https://bdl.stat.gov.pl/api/v1/",
        "refresh_uses_cache": True,
    }
    write("manifest.json", manifest)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "snapshot_id",
                    "state",
                    "unit_count",
                    "received_observation_count",
                    "quality_counts",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
