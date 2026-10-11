"""Resolve retained BDL evidence and validate declared observation-year coverage."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd

_INDEX_REFERENCE = re.compile(r"results\[(\d+)\]\.values\[(\d+)\]")
_IDENTITY_REFERENCE = re.compile(
    r"(\d{12})/(\d{4})(?: \((unit absent in complete response|"
    r"year absent in complete unit response)\))?"
)


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "") or bool(pd.isna(value))


def _number(value: Any) -> Decimal | None:
    if _missing(value):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("source raw value must be numeric or NULL") from exc
    if not result.is_finite():
        raise ValueError("source raw value must be finite")
    return result


def _code(value: Any) -> str:
    return "" if _missing(value) else str(value)


def validate_unit_years(dataset: Any) -> list[str]:
    """Check data coverage; observed_snapshot_coverage never denotes legal existence dates."""
    errors: list[str] = []
    if not {"unit_id", "year"}.issubset(dataset.observations.columns):
        return errors
    if "bdl_unit_id" not in dataset.units:
        return errors
    for unit in dataset.units.to_dict(orient="records"):
        uid = str(unit["bdl_unit_id"])
        rows = dataset.observations.loc[dataset.observations.unit_id.astype(str) == uid]
        parsed = pd.to_numeric(rows.year, errors="coerce")
        if parsed.isna().any() or ((parsed % 1) != 0).any():
            continue  # The dataset validator reports malformed years separately.
        used = set(parsed.astype(int))
        declared = unit.get("years")
        if isinstance(declared, list):
            try:
                declared_years = {int(year) for year in declared}
            except (TypeError, ValueError):
                errors.append(f"Unit {uid} has invalid declared data years.")
                continue
            if not used.issubset(declared_years):
                errors.append(f"Unit {uid} observations exceed its declared data years.")
        elif declared is not None and not _missing(declared):
            errors.append(f"Unit {uid} declared data years must be a list.")
        basis = unit.get("validity_basis")
        if not _missing(basis) and basis not in {
            "unit_metadata_years",
            "observed_snapshot_coverage",
        }:
            errors.append(f"Unit {uid} has unsupported validity_basis {basis!r}.")
        bounds: dict[str, int] = {}
        for key in ("valid_from", "valid_to"):
            value = unit.get(key)
            if not _missing(value):
                try:
                    numeric = Decimal(str(value))
                    if not numeric.is_finite() or numeric != numeric.to_integral_value():
                        raise ValueError
                    bounds[key] = int(numeric)
                except (InvalidOperation, TypeError, ValueError):
                    errors.append(f"Unit {uid} has invalid {key} data coverage.")
        if bounds.get("valid_from", -1) > bounds.get("valid_to", 10000):
            errors.append(f"Unit {uid} data coverage has reversed bounds.")
        if any(
            year < bounds.get("valid_from", year) or year > bounds.get("valid_to", year)
            for year in used
        ):
            errors.append(f"Unit {uid} observations exceed its declared data coverage bounds.")
    return errors


def _source_indicator(payload: dict[str, Any]) -> str:
    identities = []
    if "variableId" in payload:
        identities.append(str(payload["variableId"]))
    links = payload.get("links", {})
    if not isinstance(links, dict):
        raise ValueError("retained response has malformed links metadata")
    url = payload.get("url") or links.get("self")
    if url:
        match = re.search(r"/data/by-variable/(\d+)/?$", urlsplit(str(url)).path)
        if match:
            identities.append(match[1])
    if not identities or len(set(identities)) != 1:
        raise ValueError("retained response has missing or conflicting variable identity")
    return identities[0]


def _complete_response(payload: dict[str, Any], year: int) -> bool:
    """An absent cell needs evidence of a complete request that included the selected year."""
    results = payload["results"]
    pages = payload.get("pages_expected")
    expected = payload.get("records_expected")
    params = payload.get("params", {})
    if not isinstance(params, dict):
        return False
    requested = params.get("year", [])
    if not isinstance(requested, list):
        requested = [requested]
    try:
        return (
            isinstance(pages, int)
            and pages > 0
            and pages == payload.get("pages_received")
            and isinstance(expected, int)
            and expected >= 0
            and expected == payload.get("records_received") == len(results)
            and (
                "totalRecords" not in payload
                or (
                    isinstance(payload["totalRecords"], int)
                    and not isinstance(payload["totalRecords"], bool)
                    and payload["totalRecords"] == expected
                )
            )
            and year in set(map(int, requested))
        )
    except (TypeError, ValueError):
        return False


def _resolve(
    payload: dict[str, Any], reference: str, uid: str, year: int
) -> tuple[dict[str, Any] | None, str | None]:
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("retained response lacks a results list")
    ids = [str(record.get("id")) for record in results if isinstance(record, dict)]
    if len(ids) != len(results) or len(ids) != len(set(ids)):
        raise ValueError("retained response has malformed or duplicate unit records")
    indexed = _INDEX_REFERENCE.fullmatch(reference)
    if indexed:
        try:
            record = results[int(indexed[1])]
            value = record["values"][int(indexed[2])]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError("source_record cannot be resolved") from exc
        if str(record.get("id")) != uid:
            raise ValueError("source_record points to a different unit")
        if not isinstance(value, dict) or str(value.get("year")) != str(year):
            raise ValueError("source_record points to a different year")
        return value, None
    identified = _IDENTITY_REFERENCE.fullmatch(reference)
    if not identified:
        raise ValueError("source_record uses an unsupported or malformed reference")
    if identified[1] != uid or int(identified[2]) != year:
        raise ValueError("source_record identity differs from the observation unit/year")
    absence = identified[3]
    record = next((row for row in results if str(row.get("id")) == uid), None)
    if record is None:
        if absence != "unit absent in complete response" or not _complete_response(payload, year):
            raise ValueError("unit absence lacks matching complete-pagination evidence")
        return None, absence
    values = record.get("values")
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        raise ValueError("source unit lacks a valid values list")
    matches = [value for value in values if str(value.get("year")) == str(year)]
    if len(matches) > 1:
        raise ValueError("retained response repeats the observation year")
    if not matches:
        if absence != "year absent in complete unit response" or not _complete_response(
            payload, year
        ):
            raise ValueError("year absence lacks matching complete-pagination evidence")
        return None, absence
    if absence:
        raise ValueError("source_record declares an absence for an existing source value")
    return matches[0], None


def validate_provenance(dataset: Any, snapshot_dir: str | Path) -> list[str]:
    """Verify observation pointers against retained sources, independently of file hashes."""
    errors: list[str] = []
    root = Path(snapshot_dir).resolve()
    files = dataset.manifest.get("files", dataset.manifest.get("file_hashes", {}))
    covered = set(files) if isinstance(files, dict) else {item["path"] for item in files}
    sources: dict[str, dict[str, Any] | ValueError] = {}
    required = {
        "source_file",
        "source_record",
        "unit_id",
        "year",
        "indicator_id",
        "raw_value",
        "raw_attr_id",
        "semantic_value",
        "quality_status",
        "reason_code",
    }
    if not required.issubset(dataset.observations.columns):
        return ["Provenance cannot be checked because observation columns are missing."]
    for row in dataset.observations.itertuples(index=False):
        label = f"{row.unit_id}/{row.year}/{row.indicator_id}"
        filename = str(row.source_file)
        try:
            if filename not in sources:
                try:
                    target = (root / filename).resolve()
                    if not target.is_relative_to(root) or filename not in covered:
                        raise ValueError("source_file is outside the verified snapshot manifest")
                    payload = json.loads(target.read_text(encoding="utf-8-sig"))
                    if not isinstance(payload, dict):
                        raise ValueError("retained response must be a JSON object")
                    sources[filename] = payload
                except (OSError, ValueError) as exc:
                    sources[filename] = ValueError(str(exc))
            source = sources[filename]
            if isinstance(source, ValueError):
                raise source
            if _source_indicator(source) != str(row.indicator_id):
                raise ValueError("source_record points to a different indicator")
            value, absence = _resolve(
                source, str(row.source_record), str(row.unit_id), int(row.year)
            )
            if absence:
                if (
                    not _missing(row.raw_value)
                    or not _missing(row.raw_attr_id)
                    or not _missing(row.semantic_value)
                    or row.quality_status != "missing"
                    or row.reason_code != "source_value_missing"
                ):
                    raise ValueError(
                        "documented absent source cell must remain missing with its reason"
                    )
            elif value is not None:
                if _number(row.raw_value) != _number(value.get("val")):
                    raise ValueError("raw_value differs from the referenced source value")
                if _code(row.raw_attr_id) != _code(value.get("attrId")):
                    raise ValueError("raw_attr_id differs from the referenced source attribute")
        except (ValueError, TypeError) as exc:
            errors.append(f"Observation provenance {label}: {exc}.")
    errors.extend(validate_unit_years(dataset))
    return errors
