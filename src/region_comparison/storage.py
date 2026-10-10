"""One immutable dataset contract for offline snapshots and real PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from region_comparison.validation import attribute_id, indicator_id, validate_dataset


@dataclass
class Dataset:
    manifest: dict[str, Any]
    units: pd.DataFrame
    observations: pd.DataFrame
    indicators: list[dict[str, Any]]
    attributes: list[dict[str, Any]]

    @property
    def snapshot_id(self) -> str:
        return str(self.manifest["snapshot_id"])

    @property
    def years(self) -> list[int]:
        return list(map(int, self.manifest["years"]))


class StorageError(RuntimeError):
    """A dataset cannot safely be loaded or activated."""


def _list_json(path: Path) -> list[dict[str, Any]]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(result, dict):
        result = result.get(
            "results", result.get("indicators", result.get("attributes", result.get("units")))
        )
    if not isinstance(result, list):
        raise StorageError(f"Expected a list of definitions in {path.name}.")
    return result


def load_snapshot(path: str | Path, *, allow_partial: bool = False) -> Dataset:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    state = manifest.get("state", manifest.get("status", manifest.get("import_state")))
    if state != "complete" and not allow_partial:
        raise StorageError("Snapshot cannot be activated: the download is incomplete.")
    files = manifest.get("files", manifest.get("file_hashes", {}))
    if isinstance(files, list):
        files = {item["path"]: item["sha256"] for item in files}
    required = {"units.json", "observations.csv", "indicators.json", "attributes.json"}
    if not required.issubset(files):
        raise StorageError("Manifest must identify hashes for every dataset file.")
    for relative, digest in files.items():
        target = (path / relative).resolve()
        if not target.is_relative_to(path.resolve()):
            raise StorageError("Snapshot manifest contains a path outside its directory.")
        expected = digest.get("sha256") if isinstance(digest, dict) else digest
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise StorageError(f"Snapshot file is missing or has an invalid hash: {relative}.")
    units = pd.DataFrame(_list_json(path / "units.json"))
    for column in ("bdl_unit_id", "kind", "parent_id", "teryt"):
        if column in units:
            units[column] = units[column].map(lambda v: str(v) if v is not None else None)
    observations = pd.read_csv(
        path / "observations.csv",
        dtype={
            "unit_id": str,
            "indicator_id": str,
            "raw_attr_id": str,
            "raw_value": str,
            "source_file": str,
            "source_record": str,
            "reason_code": str,
        },
        keep_default_na=False,
    )
    observations["semantic_value"] = pd.to_numeric(observations["semantic_value"], errors="raise")
    observations["year"] = pd.to_numeric(observations["year"], errors="raise").astype(int)
    for column in ("raw_value", "raw_attr_id"):
        observations[column] = observations[column].where(observations[column] != "", None)
    return Dataset(
        manifest,
        units,
        observations,
        sorted(_list_json(path / "indicators.json"), key=indicator_id),
        sorted(_list_json(path / "attributes.json"), key=attribute_id),
    )


def _engine(database_url: str) -> Engine:
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not database_url.startswith("postgresql+psycopg://"):
        raise StorageError("The full adapter requires PostgreSQL using the psycopg driver.")
    return create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


def migrate(database_url: str, migration_dir: str | Path | None = None) -> None:
    from region_comparison.config import ROOT

    migrations = Path(migration_dir) if migration_dir else ROOT / "sql" / "migrations"
    if not migrations.is_dir():
        raise StorageError("SQL migrations are unavailable; run from the repository distribution.")
    engine = _engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(73490001)"))
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
                    "applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            for migration in sorted(migrations.glob("*.sql")):
                content = migration.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                applied = connection.execute(
                    text("SELECT sha256 FROM schema_migrations WHERE version=:v"),
                    {"v": migration.name},
                ).scalar_one_or_none()
                if applied:
                    if applied != digest:
                        raise StorageError(f"Applied migration {migration.name} was modified.")
                    continue
                connection.exec_driver_sql(content.decode("utf-8"))
                connection.execute(
                    text("INSERT INTO schema_migrations(version,sha256) VALUES (:v,:h)"),
                    {"v": migration.name, "h": digest},
                )
    finally:
        engine.dispose()


def _clean(value: Any) -> Any:
    if isinstance(value, str) and value == "":
        return None
    return _metadata(value)


def _metadata(value: Any) -> Any:
    """Preserve source metadata exactly; only pandas' missing scalars become JSON null."""
    if isinstance(value, dict):
        return {key: _metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_metadata(item) for item in value]
    if value is None or pd.isna(value):
        return None
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def import_snapshot(database_url: str, path: str | Path) -> str:
    dataset = load_snapshot(path)
    report = validate_dataset(dataset)
    if not report.valid:
        raise StorageError("Snapshot cannot be activated: " + "; ".join(report.errors))
    migrate(database_url)
    digest = hashlib.sha256(_json(dataset.manifest).encode()).hexdigest()
    engine = _engine(database_url)
    sid = dataset.snapshot_id
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(73490002)"))
            existing = connection.execute(
                text("SELECT content_sha256 FROM snapshots WHERE snapshot_id=:s"), {"s": sid}
            ).scalar_one_or_none()
            if existing:
                if existing != digest:
                    raise StorageError(
                        "An immutable snapshot identifier already exists with different content."
                    )
                connection.execute(text("UPDATE snapshots SET active=FALSE WHERE active"))
                connection.execute(
                    text("UPDATE snapshots SET active=TRUE WHERE snapshot_id=:s"), {"s": sid}
                )
                return sid
            connection.execute(
                text(
                    "INSERT INTO snapshots(snapshot_id,manifest_schema_version,state,manifest,content_sha256) "
                    "VALUES (:s,:v,'complete',CAST(:m AS JSONB),:h)"
                ),
                {
                    "s": sid,
                    "v": int(str(dataset.manifest.get("manifest_schema_version", 1)).split(".")[0]),
                    "m": _json(dataset.manifest),
                    "h": digest,
                },
            )
            for unit in dataset.units.to_dict(orient="records"):
                uid = str(unit["bdl_unit_id"])
                connection.execute(
                    text("INSERT INTO units(unit_id) VALUES (:u) ON CONFLICT DO NOTHING"),
                    {"u": uid},
                )
                connection.execute(
                    text(
                        "INSERT INTO unit_versions(snapshot_id,unit_id,name,kind,parent_id,powiat,"
                        "valid_from,valid_to,teryt,metadata) VALUES "
                        "(:s,:u,:n,:k,:p,:w,:f,:t,:r,CAST(:m AS JSONB))"
                    ),
                    {
                        "s": sid,
                        "u": uid,
                        "n": unit["name"],
                        "k": str(unit["kind"]),
                        "p": _clean(unit.get("parent_id")),
                        "w": _clean(unit.get("powiat")),
                        "f": _clean(unit.get("valid_from")),
                        "t": _clean(unit.get("valid_to")),
                        "r": _clean(unit.get("teryt")),
                        "m": _json(_metadata(unit)),
                    },
                )
            for definition in dataset.indicators:
                connection.execute(
                    text(
                        "INSERT INTO indicator_definitions(snapshot_id,indicator_id,definition_version,metadata) "
                        "VALUES (:s,:i,:v,CAST(:m AS JSONB))"
                    ),
                    {
                        "s": sid,
                        "i": indicator_id(definition),
                        "v": str(definition.get("definition_version", "1")),
                        "m": _json(definition),
                    },
                )
            for attribute in dataset.attributes:
                connection.execute(
                    text(
                        "INSERT INTO attribute_definitions(snapshot_id,attr_id,metadata) "
                        "VALUES (:s,:a,CAST(:m AS JSONB))"
                    ),
                    {"s": sid, "a": attribute_id(attribute), "m": _json(attribute)},
                )
            records = []
            for row in dataset.observations.to_dict(orient="records"):
                records.append(
                    {"snapshot_id": sid, **{key: _clean(value) for key, value in row.items()}}
                )
            connection.execute(
                text(
                    "INSERT INTO observations(snapshot_id,unit_id,year,indicator_id,raw_value,raw_attr_id,"
                    "semantic_value,quality_status,reason_code,source_file,source_record) VALUES "
                    "(:snapshot_id,:unit_id,:year,:indicator_id,:raw_value,:raw_attr_id,:semantic_value,"
                    ":quality_status,:reason_code,:source_file,:source_record)"
                ),
                records,
            )
            connection.execute(
                text(
                    "INSERT INTO ingestion_runs(snapshot_id,state,started_at,finished_at,metadata) "
                    "VALUES (:s,'complete',:b,:e,CAST(:m AS JSONB))"
                ),
                {
                    "s": sid,
                    "b": dataset.manifest.get("started_at", dataset.manifest.get("started_at_utc")),
                    "e": dataset.manifest.get(
                        "finished_at", dataset.manifest.get("completed_at_utc")
                    ),
                    "m": _json(report.to_dict()),
                },
            )
            connection.execute(text("UPDATE snapshots SET active=FALSE WHERE active"))
            connection.execute(
                text("UPDATE snapshots SET active=TRUE WHERE snapshot_id=:s"), {"s": sid}
            )
        return sid
    finally:
        engine.dispose()


def load_database(database_url: str, snapshot_id: str | None = None) -> Dataset:
    engine = _engine(database_url)
    try:
        with engine.connect() as connection:
            statement = "SELECT snapshot_id,manifest FROM snapshots WHERE state='complete' AND "
            statement += "active" if snapshot_id is None else "snapshot_id=:s"
            snapshot = (
                connection.execute(text(statement), {"s": snapshot_id}).mappings().one_or_none()
            )
            if snapshot is None:
                raise StorageError("No complete active PostgreSQL snapshot is available.")
            sid = snapshot["snapshot_id"]

            def metadata(table: str, order: str) -> list[dict[str, Any]]:
                # Table/order names are fixed internal constants, never user input.
                return list(
                    connection.execute(
                        text(f"SELECT metadata FROM {table} WHERE snapshot_id=:s ORDER BY {order}"),
                        {"s": sid},
                    ).scalars()
                )

            units = pd.DataFrame(metadata("unit_versions", "unit_id"))
            indicators = metadata("indicator_definitions", "indicator_id")
            attributes = metadata("attribute_definitions", "attr_id")
            observations = pd.read_sql_query(
                text(
                    "SELECT unit_id,year,indicator_id,raw_value,raw_attr_id,semantic_value,"
                    "quality_status,reason_code,source_file,source_record "
                    "FROM observations WHERE snapshot_id=:s ORDER BY unit_id,year,indicator_id"
                ),
                connection,
                params={"s": sid},
            )
            return Dataset(snapshot["manifest"], units, observations, indicators, attributes)
    finally:
        engine.dispose()
