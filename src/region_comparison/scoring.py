"""Fixed regional eligibility, percentile normalization and honest tie intervals."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from region_comparison.config import COMPONENTS, METHODOLOGY_VERSION

SCORE_PRECISION = 6


@dataclass
class ScoringResult:
    frame: pd.DataFrame
    weights: dict[str, float]
    cohort_ids: tuple[str, ...]
    year: int
    methodology_version: str = METHODOLOGY_VERSION
    constant_components: tuple[str, ...] = ()


def normalize_weights(weights: dict | None = None) -> dict[str, float]:
    weights = dict.fromkeys(COMPONENTS, 1.0) if weights is None else dict(weights)
    if set(weights) != set(COMPONENTS):
        raise ValueError("Weights must contain exactly the methodology components")
    values = np.array(list(weights.values()), dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or values.max() <= 0:
        raise ValueError("Weights must be finite, nonnegative and have a positive sum")
    scaled = values / values.max()
    return {key: float(value / scaled.sum()) for key, value in zip(weights, scaled, strict=True)}


def rank_intervals(scores: pd.Series) -> tuple[pd.Series, pd.Series]:
    rounded = scores.round(SCORE_PRECISION)
    return (
        rounded.rank(method="min", ascending=False),
        rounded.rank(method="max", ascending=False),
    )


def apply_weights(result: ScoringResult, weights: dict | None) -> ScoringResult:
    """Reuse the cohort and percentiles, including for weights equal to zero."""
    normalized = normalize_weights(weights)
    frame = result.frame.copy()
    frame["score"] = np.nan
    mask = frame["eligible"]
    if len(result.cohort_ids) >= 2:
        score = pd.Series(0.0, index=frame.index[mask])
        for metric, weight in normalized.items():
            column = f"{metric}_contribution"
            frame[column] = np.nan
            frame.loc[mask, column] = 100 * weight * frame.loc[mask, f"{metric}_percentile"]
            score += frame.loc[mask, column]
        frame.loc[mask, "score"] = score.round(SCORE_PRECISION)
    frame["rank_min"], frame["rank_max"] = rank_intervals(frame["score"])
    return ScoringResult(
        frame,
        normalized,
        result.cohort_ids,
        result.year,
        result.methodology_version,
        result.constant_components,
    )


def evaluate(metrics: pd.DataFrame, year: int, weights: dict | None = None) -> ScoringResult:
    frame = metrics.loc[metrics["year"] == int(year)].copy().reset_index(drop=True)
    if frame["unit_id"].duplicated().any():
        raise ValueError("Duplicate municipalities in reference cohort")
    required = list(COMPONENTS)
    missing = ~np.isfinite(frame[required].astype(float))
    frame["eligible"] = ~missing.any(axis=1)
    frame["eligibility_reason"] = [
        ";".join(
            f"{metric}:{row.get(f'{metric}_reason', 'missing')}"
            for metric in required
            if pd.isna(row[metric]) or not np.isfinite(row[metric])
        )
        for row in frame.to_dict("records")
    ]
    cohort = tuple(sorted(frame.loc[frame["eligible"], "unit_id"].astype(str)))
    constant = []
    for metric, definition in COMPONENTS.items():
        frame[f"{metric}_percentile"] = np.nan
        values = frame.loc[frame["eligible"], metric]
        if len(cohort) > 1:
            if values.nunique() == 1:
                frame.loc[frame["eligible"], f"{metric}_percentile"] = 0.5
                constant.append(metric)
            else:
                ranks = values.rank(method="average", ascending=definition["ascending"])
                frame.loc[frame["eligible"], f"{metric}_percentile"] = (ranks - 1) / (
                    len(cohort) - 1
                )
    if len(cohort) < 2:
        frame.loc[frame["eligible"], "eligibility_reason"] = "insufficient_reference_cohort"
    result = ScoringResult(frame, {}, cohort, int(year), constant_components=tuple(constant))
    return apply_weights(result, weights)
