"""Snapshot integrity and genuine PostgreSQL migration/import/adapter integration."""

import hashlib
import json
import os
from pathlib import Path

import httpx
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from region_comparison.storage import (
    StorageError,
    import_snapshot,
    load_database,
    load_snapshot,
    migrate,
)


def write_fixture(path: Path, snapshot_id="test-storage") -> Path:
    path.mkdir(parents=True)
    units = [
        {"bdl_unit_id": "030201011011", "name": "Fixture A", "kind": "1", "powiat": "Fixture"},
        {"bdl_unit_id": "030201011022", "name": "Fixture B", "kind": "2", "powiat": "Fixture"},
    ]
    for filename, contents in [
        ("units.json", units),
        ("indicators.json", [{"id": "7", "years": [2023], "definition_version": "1"}]),
        ("attributes.json", [{"id": 0, "name": "0"}, {"id": 1, "name": "value"}]),
    ]:
        (path / filename).write_text(json.dumps(contents), encoding="utf-8")
    (path / "fixture.json").write_text(
        json.dumps({"synthetic": True, "values": [3, 0]}), encoding="utf-8"
    )
    pd.DataFrame(
        [
            {
                "unit_id": u["bdl_unit_id"],
                "year": 2023,
                "indicator_id": "7",
                "raw_value": value,
                "raw_attr_id": "0" if value == 0 else "1",
                "semantic_value": value,
                "quality_status": "true_zero" if value == 0 else "valid",
                "reason_code": "observed_zero" if value == 0 else "observed",
                "source_file": "fixture.json",
                "source_record": str(index),
            }
            for index, (u, value) in enumerate(zip(units, [3, 0], strict=True))
        ]
    ).to_csv(path / "observations.csv", index=False)
    manifest = {
        "snapshot_id": snapshot_id,
        "manifest_schema_version": 1,
        "state": "complete",
        "years": [2023],
        "files": {
            file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in path.iterdir()
        },
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_snapshot_retains_leading_zeros_and_real_zero(tmp_path):
    dataset = load_snapshot(write_fixture(tmp_path / "snapshot"))
    assert dataset.units.bdl_unit_id.iloc[0] == "030201011011"
    assert dataset.observations.unit_id.iloc[0] == "030201011011"
    assert dataset.observations.raw_attr_id.iloc[0] == "1"
    assert dataset.observations.semantic_value.iloc[1] == 0


def test_snapshot_hash_tampering_and_path_escape_fail(tmp_path):
    path = write_fixture(tmp_path / "snapshot")
    (path / "units.json").write_text("[]")
    with pytest.raises(StorageError, match="hash"):
        load_snapshot(path)
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["files"]["../escape.json"] = "0" * 64
    manifest["files"]["units.json"] = hashlib.sha256((path / "units.json").read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(StorageError, match="outside"):
        load_snapshot(path)


def test_full_adapter_refuses_sqlite():
    with pytest.raises(StorageError, match="PostgreSQL"):
        load_database("sqlite://")


@pytest.fixture
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL is required for genuine PostgreSQL integration; CI supplies it."
        )
    name = make_url(url).database or ""
    if not (name.endswith("_test") or name.startswith("test")):
        pytest.fail("Destructive PostgreSQL integration requires a dedicated test database name.")
    migrate(url)
    normalized = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(normalized)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE observations, unit_versions, indicator_definitions, attribute_definitions, ingestion_runs, snapshots, units RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
    return url


@pytest.mark.postgres
def test_postgres_migration_idempotent_import_and_adapter_equivalence(tmp_path, database_url):
    path = write_fixture(tmp_path / "snapshot")
    migrate(database_url)
    migrate(database_url)
    assert import_snapshot(database_url, path) == "test-storage"
    assert import_snapshot(database_url, path) == "test-storage"
    offline, database = load_snapshot(path), load_database(database_url)
    assert database.manifest == offline.manifest
    assert database.snapshot_id == offline.snapshot_id
    assert_frame_equal(
        offline.units.sort_values("bdl_unit_id").reset_index(drop=True),
        database.units.sort_values("bdl_unit_id").reset_index(drop=True),
        check_dtype=False,
        check_like=True,
    )
    columns = list(offline.observations.columns)
    assert_frame_equal(
        offline.observations.sort_values("unit_id").reset_index(drop=True),
        database.observations[columns].sort_values("unit_id").reset_index(drop=True),
        check_dtype=False,
    )
    assert database.indicators == offline.indicators
    assert database.attributes == offline.attributes


@pytest.mark.postgres
def test_invalid_or_changed_snapshot_preserves_previous_active_snapshot(tmp_path, database_url):
    original = write_fixture(tmp_path / "original")
    import_snapshot(database_url, original)
    invalid = write_fixture(tmp_path / "invalid", "invalid")
    manifest = json.loads((invalid / "manifest.json").read_text())
    manifest["state"] = "partial"
    (invalid / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(StorageError, match="cannot be activated"):
        import_snapshot(database_url, invalid)
    assert load_database(database_url).snapshot_id == "test-storage"
    original_manifest = json.loads((original / "manifest.json").read_text())
    original_manifest["code_version"] = "changed"
    (original / "manifest.json").write_text(json.dumps(original_manifest))
    with pytest.raises(StorageError, match="immutable"):
        import_snapshot(database_url, original)
    assert load_database(database_url).manifest.get("code_version") is None


@pytest.mark.postgres
def test_new_definition_is_scoped_to_its_snapshot(tmp_path, database_url):
    old = write_fixture(tmp_path / "old", "old")
    new = write_fixture(tmp_path / "new", "new")
    import_snapshot(database_url, old)
    definitions = [
        {"id": "7", "years": [2023], "definition_version": "2", "definition": "new definition"}
    ]
    (new / "indicators.json").write_text(json.dumps(definitions))
    manifest = json.loads((new / "manifest.json").read_text())
    manifest["files"]["indicators.json"] = hashlib.sha256(
        (new / "indicators.json").read_bytes()
    ).hexdigest()
    (new / "manifest.json").write_text(json.dumps(manifest))
    import_snapshot(database_url, new)
    assert load_database(database_url).snapshot_id == "new"
    assert load_database(database_url, "old").indicators[0]["definition_version"] == "1"
    assert load_database(database_url, "new").indicators[0]["definition_version"] == "2"
    import_snapshot(database_url, old)
    assert load_database(database_url).snapshot_id == "old"
    assert load_database(database_url, "new").indicators[0]["definition_version"] == "2"


@pytest.mark.postgres
@pytest.mark.parametrize("omit_registered_unit", [False, True])
def test_real_snapshot_postgres_and_offline_have_identical_metrics_scores(
    database_url, tmp_path, omit_registered_unit
):
    from region_comparison.config import read_indicators
    from region_comparison.exports import dataset_fingerprint
    from region_comparison.ingestion import BDLClient, fetch_snapshot
    from region_comparison.metrics import build_metrics
    from region_comparison.scoring import evaluate

    sample = Path(__file__).resolve().parents[1] / "data" / "sample"
    if omit_registered_unit:
        original = load_snapshot(sample)
        configuration = read_indicators()
        configuration.update(
            units=original.units.to_dict(orient="records"), attributes=original.attributes
        )

        def handler(request):
            endpoint = request.url.path.rsplit("/api/v1/", 1)[-1]
            if endpoint == "units":
                filename = f"units-page-{request.url.params['page']}.json"
            elif endpoint == "attributes":
                filename = "attributes.json"
            elif endpoint.startswith("variables/"):
                filename = f"variable-{endpoint.split('/')[-1]}.json"
            else:
                filename = f"data-{endpoint.split('/')[-1]}-page-{request.url.params['page']}.json"
            body = json.loads((sample / "source_responses" / filename).read_text(encoding="utf-8"))
            if endpoint == "data/by-variable/453372":
                body["totalRecords"] -= 1
                body["results"] = [row for row in body["results"] if row["id"] != "030210564011"]
            return httpx.Response(200, json=body)

        with BDLClient(
            tmp_path / "cache",
            transport=httpx.MockTransport(handler),
            rate_limits=((1, 10000), (60, 10000)),
        ) as client:
            fetched = fetch_snapshot(configuration, tmp_path / "omitted-unit", client)
        sample = fetched
    import_snapshot(database_url, sample)
    offline, postgres = load_snapshot(sample), load_database(database_url)
    assert offline.attributes == postgres.attributes
    assert offline.indicators == postgres.indicators
    assert_frame_equal(
        offline.units.sort_values("bdl_unit_id").reset_index(drop=True),
        postgres.units.sort_values("bdl_unit_id").reset_index(drop=True),
        check_like=True,
        check_dtype=False,
    )
    assert dataset_fingerprint(offline) == dataset_fingerprint(postgres)
    for column in ("raw_value", "raw_attr_id"):
        key = ["unit_id", "year", "indicator_id"]
        pd.testing.assert_series_equal(
            offline.observations.set_index(key).sort_index()[column],
            postgres.observations.set_index(key).sort_index()[column],
            check_dtype=False,
        )
    if omit_registered_unit:
        missing = offline.observations[
            (offline.observations.unit_id == "030210564011")
            & (offline.observations.indicator_id == "453372")
        ]
        assert len(missing) == 3
        assert missing.raw_value.isna().all() and missing.raw_attr_id.isna().all()
    left, right = build_metrics(offline), build_metrics(postgres)
    assert_frame_equal(left, right, check_like=True, check_dtype=False)
    for year in offline.years:
        assert_frame_equal(evaluate(left, year).frame, evaluate(right, year).frame, check_like=True)
        if omit_registered_unit:
            assert "030210564011" not in evaluate(left, year).cohort_ids
