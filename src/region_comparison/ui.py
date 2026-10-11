"""Polish presentation layer; analytical decisions live in dedicated modules."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from itertools import combinations
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from region_comparison.config import (
    COMPONENTS,
    DEFAULT_SNAPSHOT,
    METHODOLOGY_VERSION,
    read_indicators,
)
from region_comparison.exports import (
    dataset_fingerprint,
    export_config,
    export_csv,
    methodology_fingerprint,
)
from region_comparison.metrics import build_metrics, ratio_summary
from region_comparison.scoring import apply_weights, evaluate
from region_comparison.sensitivity import analyze
from region_comparison.storage import load_database, load_snapshot
from region_comparison.validation import validate_dataset

SOURCE = "Źródło: GUS, Bank Danych Lokalnych • obliczenia RegionComparison"
FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#172B3A"/>'
    '<path d="M7 24V15h4v9zm7 0V8h4v16zm7 0V12h4v12z" fill="#EDA782"/>'
    "</svg>"
)
METRIC_LABELS = {
    "population_total": ("Ludność ogółem", "osoby", 0),
    "children_0_2": ("Dzieci w wieku 0–2 lata", "osoby", 0),
    "children_share_pct": ("Udział dzieci 0–2 w ludności", "%", 2),
    "care_places": ("Miejsca w żłobkach i klubach", "miejsca", 0),
    "places_per_1000": ("Miejsca na 1000 dzieci 0–2", "miejsca / 1000 dzieci", 1),
    "children_in_care": ("Dzieci w opiece — stan 31 XII", "osoby", 0),
    "nurseries": ("Żłobki", "placówki", 0),
    "child_clubs": ("Kluby dziecięce", "placówki", 0),
    "care_facilities": ("Żłobki i kluby łącznie", "placówki", 0),
    "gus_places_per_1000": ("Miejsca na 1000 — wskaźnik GUS", "miejsca / 1000 dzieci", 1),
}
STATUS_LABELS = {
    "valid": "Wartość poprawna",
    "true_zero": "Rzeczywiste zero",
    "preliminary": "Dane wstępne",
    "missing": "Brak danych",
    "unavailable": "Brak lub niedostępność",
    "protected_or_unavailable": "Wartość niedostępna / chroniona",
    "below_precision": "Poniżej precyzji prezentacji",
    "low_precision": "Niska precyzja",
    "incomplete": "Niekompletna miara",
    "definition_mismatch": "Niezgodność definicji",
    "comparability_break": "Przerwa porównywalności",
    "unknown_attribute": "Nieznany atrybut GUS",
    "invalid": "Wartość niepoprawna",
}
VALID_STATUSES = {"valid", "true_zero"}
KIND_LABELS = {"1": "miejska", "2": "wiejska", "3": "miejsko-wiejska"}
PALETTE = ("#266B80", "#C45D35", "#6A7F42", "#87679D", "#BB8030", "#468A79")


@st.cache_data(max_entries=4, show_spinner=False)
def _load_sample(path: str, manifest_modified: int):
    """Immutable snapshot cached by path and manifest version on disk."""
    dataset = load_snapshot(Path(path))
    if not validate_dataset(dataset).valid:
        raise ValueError("Snapshot quality validation failed")
    return dataset


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
def _load_postgres(database_url: str, snapshot_id: str | None):
    return load_database(database_url, snapshot_id=snapshot_id)


@st.cache_data(max_entries=4, show_spinner=False)
def _metrics(dataset_sha256: str, methodology_sha256: str, _dataset) -> pd.DataFrame:
    """Cache verified content and the executed contract, rather than a metadata identity."""
    return build_metrics(_dataset)


@st.cache_data(max_entries=64, show_spinner=False)
def _sensitivity(
    dataset_sha256: str,
    methodology_sha256: str,
    year: int,
    weights: tuple,
    cohort_ids: tuple[str, ...],
    _result,
):
    return analyze(_result)


def _format(value: object, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "Brak danych"
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


def _rank(row: pd.Series) -> str:
    if pd.isna(row.get("rank_min")):
        return "Brak oceny"
    low, high = int(row["rank_min"]), int(row["rank_max"])
    return str(low) if low == high else f"{low}–{high} (remis)"


def _status(value: object) -> str:
    if value is None or pd.isna(value):
        return "Brak statusu"
    return STATUS_LABELS.get(str(value), str(value))


def _unit_labels(units: pd.DataFrame) -> dict[str, str]:
    labels = {}
    for row in units.to_dict("records"):
        kind = KIND_LABELS.get(str(row.get("kind", "")), str(row.get("kind", "")))
        powiat = str(row.get("powiat") or "powiat nieopisany")
        labels[str(row["bdl_unit_id"])] = f"{row['name']} · {kind} · {powiat}"
    return labels


def _default_selection(units: pd.DataFrame) -> list[str]:
    """Three contrasting municipality kinds, identified by source IDs thereafter."""
    chosen = []
    wroclaw = units[(units["name"] == "Wrocław") & (units["kind"].astype(str) == "1")]
    if not wroclaw.empty:
        chosen.append(str(wroclaw.iloc[0]["bdl_unit_id"]))
    for name, kind in (("Kobierzyce", "2"), ("Siechnice", "3")):
        candidates = units[(units["name"] == name) & (units["kind"].astype(str) == kind)]
        if candidates.empty:
            candidates = units[units["kind"].astype(str) == kind]
        if not candidates.empty:
            chosen.append(str(candidates.iloc[0]["bdl_unit_id"]))
    for unit_id in units["bdl_unit_id"].astype(str):
        if len(chosen) >= 3:
            break
        if unit_id not in chosen:
            chosen.append(unit_id)
    return chosen


def _colors(ids: list[str]) -> dict[str, str]:
    """Keep municipality colors across widgets and reruns within the session."""
    colors = st.session_state.setdefault("municipality_colors", {})
    for unit_id in ids:
        if unit_id not in colors:
            if len(colors) < len(PALETTE):
                colors[unit_id] = PALETTE[len(colors)]
            else:
                hue = int(hashlib.sha256(unit_id.encode()).hexdigest()[:8], 16) % 360
                colors[unit_id] = f"hsl({hue}, 45%, 38%)"
    return colors


def _chart(fig: go.Figure, key: str, alt: str, *, height: int = 330) -> None:
    fig.update_layout(
        height=height,
        margin={"l": 12, "r": 16, "t": 16, "b": 30},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial, sans-serif", "color": "#172B3A", "size": 12},
        legend={"orientation": "h", "y": -0.22, "x": 0},
        hoverlabel={"bgcolor": "#FFFFFF"},
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#DFE5E1", zerolinecolor="#DFE5E1")
    st.plotly_chart(
        fig,
        key=key,
        width="stretch",
        config={"displaylogo": False, "scrollZoom": False, "responsive": True},
        alt=alt,
    )
    st.caption(SOURCE)


def _enrich(frame: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    unit_frame = units.rename(columns={"bdl_unit_id": "unit_id"})
    fields = [c for c in ("unit_id", "name", "kind", "powiat") if c in unit_frame]
    missing = [c for c in fields if c not in frame or c == "unit_id"]
    enriched = frame.merge(unit_frame[missing], on="unit_id", how="left", validate="many_to_one")
    enriched["display_name"] = enriched.apply(
        lambda r: f"{r['name']} ({KIND_LABELS.get(str(r.get('kind')), str(r.get('kind')))})", axis=1
    )
    return enriched


def _set_weights(first: int, second: int) -> None:
    st.session_state["weight_places_per_1000"] = first
    st.session_state["weight_children_share_pct"] = second


def _comparison_table(frame: pd.DataFrame) -> pd.DataFrame:
    table = frame[["display_name", "unit_id"]].rename(
        columns={"display_name": "Gmina", "unit_id": "ID BDL"}
    )
    for metric, (label, unit, digits) in METRIC_LABELS.items():
        if metric in frame:
            table[f"{label} [{unit}]"] = frame[metric].map(lambda v, d=digits: _format(v, d))
    table["Wynik [pkt]"] = frame["score"].map(
        lambda v: _format(v, 2) if pd.notna(v) else "Brak oceny"
    )
    table["Miejsce / przedział"] = frame.apply(_rank, axis=1)
    table["Powód braku oceny"] = frame["eligibility_reason"].where(~frame["eligible"], "—")
    return table


def _overview(dataset, metrics: pd.DataFrame, result, frame: pd.DataFrame, selected: list[str]):
    st.subheader("Region w jednym miejscu", icon=":material/landscape:")
    st.markdown(
        "Zestaw demografię najmłodszych mieszkańców z instytucjonalną opieką. "
        "Wybierz gminy, sprawdź dane źródłowe i zobacz, jak wagi wpływają na porównanie."
    )
    count = len(dataset.units)
    eligible = len(result.cohort_ids)
    obs = dataset.observations[dataset.observations["year"] == result.year]
    usable = int(obs["quality_status"].isin(VALID_STATUSES).sum())
    completeness = 100 * usable / len(obs) if len(obs) else 0.0
    columns = st.columns(4)
    columns[0].metric("Gminy w zakresie", count, border=True, icon=":material/location_city:")
    columns[1].metric("Gminy z oceną", eligible, border=True, icon=":material/check_circle:")
    columns[2].metric("Bez oceny", count - eligible, border=True, icon=":material/info:")
    columns[3].metric("Poprawne obserwacje", f"{_format(completeness, 1)}%", border=True)
    st.caption(
        f"Rok {result.year} • wspólny zbiór odniesienia: {eligible} gmin • "
        "kompletność dotyczy wszystkich cech źródłowych w wybranym roku."
    )
    if len(dataset.years) < 3:
        st.warning("Zakres częściowy: zweryfikowano mniej niż trzy wspólne lata.")
    left, right = st.columns([1.8, 1])
    with left, st.container(border=True):
        st.markdown("#### Jak czytać ten obraz?")
        st.caption("Każdy punkt to pełna gmina. Kolor wyróżnia wybór z panelu bocznego.")
        regional = frame[frame["eligible"]].copy()
        regional["Wybór"] = regional["unit_id"].isin(selected)
        fig = go.Figure()
        background = regional[~regional["Wybór"]]
        fig.add_trace(
            go.Scatter(
                x=background["places_per_1000"],
                y=background["children_share_pct"],
                mode="markers",
                marker={"size": 7, "color": "#A7B7B6", "opacity": 0.65},
                name="Pozostałe gminy",
                text=background["display_name"],
                hovertemplate="%{text}<br>%{x:.1f} miejsc / 1000<br>%{y:.2f}% dzieci 0–2<extra></extra>",
            )
        )
        colors = _colors(selected)
        for unit_id in selected:
            rows = regional[regional["unit_id"] == unit_id]
            fig.add_trace(
                go.Scatter(
                    x=rows["places_per_1000"],
                    y=rows["children_share_pct"],
                    mode="markers",
                    name=rows["display_name"].iloc[0] if not rows.empty else unit_id,
                    marker={
                        "size": 13,
                        "color": colors[unit_id],
                        "line": {"width": 1, "color": "white"},
                    },
                    hovertemplate="%{x:.1f} miejsc / 1000<br>%{y:.2f}% dzieci 0–2<extra>%{fullData.name}</extra>",
                )
            )
        fig.update_layout(
            xaxis_title="Miejsca na 1000 dzieci 0–2", yaxis_title="Udział dzieci 0–2 [%]"
        )
        _chart(fig, "region_scatter", "Gminy: podaż względna i udział dzieci 0–2", height=355)
    with right, st.container(border=True):
        st.markdown("#### Od danych do pytania badawczego")
        st.markdown(
            "**01 · Porównaj**\n\nW panelu bocznym wybierz 2–4 gminy i jeden rok.\n\n"
            "**02 · Sprawdź kontekst**\n\nProfil pokazuje wartości, trendy i statusy danych.\n\n"
            "**03 · Zmień założenia**\n\nW zakładce wag oceń zakres pozycji w wielu scenariuszach."
        )
        st.caption("Wyższy wynik oznacza silniejszy sygnał do dalszej analizy.")
    st.info(
        "Wynik porównawczy nie mierzy niezaspokojonego popytu. Dane nie obejmują cen, "
        "kolejek, dojazdów, preferencji rodziców ani przepływów dzieci między gminami.",
        icon=":material/info:",
    )


def _comparison(frame: pd.DataFrame, result, selected: list[str]):
    st.subheader("Gminy obok siebie", icon=":material/compare_arrows:")
    if len(selected) < 2:
        st.info("Wybierz od 2 do 4 gmin w panelu bocznym, aby rozpocząć porównanie.")
        return
    rows = frame[frame["unit_id"].isin(selected)].set_index("unit_id").loc[selected].reset_index()
    st.caption(
        f"Wszystkie wartości dotyczą roku {result.year}. "
        f"Wynik i miejsca odnoszą się do {len(result.cohort_ids)} gmin regionu."
    )
    colors = _colors(selected)
    for column, (_, row) in zip(st.columns(len(rows)), rows.iterrows(), strict=True):
        with column, st.container(border=True):
            st.markdown(f"**{row['display_name']}**")
            st.caption(str(row.get("powiat", "")))
            st.metric(
                "Wynik porównawczy [pkt]",
                _format(row["score"], 2) if pd.notna(row["score"]) else "Brak oceny",
            )
            st.caption(f"Miejsce: {_rank(row)}")
            if not row["eligible"]:
                st.warning(f"Brak oceny: {row['eligibility_reason']}")
    for column, metric in zip(st.columns(2), COMPONENTS, strict=True):
        label, unit, digits = METRIC_LABELS[metric]
        with column, st.container(border=True):
            st.markdown(f"#### {label}")
            chart_rows = rows[rows[metric].notna()]
            fig = px.bar(
                chart_rows,
                x="display_name",
                y=metric,
                color="unit_id",
                color_discrete_map=colors,
                labels={"display_name": "Gmina", metric: f"{label} [{unit}]", "unit_id": "ID BDL"},
                text=chart_rows[metric].map(lambda v, d=digits: _format(v, d)),
            )
            fig.update_layout(showlegend=False, xaxis_title=None)
            fig.update_traces(textposition="outside", cliponaxis=False)
            _chart(fig, f"comparison_{metric}", f"Porównanie gmin: {label}, rok {result.year}")
            if rows[metric].isna().any():
                st.caption(
                    "Brak wartości nie jest słupkiem o wysokości zero; przyczyny są w profilu."
                )
    st.dataframe(
        _comparison_table(rows),
        hide_index=True,
        key="comparison_table",
        alt="Wartości miar, jednostki i wynik wybranych gmin",
    )
    st.caption(
        "Miejsca i dzieci w opiece są różnymi wielkościami. Liczba dzieci w placówkach "
        "może obejmować dzieci starsze niż 2 lata; nie jest liczbą wszystkich użytkowników w roku."
    )


def _profile(
    dataset, metrics: pd.DataFrame, frame: pd.DataFrame, labels: dict, selected: list[str]
):
    st.subheader("Profil i rzeczywiste trendy", icon=":material/query_stats:")
    options = list(labels)
    default = options.index(selected[0]) if selected else 0
    unit_id = st.selectbox(
        "Gmina do profilu", options, index=default, format_func=labels.get, key="profile_unit"
    )
    rows = frame[frame["unit_id"] == unit_id]
    if rows.empty:
        st.info("Brak danych tej jednostki w wybranym roku.")
        return
    row = rows.iloc[0]
    st.markdown(f"#### {row['display_name']}")
    st.caption(f"ID BDL: {unit_id} • {row.get('powiat', '')}")
    if row["eligible"] and pd.notna(row["score"]):
        st.success(
            f"Wynik: {_format(row['score'], 2)} pkt · miejsce {_rank(row)}",
            icon=":material/check_circle:",
        )
    else:
        st.warning(f"Brak oceny: {row['eligibility_reason']}")
    profile_rows = []
    for metric, (label, unit, digits) in METRIC_LABELS.items():
        if metric in row:
            profile_rows.append(
                {
                    "Miara": label,
                    "Wartość": _format(row[metric], digits),
                    "Jednostka": unit,
                    "Status": _status(row.get(f"{metric}_status")),
                    "Kod przyczyny": row.get(f"{metric}_reason", ""),
                }
            )
    st.dataframe(
        pd.DataFrame(profile_rows),
        hide_index=True,
        alt="Profil gminy ze statusami i przyczynami braków",
    )
    metric = st.selectbox(
        "Miara na wykresie trendu",
        list(METRIC_LABELS),
        format_func=lambda m: f"{METRIC_LABELS[m][0]} [{METRIC_LABELS[m][1]}]",
        index=list(METRIC_LABELS).index("places_per_1000"),
        key="trend_metric",
    )
    trend = metrics[metrics["unit_id"] == unit_id].sort_values("year").copy()
    # Keep every year, including null values; connectgaps=False preserves breaks.
    years = pd.DataFrame({"year": list(dataset.years)})
    trend = years.merge(trend, on="year", how="left", validate="one_to_one")
    label, unit, _ = METRIC_LABELS[metric]
    fig = go.Figure(
        go.Scatter(
            x=trend["year"],
            y=trend[metric],
            mode="lines+markers",
            connectgaps=False,
            line={"color": _colors([unit_id])[unit_id], "width": 3},
            marker={"size": 10},
            name=row["display_name"],
            hovertemplate="%{x}: %{y:.2f}<extra>%{fullData.name}</extra>",
        )
    )
    fig.update_layout(xaxis_title="Rok", yaxis_title=f"{label} [{unit}]", xaxis={"dtick": 1})
    _chart(fig, "profile_trend", f"Trend gminy: {label}; brakujące lata przerywają linię")
    st.caption(
        "Trend przedstawia surową miarę. Zmiana percentyla między latami nie jest zmianą jej wartości."
    )
    details = ["year", metric, f"{metric}_status", f"{metric}_reason"]
    st.dataframe(
        trend[[c for c in details if c in trend]].rename(columns={"year": "Rok", metric: label}),
        hide_index=True,
        alt="Wartości trendu i statusy porównywalności",
    )
    with st.expander("Scenariusz testowy: brak wymaganej miary", icon=":material/science:"):
        st.caption(
            "Jawna fikcyjna jednostka. Poza oficjalną kohortą, rankingiem i eksportem danych GUS."
        )
        if st.toggle("Pokaż DEMO_BRAK_DANYCH", key="show_missing_demo"):
            st.warning("DEMO_BRAK_DANYCH · Brak oceny · brak wymaganej liczby dzieci 0–2.")
            st.markdown(
                "Miejsca na 1000 dzieci: **Brak danych**. Wynik: **Brak oceny**. "
                "Waga 0 dla podaży nie przywraca kwalifikacji. Rzeczywiste dane gmin pozostają pełne."
            )


def _weights(
    dataset,
    result,
    frame: pd.DataFrame,
    selected: list[str],
    dataset_sha256: str,
    methodology_sha256: str,
):
    st.subheader("Założenia i odporność porównania", icon=":material/tune:")
    st.caption(
        "Zmiana wag dotyczy tej sesji. Dane, regionalna kohorta i percentyle pozostają takie same."
    )
    with st.container(horizontal=True):
        st.button(
            "Równe wagi",
            key="reset_weights",
            on_click=_set_weights,
            args=(50, 50),
            icon=":material/restart_alt:",
        )
        st.button("Akcent na podaż", key="supply_preset", on_click=_set_weights, args=(80, 20))
        st.button(
            "Akcent na demografię", key="demography_preset", on_click=_set_weights, args=(20, 80)
        )
    for column, metric in zip(st.columns(2), COMPONENTS, strict=True):
        with column:
            st.slider(
                COMPONENTS[metric]["label"],
                min_value=0,
                max_value=100,
                step=5,
                key=f"weight_{metric}",
                help="Waga względna; aplikacja normalizuje sumę do 100%.",
            )
    st.markdown(
        "**Zastosowane wagi:** "
        + " · ".join(
            f"{COMPONENTS[m]['label']}: {_format(w * 100, 1)}%" for m, w in result.weights.items()
        )
    )
    rows = frame[frame["unit_id"].isin(selected)]
    baseline = apply_weights(result, None).frame.set_index("unit_id")["score"]
    if not rows.empty:
        changes = pd.DataFrame(
            {
                "Gmina": rows["display_name"],
                "Równe wagi [pkt]": rows["unit_id"].map(baseline),
                "Bieżący wynik [pkt]": rows["score"],
                "Zmiana [pkt]": rows["score"] - rows["unit_id"].map(baseline),
            }
        )
        st.dataframe(changes, hide_index=True, alt="Zmiana wyniku wobec scenariusza równych wag")
    if result.constant_components:
        st.info(
            "Stałe składowe nie różnicują gmin (percentyl 0,5): "
            + ", ".join(COMPONENTS[m]["label"] for m in result.constant_components)
        )
    contributions = []
    for _, row in rows.iterrows():
        for metric in COMPONENTS:
            contributions.append(
                {
                    "Gmina": row["display_name"],
                    "Składowa": COMPONENTS[metric]["label"],
                    "Surowa miara": row[metric],
                    "Jednostka": METRIC_LABELS[metric][1],
                    "Percentyl [0–1]": row.get(f"{metric}_percentile"),
                    "Wkład [pkt]": row.get(f"{metric}_contribution"),
                }
            )
    if contributions:
        st.dataframe(
            pd.DataFrame(contributions),
            hide_index=True,
            alt="Surowe miary, percentyle i wkłady składowych",
        )
    if len(result.cohort_ids) < 2:
        st.info("Mniej niż dwie gminy spełniają warunki; ranking i analiza pozycji są niedostępne.")
        return
    sensitivity = _sensitivity(
        dataset_sha256,
        methodology_sha256,
        result.year,
        tuple(sorted(result.weights.items())),
        result.cohort_ids,
        result,
    )
    summary = sensitivity.summary.copy()
    if "unit_id" not in summary:
        summary = summary.reset_index()
    summary = _enrich(summary, dataset.units)
    summary = summary[summary["unit_id"].isin(selected)]
    st.markdown("#### Zakres możliwych pozycji")
    scenario_count = sensitivity.count
    st.caption(
        f"{scenario_count} różnych wariantów: siatka wag co 0,1, presety i bieżący wariant. "
        "Zakres miejsc uwzględnia również remisy."
    )
    colors = _colors(selected)
    fig = go.Figure()
    for _, row in summary.iterrows():
        fig.add_trace(
            go.Scatter(
                x=[row["rank_min"], row["rank_max"]],
                y=[row["display_name"]] * 2,
                mode="lines+markers",
                name=row["display_name"],
                line={"color": colors[row["unit_id"]], "width": 8},
                marker={"size": 12},
                hovertemplate="Miejsce %{x}<extra>%{fullData.name}</extra>",
            )
        )
    fig.update_layout(
        showlegend=False,
        xaxis_title="Miejsce w regionalnej kohorcie",
        xaxis={"rangemode": "tozero"},
    )
    _chart(
        fig, "sensitivity_rank", "Zakres pozycji wybranych gmin przy zmianie samych wag", height=250
    )
    st.dataframe(
        summary[["display_name", "score_min", "score_max", "rank_min", "rank_max"]].rename(
            columns={
                "display_name": "Gmina",
                "score_min": "Wynik min [pkt]",
                "score_max": "Wynik max [pkt]",
                "rank_min": "Najwyższa pozycja",
                "rank_max": "Najniższa pozycja",
            }
        ),
        hide_index=True,
        alt="Zakres wyników i miejsc w scenariuszach wag",
    )
    pair_rows = []
    for first, second in combinations(selected, 2):
        pair = sensitivity.pairwise(first, second)
        pair_rows.append(
            {
                "Gmina A": frame.loc[frame["unit_id"] == first, "display_name"].iloc[0],
                "Gmina B": frame.loc[frame["unit_id"] == second, "display_name"].iloc[0],
                "A wyżej": pair["above"],
                "A niżej": pair["below"],
                "Remis": pair["tied"],
                "Warianty ocenione": pair["count"],
            }
        )
    if pair_rows:
        st.dataframe(
            pd.DataFrame(pair_rows), hide_index=True, alt="Relacje par gmin w wariantach wag"
        )
    st.caption(
        "Liczby i udziały wariantów opisują wybraną siatkę założeń; nie są prawdopodobieństwami."
    )


def _data(dataset, metrics: pd.DataFrame, result, selected: list[str]):
    st.subheader("Dane, definicje i odtwarzalność", icon=":material/database:")
    search = st.text_input(
        "Szukaj w słowniku",
        placeholder="Nazwa, identyfikator lub definicja…",
        key="dictionary_search",
    )
    derived = read_indicators().get("derived", [])
    definitions = []
    for definition in [*dataset.indicators, *derived]:
        metric = definition["metric_id"]
        label, unit, _ = METRIC_LABELS[metric]
        local = definition.get("kind") == "derived"
        inputs = ", ".join(definition.get("input_ids", []))
        definitions.append(
            {
                "Miara": label,
                "Rodzaj": "Wyliczona lokalnie" if local else "Cecha źródłowa GUS",
                "ID GUS / wejścia": inputs if local else str(definition["indicator_id"]),
                "Oryginalna nazwa GUS": "—" if local else definition["original_name"],
                "Jednostka": unit,
                "Okres": "Stan 31 grudnia",
                "Źródło": definition.get("metadata_url", definition.get("source_url", "")),
            }
        )
    definitions = pd.DataFrame(definitions)
    if search and not definitions.empty:
        mask = definitions.astype(str).apply(
            lambda row: search.casefold() in " ".join(row).casefold(), axis=1
        )
        definitions = definitions[mask]
    st.dataframe(
        definitions,
        hide_index=True,
        column_config={"Źródło": st.column_config.LinkColumn("Źródło", display_text="GUS BDL")},
        alt="Słownik źródłowych cech GUS z oryginalnymi nazwami i definicjami",
    )
    st.markdown("#### Miary pochodne")
    st.markdown(
        "**Udział dzieci 0–2 [%]** = 100 × dzieci 0–2 / ludność ogółem.\n\n"
        "**Miejsca na 1000 dzieci 0–2** = 1000 × miejsca w żłobkach i klubach / dzieci 0–2.\n\n"
        "**Placówki łącznie** = żłobki + kluby dziecięce; obie składowe muszą być dostępne."
    )
    st.caption(
        "Mianownik musi być dodatni i wszystkie wejścia poprawne. Relacja miejsc do populacji "
        "nie jest odsetkiem konkretnych dzieci, które otrzymały opiekę."
    )
    with st.expander("Normalizacja, kwalifikacja i remisy", expanded=True):
        st.markdown(
            "Wspólny zbiór odniesienia obejmuje gminy z kompletem obu wymaganych składowych "
            "w danym roku. Brak wymaganej miary wyklucza ocenę także przy jej wadze 0. "
            "Wybór gmin służy prezentacji i nie zmienia normalizacji."
        )
        st.latex(r"p_j = \frac{\overline{r}_j-1}{N-1},\qquad S=100\sum_j w_j p_j")
        st.caption(
            "r̄: średnia ranga z uwzględnieniem remisów; N: liczba gmin w kohorcie; S: wynik."
        )
        st.markdown(
            "Niższa podaż względna i wyższy udział dzieci 0–2 zwiększają sygnał do dalszych "
            "badań. Są to jawne założenia demonstracyjne. Stała składowa ma percentyl 0,5. "
            "Remis pokazujemy przedziałem miejsc; nazwa gminy nie rozstrzyga remisu."
        )
    st.markdown("#### Jakość gmina–rok–cecha")
    observations = dataset.observations.copy()
    scope = st.segmented_control(
        "Zakres jakości",
        ["Wybrane gminy", "Cały region"],
        default="Wybrane gminy",
        key="quality_scope",
    )
    if scope != "Cały region":
        observations = observations[observations["unit_id"].isin(selected)]
    status_counts = (
        observations.groupby(["year", "quality_status", "reason_code"], dropna=False)
        .size()
        .reset_index(name="Liczba")
    )
    status_counts["Status"] = status_counts["quality_status"].map(_status)
    st.dataframe(
        status_counts.rename(columns={"year": "Rok", "reason_code": "Kod przyczyny"})[
            ["Rok", "Status", "Kod przyczyny", "Liczba"]
        ],
        hide_index=True,
        alt="Liczby obserwacji według roku, statusu i przyczyny",
    )
    st.markdown("#### Kontrola wskaźnika miejsc na 1000 dzieci")
    ratio = ratio_summary(metrics.loc[metrics["year"] == result.year])
    columns = st.columns(2)
    columns[0].metric("Porównywalne pary ze wskaźnikiem GUS", ratio["paired_cells"])
    columns[1].metric("Różnice poza tolerancją", ratio["outside_tolerance"])
    st.caption(
        f"Cały region · rok {result.year}. Tolerancja zaokrąglenia wskaźnika GUS do "
        f"liczby całkowitej: {_format(ratio['tolerance'], 9)}. "
        f"Największa różnica bezwzględna: {_format(ratio['max_absolute_difference'], 9)}."
    )
    if ratio["outside_tolerance"]:
        st.warning(
            "Różnice poza tolerancją wymagają wyjaśnienia. Samo porównanie nie rozstrzyga, "
            "która seria jest błędna. Wartości pozostają bez dopasowania i imputacji."
        )
    elif not ratio["paired_cells"]:
        st.info("Brak porównywalnych par do kontroli wskaźnika w wybranym roku.")
    with st.expander("Obserwacje z wartościami surowymi, semantycznymi i pochodzeniem"):
        st.dataframe(
            observations,
            hide_index=True,
            alt="Obserwacje gmina–rok–cecha ze źródłem i atrybutem GUS",
        )
    with st.expander("Słownik atrybutów GUS"):
        st.dataframe(
            pd.DataFrame(dataset.attributes), hide_index=True, alt="Pobrany słownik atrybutów GUS"
        )
        st.caption(
            "Numeryczne 0 z atrybutem braku pozostaje brakiem. Nieznany atrybut blokuje analizę."
        )
    with st.expander("Pełne definicje i metadane źródłowe"):
        st.json({"cechy_źródłowe": dataset.indicators, "miary_pochodne": derived})
    st.markdown("#### Eksport bieżącego porównania")
    st.caption(
        f"Rok {result.year} • {len(selected)} wybranych gmin • snapshot {dataset.snapshot_id} • "
        f"metodologia {METHODOLOGY_VERSION}. CSV zachowuje statusy i pochodzenie; JSON odtwarza scenariusz."
    )
    with st.container(horizontal=True):
        st.download_button(
            "Pobierz dane CSV",
            export_csv(dataset, metrics, result, selected),
            file_name=f"region-comparison-{result.year}.csv",
            mime="text/csv",
            key="export_csv",
            disabled=not selected,
            icon=":material/download:",
            on_click="ignore",
        )
        st.download_button(
            "Pobierz konfigurację JSON",
            export_config(dataset, result, selected),
            file_name=f"region-comparison-{result.year}.json",
            mime="application/json",
            key="export_json",
            disabled=not selected,
            icon=":material/download:",
            on_click="ignore",
        )
    st.markdown(
        "Dane publiczne: [GUS BDL](https://bdl.stat.gov.pl/) · "
        "[Dokumentacja API](https://api.stat.gov.pl/Home/BdlApi). "
        "Autor aplikacji: Jonatan Tomaszewicz."
    )


def main() -> None:
    """Render the app without live requests to the GUS API."""
    st.set_page_config(
        page_title="RegionComparison · gminy Dolnego Śląska",
        page_icon=FAVICON,
        layout="wide",
    )
    with st.sidebar:
        st.markdown("## :material/analytics: RegionComparison")
        st.caption("DOLNY ŚLĄSK · DEMOGRAFIA I OPIEKA")
    st.caption("ANALIZA REGIONALNA / PUBLICZNE DANE GUS")
    st.title("Małe dzieci. Lokalne możliwości.")
    st.markdown("Porównaj gminy Dolnego Śląska i wybierz pytania do dalszego badania.")
    mode = os.getenv("REGION_DATA_MODE", "snapshot").lower()
    if mode not in {"snapshot", "postgres"}:
        st.error("Nieprawidłowy tryb danych. Ustaw REGION_DATA_MODE na snapshot lub postgres.")
        return
    try:
        with st.spinner("Wczytywanie zweryfikowanego zestawu danych…"):
            if mode == "postgres":
                url = os.getenv("DATABASE_URL")
                if not url:
                    st.error(
                        "Brak konfiguracji bazy PostgreSQL. Ustaw DATABASE_URL lub uruchom demo snapshot."
                    )
                    return
                dataset = _load_postgres(url, os.getenv("REGION_SNAPSHOT_ID"))
            else:
                path = Path(os.getenv("REGION_SNAPSHOT_PATH", str(DEFAULT_SNAPSHOT)))
                dataset = _load_sample(str(path), (path / "manifest.json").stat().st_mtime_ns)
    except Exception:
        # Connection URLs and exception text may contain credentials; do not render either.
        if mode == "postgres":
            st.error(
                "Nie można wczytać danych z PostgreSQL. Sprawdź uruchomienie bazy, migracje i zatwierdzony import."
            )
        else:
            st.error(
                "Nie można wczytać zatwierdzonego snapshotu. Sprawdź kompletność plików i uruchom walidację zestawu."
            )
        st.caption(
            "Aplikacja nie aktywuje częściowego importu. Instrukcje uruchomienia są w README."
        )
        return
    if dataset.units.empty or dataset.observations.empty or not dataset.years:
        st.info(
            "Zestaw nie zawiera danych do porównania. Zaimportuj kompletny, zweryfikowany snapshot."
        )
        return
    labels = _unit_labels(dataset.units)
    defaults = _default_selection(dataset.units)
    st.session_state.setdefault("weight_places_per_1000", 50)
    st.session_state.setdefault("weight_children_share_pct", 50)
    with st.sidebar:
        year = st.selectbox("Rok danych", list(reversed(dataset.years)), key="analysis_year")
        selected = st.multiselect(
            "Gminy do porównania (2–4)",
            list(labels),
            default=defaults,
            format_func=labels.get,
            max_selections=4,
            key="selected_units",
            placeholder="Wyszukaj nazwę gminy…",
        )
        st.caption("Wybór nie zmienia regionalnego zbioru odniesienia.")
        st.space("small")
        st.badge(
            "PostgreSQL" if mode == "postgres" else "Demo offline · snapshot",
            color="blue",
            icon=":material/database:",
        )
        timestamp = (
            dataset.manifest.get("finished_at")
            or dataset.manifest.get("completed_at")
            or dataset.manifest.get("completed_at_utc")
        )
        if timestamp:
            timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).strftime(
                "%d.%m.%Y · %H:%M UTC"
            )
        else:
            timestamp = "Brak daty w manifeście"
        st.caption(f"Pobrano: {timestamp}")
        st.caption(f"Zakres: {min(dataset.years)}–{max(dataset.years)}")
        st.caption(f"Snapshot: {dataset.snapshot_id}")
        st.caption(f"Metodologia: {METHODOLOGY_VERSION}")
    try:
        dataset_sha256 = dataset_fingerprint(dataset)
        methodology_sha256 = methodology_fingerprint()
        metrics = _metrics(dataset_sha256, methodology_sha256, dataset)
    except Exception:
        st.error(
            "Nie można wykonać porównania: dane są niezgodne z wymaganą metodologią. "
            "Sprawdź definicje cech i uruchom walidację snapshotu."
        )
        return
    weights = {m: st.session_state[f"weight_{m}"] for m in COMPONENTS}
    invalid_weights = not any(weights.values())
    if invalid_weights:
        st.error("Suma wag musi być dodatnia. Ustaw przynajmniej jedną wagę powyżej zera.")
        # Keep sliders reachable; suppress ranking computed with invalid inputs.
        for metric in COMPONENTS:
            st.slider(COMPONENTS[metric]["label"], 0, 100, step=5, key=f"weight_{metric}")
        st.button(
            "Przywróć równe wagi", on_click=_set_weights, args=(50, 50), key="reset_invalid_weights"
        )
        return
    try:
        result = evaluate(metrics, int(year), weights)
        frame = _enrich(result.frame, dataset.units)
    except Exception:
        st.error(
            "Nie można obliczyć wyniku porównawczego. Sprawdź zgodność danych, "
            "wybrany rok i parametry wag z metodologią."
        )
        return
    if len(result.cohort_ids) < 2:
        st.warning("Mniej niż dwie porównywalne gminy: wynik i ranking nie są publikowane.")
    _colors(selected)
    status = dataset.manifest.get("status", dataset.manifest.get("import_state", "complete"))
    status_label = {
        "complete": "kompletny",
        "partial": "częściowy",
        "incomplete": "niekompletny",
        "failed": "z błędem",
        "validated": "zweryfikowany",
        "blocked": "zablokowany",
    }.get(str(status), "o nieustalonym statusie")
    st.caption(
        f"{year} · {len(dataset.units)} pełnych gmin · zestaw {status_label} · źródło GUS BDL"
    )
    overview, comparison, profile, weights_tab, data = st.tabs(
        [
            "Przegląd regionu",
            "Porównanie gmin",
            "Profil i trendy",
            "Wagi i wrażliwość",
            "Dane i metodologia",
        ]
    )
    with overview:
        _overview(dataset, metrics, result, frame, selected)
    with comparison:
        _comparison(frame, result, selected)
    with profile:
        _profile(dataset, metrics, frame, labels, selected)
    with weights_tab:
        _weights(dataset, result, frame, selected, dataset_sha256, methodology_sha256)
    with data:
        _data(dataset, metrics, result, selected)
