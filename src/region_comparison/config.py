"""Versioned analytical configuration; no credentials are stored here."""

from pathlib import Path

import yaml

from region_comparison.paths import ROOT

DEFAULT_SNAPSHOT = ROOT / "data" / "sample"
METHODOLOGY_VERSION = "1.0.0"
COMPONENTS = {
    "places_per_1000": {"label": "Niższa podaż względna", "ascending": False},
    "children_share_pct": {"label": "Wyższy udział dzieci 0–2", "ascending": True},
}
SOURCE_METRICS = {
    "population_total": "453371",
    "children_0_2": "453372",
    "care_places": "1649554",
    "children_in_care": "1649557",
    "nurseries": "377234",
    "child_clubs": "377225",
    "gus_places_per_1000": "1649860",
}


def read_indicators(path: Path | None = None) -> dict:
    with (path or ROOT / "config" / "indicators.yml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)
