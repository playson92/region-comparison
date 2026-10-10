"""Exercise real Streamlit interactions against the public offline snapshot."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from region_comparison import ui

APP = Path(__file__).resolve().parents[1] / "app.py"


def comparison_table(app):
    return next(table.value for table in app.dataframe if "Wynik [pkt]" in table.value)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("REGION_DATA_MODE", "snapshot")
    monkeypatch.delenv("REGION_SNAPSHOT_PATH", raising=False)
    ui._load_sample.clear()
    ui._metrics.clear()
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
