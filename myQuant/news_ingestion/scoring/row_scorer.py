from __future__ import annotations
from .config import (
    RELATION_WEIGHT, DEFAULT_RELATION_WEIGHT,
    HORIZON_WEIGHT, DEFAULT_HORIZON_WEIGHT,
    STRENGTH_EXPONENT, CONFIDENCE_FLOOR, CONFIDENCE_SCALE,
)


def direction_sign(impact_direction: str) -> int:
    if impact_direction == "positive":
        return 1
    elif impact_direction == "negative":
        return -1
    return 0


def compute_strength_eff(impact_strength: float) -> float:
    s = max(0.0, min(1.0, float(impact_strength)))
    return s ** STRENGTH_EXPONENT


def compute_confidence_eff(confidence: float) -> float:
    c = max(0.0, min(1.0, float(confidence)))
    raw = (c - CONFIDENCE_FLOOR) / CONFIDENCE_SCALE
    return max(0.0, min(1.0, raw))


def compute_relation_weight(relation_type: str) -> float:
    return RELATION_WEIGHT.get(relation_type, DEFAULT_RELATION_WEIGHT)


def compute_horizon_weight(time_horizon: str) -> float:
    return HORIZON_WEIGHT.get(time_horizon, DEFAULT_HORIZON_WEIGHT)


def compute_row_score(
    impact_direction: str,
    impact_strength: float,
    confidence: float,
    relation_type: str,
    time_horizon: str,
) -> tuple[int, float]:
    dsign = direction_sign(impact_direction)
    if dsign == 0:
        return (0, 0.0)
    s_eff = compute_strength_eff(impact_strength)
    c_eff = compute_confidence_eff(confidence)
    r_w = compute_relation_weight(relation_type)
    h_w = compute_horizon_weight(time_horizon)
    row_score = dsign * s_eff * c_eff * r_w * h_w
    return (dsign, row_score)


def compute_row_score_from_dict(row: dict) -> tuple[int, float]:
    return compute_row_score(
        impact_direction=row.get("impact_direction", "unknown"),
        impact_strength=row.get("impact_strength", 0.0),
        confidence=row.get("confidence", 0.0),
        relation_type=row.get("relation_type", "unknown"),
        time_horizon=row.get("time_horizon", "unknown"),
    )
