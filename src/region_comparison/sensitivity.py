"""Deterministic simplex scenarios; proportions are not probabilities."""

from dataclasses import dataclass
from itertools import product

import pandas as pd

from region_comparison.config import COMPONENTS
from region_comparison.scoring import ScoringResult, apply_weights, normalize_weights


def weight_grid(base: dict, step: int = 10) -> list[dict]:
    keys = list(COMPONENTS)
    scenarios = [normalize_weights(base)]
    scenarios += [
        dict(zip(keys, (v / step for v in values), strict=True))
        for values in product(range(step + 1), repeat=len(keys))
        if sum(values) == step
    ]
    # Emphasis presets belong to the 0.1 grid, so deduplication preserves exact baseline.
    seen = set()
    unique = []
    for weights in scenarios:
        key = tuple(round(weights[k], 12) for k in keys)
        if key not in seen:
            unique.append(weights)
            seen.add(key)
    return unique


@dataclass
class SensitivityResult:
    summary: pd.DataFrame
    scenarios: pd.DataFrame
    count: int

    def pairwise(self, a: str, b: str) -> dict:
        scores = self.scenarios.pivot(index="scenario", columns="unit_id", values="score")
        if a not in scores or b not in scores:
            return {"above": 0, "below": 0, "tied": 0, "count": 0}
        valid = scores[[a, b]].dropna()
        return {
            "above": int((valid[a] > valid[b]).sum()),
            "below": int((valid[a] < valid[b]).sum()),
            "tied": int((valid[a] == valid[b]).sum()),
            "count": len(valid),
        }


def analyze(result: ScoringResult) -> SensitivityResult:
    grid = weight_grid(result.weights)
    frames = []
    for number, weights in enumerate(grid):
        frame = (
            apply_weights(result, weights)
            .frame[["unit_id", "score", "rank_min", "rank_max"]]
            .copy()
        )
        frame["scenario"] = number
        for name, weight in weights.items():
            frame[f"weight_{name}"] = weight
        frames.append(frame)
    scenarios = pd.concat(frames, ignore_index=True)
    summary = scenarios.groupby("unit_id", as_index=False).agg(
        score_min=("score", "min"),
        score_max=("score", "max"),
        rank_min=("rank_min", "min"),
        rank_max=("rank_max", "max"),
    )
    return SensitivityResult(summary, scenarios, len(grid))
