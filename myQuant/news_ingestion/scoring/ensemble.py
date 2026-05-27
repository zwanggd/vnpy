from __future__ import annotations
from statistics import mean

from .config import ENSEMBLE_AGREEMENT_BASE, ENSEMBLE_AGREEMENT_WEIGHT


def ensemble_model_scores(row_scores: list[float]) -> float:
    """Ensemble multiple model scores for the same (raw_news_id, vt_symbol).

    Grouping dimension: raw_news_id + vt_symbol
    Algorithm:
        model_mean = mean(row_scores)
        agreement = abs(model_mean) / (mean(abs(x) for x in row_scores) + 1e-6)
        news_score = model_mean * (BASE + WEIGHT * agreement)
    """
    if not row_scores:
        return 0.0

    model_mean = mean(row_scores)
    mean_abs = mean(abs(x) for x in row_scores)

    if mean_abs < 1e-6:
        return 0.0

    agreement = abs(model_mean) / (mean_abs + 1e-6)
    agreement = max(0.0, min(1.0, agreement))

    return model_mean * (ENSEMBLE_AGREEMENT_BASE + ENSEMBLE_AGREEMENT_WEIGHT * agreement)
