"""Exercise real Streamlit interactions against the public offline snapshot."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from region_comparison import ui
from region_comparison.paths import OUTPUT, ROOT

APP = Path(__file__).resolve().parents[1] / "app.py"


def comparison_table(app):
    return next(table.value for table in app.dataframe if "Wynik [pkt]" in table.value)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("REGION_DATA_MODE", "snapshot")
    monkeypatch.delenv("REGION_SNAPSHOT_PATH", raising=False)
    ui._load_sample.clear()
    ui._metrics.clear()
    ui._sensitivity.clear()
    return AppTest.from_file(str(APP), default_timeout=30)


def test_start_and_same_year_comparison(app):
    app.run()
    assert not app.exception
    assert not app.error
    assert len(app.multiselect(key="selected_units").value) == 3
    comparison = comparison_table(app)
    assert len(comparison) == 3
    app.selectbox(key="analysis_year").select(2023).run()
    assert not app.exception
    assert any("Wszystkie wartości dotyczą roku 2023" in item.value for item in app.caption)
    assert len(comparison_table(app)) == 3


def test_weights_change_score_without_reloading_or_changing_cohort(app, monkeypatch):
    original = ui.load_snapshot
    calls = []

    def counted(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(ui, "load_snapshot", counted)
    app.run()
    before = comparison_table(app)["Wynik [pkt]"].tolist()
    cohort_before = next(m.value for m in app.metric if m.label == "Gminy z oceną")
    app.slider(key="weight_places_per_1000").set_value(80).run()
    assert not app.exception
    after = comparison_table(app)["Wynik [pkt]"].tolist()
    assert before != after
    assert cohort_before == next(m.value for m in app.metric if m.label == "Gminy z oceną")
    assert len(calls) == 1
    app.button(key="reset_weights").click().run()
    assert not app.exception
    assert app.slider(key="weight_places_per_1000").value == 50
    assert app.slider(key="weight_children_share_pct").value == 50
    assert comparison_table(app)["Wynik [pkt]"].tolist() == before


def test_municipality_selection_preserves_regional_scores(app):
    app.run()
    before = comparison_table(app).set_index("ID BDL")["Wynik [pkt]"].to_dict()
    cohort_before = next(m.value for m in app.metric if m.label == "Gminy z oceną")
    selected = app.multiselect(key="selected_units").value[:2]
    app.multiselect(key="selected_units").set_value(selected).run()
    assert not app.exception
    after = comparison_table(app).set_index("ID BDL")["Wynik [pkt]"].to_dict()
    assert after == {unit_id: before[unit_id] for unit_id in selected}
    assert cohort_before == next(m.value for m in app.metric if m.label == "Gminy z oceną")


def test_empty_selection_and_explicit_missing_demo(app):
    app.run()
    app.multiselect(key="selected_units").set_value([]).run()
    assert not app.exception
    assert any("Wybierz od 2 do 4 gmin" in item.value for item in app.info)
    # AppTest exposes st.toggle through the checkbox model.
    app.get_by_key("show_missing_demo").set_value(True).run()
    assert not app.exception
    assert any(
        "DEMO_BRAK_DANYCH" in item.value and "Brak oceny" in item.value for item in app.warning
    )
    assert next(m.value for m in app.metric if m.label == "Gminy w zakresie") == "169"


def test_zero_weights_remain_recoverable(app):
    app.run()
    app.slider(key="weight_places_per_1000").set_value(0).run()
    app.slider(key="weight_children_share_pct").set_value(0).run()
    assert not app.exception
    assert any("Suma wag musi być dodatnia" in item.value for item in app.error)
    app.button(key="reset_invalid_weights").click().run()
    assert not app.exception
    assert not app.error
    assert app.slider(key="weight_places_per_1000").value == 50


def test_dictionary_search_is_user_facing(app):
    app.run()
    app.text_input(key="dictionary_search").set_value("453372").run()
    assert not app.exception
    dictionary = next(table.value for table in app.dataframe if "ID GUS / wejścia" in table.value)
    assert "453372" in dictionary["ID GUS / wejścia"].tolist()
    assert all("453372" in value for value in dictionary["ID GUS / wejścia"])


def test_missing_database_configuration_has_no_traceback(app, monkeypatch):
    monkeypatch.setenv("REGION_DATA_MODE", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app.run()
    assert not app.exception
    assert any("Brak konfiguracji bazy PostgreSQL" in item.value for item in app.error)


def test_database_failure_does_not_reveal_credentials(app, monkeypatch):
    def failed(*_args, **_kwargs):
        raise RuntimeError("postgresql://person:secret_password@host/database")

    monkeypatch.setenv("REGION_DATA_MODE", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://person:secret_password@host/database")
    monkeypatch.setattr(ui, "_load_postgres", failed)
    app.run()
    assert not app.exception
    assert any("Nie można wczytać danych z PostgreSQL" in item.value for item in app.error)
    assert all("secret_password" not in item.value for item in app.error)


def test_missing_snapshot_has_clear_user_message(app, monkeypatch, tmp_path):
    monkeypatch.setenv("REGION_SNAPSHOT_PATH", str(tmp_path / "missing"))
    app.run()
    assert not app.exception
    assert any("Nie można wczytać zatwierdzonego snapshotu" in item.value for item in app.error)


def test_incompatible_definition_has_safe_analytical_error(app, monkeypatch):
    dataset = deepcopy(ui.load_snapshot(ui.DEFAULT_SNAPSHOT))
    for definition in dataset.indicators:
        if definition["metric_id"] == "children_0_2":
            definition["source_dimensions"]["n1"] = "0-3"
    monkeypatch.setattr(ui, "_load_sample", lambda *_: dataset)
    app.run()
    assert not app.exception
    assert any("dane są niezgodne z wymaganą metodologią" in item.value for item in app.error)
    assert not any(metric.label == "Wynik porównawczy [pkt]" for metric in app.metric)


def _copy_with_changed_capacity(path: Path, unit_id: str, year: int) -> Path:
    """A genuine source-consistent conflict, with all hashes updated but the same identity."""
    shutil.copytree(ui.DEFAULT_SNAPSHOT, path)
    observations = pd.read_csv(path / "observations.csv", dtype=str, keep_default_na=False)
    mask = (
        (observations.unit_id == unit_id)
        & (observations.year == str(year))
        & (observations.indicator_id == "1649554")
    )
    assert mask.sum() == 1
    original = observations.loc[mask].iloc[0]
    observations.loc[mask, ["raw_value", "semantic_value"]] = "1"
    observations.to_csv(path / "observations.csv", index=False)
    response_path = path / original.source_file
    response = json.loads(response_path.read_text(encoding="utf-8"))
    reference = re.fullmatch(r"results\[(\d+)\]\.values\[(\d+)\]", original.source_record)
    assert reference is not None
    record_index, value_index = map(int, reference.groups())
    response["results"][record_index]["values"][value_index]["val"] = 1
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(response_path.read_bytes()).hexdigest()
    metadata_path = response_path.with_suffix(".json.meta.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["sha256"] = digest
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for page in manifest["source_pages"]:
        if page["file"] == original.source_file:
            page["sha256"] = digest
    for relative in (
        "observations.csv",
        original.source_file,
        str(original.source_file) + ".meta.json",
    ):
        manifest["files"][relative] = hashlib.sha256((path / relative).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def test_same_snapshot_identity_recomputes_metrics_and_sensitivity(app, monkeypatch, tmp_path):
    source = ui.load_snapshot(ui.DEFAULT_SNAPSHOT)
    year = max(source.years)
    unit_id = ui._default_selection(source.units)[0]
    changed_path = _copy_with_changed_capacity(tmp_path / "changed", unit_id, year)
    changed = ui.load_snapshot(changed_path)
    assert ui.validate_dataset(changed).valid
    assert source.snapshot_id == changed.snapshot_id
    assert ui.dataset_fingerprint(source) != ui.dataset_fingerprint(changed)
    metrics_calls, sensitivity_calls = [], []
    build_metrics, analyze = ui.build_metrics, ui.analyze

    def counted_metrics(dataset):
        metrics_calls.append(ui.dataset_fingerprint(dataset))
        return build_metrics(dataset)

    def counted_sensitivity(result):
        sensitivity_calls.append(result)
        return analyze(result)

    monkeypatch.setattr(ui, "build_metrics", counted_metrics)
    monkeypatch.setattr(ui, "analyze", counted_sensitivity)
    app.run()
    assert not app.exception and not app.error
    previous = comparison_table(app).set_index("ID BDL").loc[unit_id]
    assert previous["Miejsca w żłobkach i klubach [miejsca]"] != "1"
    # The same AppTest process retains both caches throughout the next load.
    monkeypatch.setenv("REGION_SNAPSHOT_PATH", str(changed_path))
    app.run()
    assert not app.exception and not app.error
    current = comparison_table(app).set_index("ID BDL").loc[unit_id]
    assert current["Miejsca w żłobkach i klubach [miejsca]"] == "1"
    assert current["Wynik [pkt]"] != previous["Wynik [pkt]"]
    assert len(metrics_calls) == len(sensitivity_calls) == 2
    expected = analyze(ui.evaluate(build_metrics(changed), year, None)).summary.set_index("unit_id")
    sensitivity_table = next(
        table.value for table in app.dataframe if "Wynik min [pkt]" in table.value
    )
    actual = sensitivity_table.set_index("Gmina").loc[current["Gmina"]]
    assert actual["Wynik min [pkt]"] == expected.loc[unit_id, "score_min"]
    assert actual["Wynik max [pkt]"] == expected.loc[unit_id, "score_max"]
    assert actual["Najwyższa pozycja"] == expected.loc[unit_id, "rank_min"]
    assert actual["Najniższa pozycja"] == expected.loc[unit_id, "rank_max"]
    assert any("wymagają wyjaśnienia" in item.value for item in app.warning)


def test_ratio_tolerance_summary_matches_selected_source_year(app):
    app.run()
    assert not app.exception and not app.error
    dataset = ui.load_snapshot(ui.DEFAULT_SNAPSHOT)
    metrics = ui.build_metrics(dataset)
    for year in (max(dataset.years), min(dataset.years)):
        if app.selectbox(key="analysis_year").value != year:
            app.selectbox(key="analysis_year").select(year).run()
        summary = ui.ratio_summary(metrics.loc[metrics.year == year])
        assert next(
            item.value
            for item in app.metric
            if item.label == "Porównywalne pary ze wskaźnikiem GUS"
        ) == str(summary["paired_cells"])
        assert next(
            item.value for item in app.metric if item.label == "Różnice poza tolerancją"
        ) == str(summary["outside_tolerance"])
        assert any(
            f"Cały region · rok {year}" in item.value and "0,500000001" in item.value
            for item in app.caption
        )


@pytest.fixture
def capture_script():
    specification = importlib.util.spec_from_file_location(
        "capture_screenshots", ROOT / "scripts" / "capture-screenshots.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_capture_default_is_inside_output_independent_of_cwd(capture_script, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    arguments = capture_script._arguments(["--run-id", "ui-capture-test"])
    assert arguments.output == OUTPUT / "codex_runs" / "ui-capture-test" / "screenshots"
    assert not arguments.output.exists()
    explicit = capture_script._arguments(["--output", "output/tmp/screenshots"])
    assert explicit.output == OUTPUT / "tmp" / "screenshots"


@pytest.mark.parametrize("path", [".", "docs/images", "../screenshots", "output/../docs"])
def test_capture_rejects_artifacts_outside_output(capture_script, path, capsys):
    with pytest.raises(SystemExit) as error:
        capture_script._arguments(["--output", path])
    assert error.value.code == 2
    assert "Artifact path must be inside project output" in capsys.readouterr().err
