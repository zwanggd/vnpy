"""Signal generation: daily aggregation, row scoring."""
from myQuant.news_ingestion.scoring.daily_aggregator import (
    aggregate_daily_signal,
    compute_daily_direction,
    run_v0_22_pipeline,
    run_v0_2_pipeline,
)
from myQuant.news_ingestion.scoring.row_scorer import compute_row_score
from myQuant.news_ingestion.scoring.ensemble import ensemble_model_scores
from myQuant.news_ingestion.scoring.event_dedup import generate_event_key

__all__ = [
    "aggregate_daily_signal",
    "compute_daily_direction",
    "run_v0_22_pipeline",
    "run_v0_2_pipeline",
    "compute_row_score",
    "ensemble_model_scores",
    "generate_event_key",
]
