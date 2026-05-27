from __future__ import annotations
import math
from collections import defaultdict
from datetime import datetime
from statistics import median

from .config import (
    DAILY_TEMPERATURE, MIXED_PENALTY_COEFF,
    POSITIVE_THRESHOLD, NEGATIVE_THRESHOLD,
    STRENGTH_EXPONENT, CONFIDENCE_FLOOR, CONFIDENCE_SCALE,
    RELATION_WEIGHT, DEFAULT_RELATION_WEIGHT,
    HORIZON_WEIGHT, DEFAULT_HORIZON_WEIGHT,
    CONFIG_VERSION, AGGREGATION_VERSION,
)
from .row_scorer import compute_row_score
from .ensemble import ensemble_model_scores
from .event_dedup import generate_event_key


def calc_mixed_intensity(rows: list[dict]) -> float:
    """Compute mixed risk penalty from impact_direction=='mixed' rows.
    Uses the same strength_eff * confidence_eff * relation_weight * horizon_weight
    calculation as row_scorer, but direction_sign is NOT applied.
    """
    total = 0.0
    for r in rows:
        if r.get("impact_direction") != "mixed":
            continue
        s = max(0.0, min(1.0, float(r.get("impact_strength", 0))))
        strength_eff = s ** STRENGTH_EXPONENT
        c = max(0.0, min(1.0, float(r.get("confidence", 0))))
        confidence_eff = max(0.0, min(1.0, (c - CONFIDENCE_FLOOR) / CONFIDENCE_SCALE))
        rw = RELATION_WEIGHT.get(r.get("relation_type", ""), DEFAULT_RELATION_WEIGHT)
        hw = HORIZON_WEIGHT.get(r.get("time_horizon", ""), DEFAULT_HORIZON_WEIGHT)
        total += strength_eff * confidence_eff * rw * hw
    return total


def compute_daily_direction(daily_signal: float) -> str:
    if daily_signal >= POSITIVE_THRESHOLD:
        return "positive"
    elif daily_signal <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def aggregate_daily_signal(
    event_scores: list[float],
    mixed_intensity: float,
    temperature: float = DAILY_TEMPERATURE,
) -> float:
    """Aggregate event scores into a daily signal.

    raw_daily = sum(event_scores) / sqrt(m)  where m = number of events
    risk_penalty = 1 / (1 + coeff * mixed_intensity)
    daily = tanh(raw_daily * risk_penalty / temperature)
    """
    if not event_scores:
        return 0.0
    m = len(event_scores)
    raw_daily = sum(event_scores) / math.sqrt(m)
    risk_penalty = 1.0 / (1.0 + MIXED_PENALTY_COEFF * mixed_intensity)
    raw_daily *= risk_penalty
    daily = math.tanh(raw_daily / temperature)
    return max(-1.0, min(1.0, daily))


def run_v0_22_pipeline(rows: list[dict]) -> list[dict]:
    """Full v0.22 pipeline: row_score → ensemble → event dedup → daily aggregate.

    Input: list of dicts, each representing one agent_signal row with keys:
        raw_news_id, llm_run_id, vt_symbol, trading_date, event,
        impact_direction, impact_strength, confidence, relation_type, time_horizon

    Output: list of dicts, one per (trading_date, vt_symbol), with keys:
        trading_date, vt_symbol, daily_agent_signal, daily_direction,
        event_count, raw_daily, mixed_intensity, risk_penalty, version
    """
    # Step 1: Compute row_score for each signal
    scored_rows = []
    for r in rows:
        dsign, row_score = compute_row_score(
            impact_direction=r.get("impact_direction", "unknown"),
            impact_strength=r.get("impact_strength", 0.0),
            confidence=r.get("confidence", 0.0),
            relation_type=r.get("relation_type", "unknown"),
            time_horizon=r.get("time_horizon", "unknown"),
        )
        scored_rows.append({**r, "row_score": row_score, "direction_sign": dsign})

    # Step 2: Ensemble by (raw_news_id, vt_symbol) → news_score
    news_groups = defaultdict(list)
    for r in scored_rows:
        key = (r["raw_news_id"], r["vt_symbol"])
        news_groups[key].append(r["row_score"])

    news_scores = {}
    for key, scores in news_groups.items():
        news_scores[key] = ensemble_model_scores(scores)

    # Attach news_score and event_key to each row
    for r in scored_rows:
        key = (r["raw_news_id"], r["vt_symbol"])
        r["news_score"] = news_scores[key]
        r["event_key"] = generate_event_key(r.get("event"), r["raw_news_id"])

    # Step 3: Event-level aggregation (median of news_scores for same event_key)
    event_groups = defaultdict(list)
    for r in scored_rows:
        key = (r["trading_date"], r["vt_symbol"], r["event_key"])
        event_groups[key].append(r["news_score"])

    event_scores_map = {}
    for key, scores in event_groups.items():
        event_scores_map[key] = median(scores)

    # Step 4: Daily aggregation
    daily_groups = defaultdict(lambda: {"event_scores": [], "rows": []})
    for r in scored_rows:
        dt = r["trading_date"]
        vs = r["vt_symbol"]
        daily_groups[(dt, vs)]["rows"].append(r)

    # Collect event scores per day
    for key, scores in event_scores_map.items():
        dt, vs, ek = key
        daily_groups[(dt, vs)]["event_scores"].append(scores)

    # Step 5: Compute daily signals
    results = []
    for (dt, vs), group in sorted(daily_groups.items()):
        event_scores = group["event_scores"]
        m = len(event_scores)
        mixed_int = calc_mixed_intensity(group["rows"])
        daily_sig = aggregate_daily_signal(event_scores, mixed_int)
        direction = compute_daily_direction(daily_sig)

        if event_scores:
            raw_daily = sum(event_scores) / math.sqrt(m)
        else:
            raw_daily = 0.0
        risk_pen = 1.0 / (1.0 + MIXED_PENALTY_COEFF * mixed_int)

        results.append({
            "trading_date": dt,
            "vt_symbol": vs,
            "signal_version": CONFIG_VERSION,
            "daily_agent_signal": round(daily_sig, 6),
            "daily_direction": direction,
            "agent_label": "v0.22",
            "raw_daily_signal": round(raw_daily, 6),
            "news_count": 0,
            "event_count": m,
            "model_count": 0,
            "mixed_intensity": round(mixed_int, 6),
            "risk_penalty": round(risk_pen, 6),
            "created_at": datetime.now().isoformat(),
        })

    return results


# ── v0.2 (original) formula for comparison ──

def run_v0_2_pipeline(rows: list[dict]) -> list[dict]:
    """Original v0.2 formula: SUM(impact_strength * confidence) / SQRT(n) per day.
    Direction: ≥0.25 positive, ≤-0.25 negative, else neutral.
    """
    daily_data = defaultdict(lambda: {"scores": [], "pos": 0, "neg": 0, "neu": 0})

    for r in rows:
        dt = r.get("trading_date", "")
        vs = r.get("vt_symbol", "")
        d = (dt, vs)
        direction = r.get("impact_direction", "neutral")
        score = float(r.get("impact_strength", 0)) * float(r.get("confidence", 0))
        if direction == "positive":
            daily_data[d]["scores"].append(score)
            daily_data[d]["pos"] += 1
        elif direction == "negative":
            daily_data[d]["scores"].append(-score)
            daily_data[d]["neg"] += 1
        else:
            daily_data[d]["neu"] += 1

    results = []
    for (dt, vs), dd in sorted(daily_data.items()):
        n = len(dd["scores"])
        if n == 0:
            sig = 0.0
        else:
            sig = max(-1.0, min(1.0, sum(dd["scores"]) / math.sqrt(n)))
        direction = compute_daily_direction(sig)
        results.append({
            "trading_date": dt,
            "vt_symbol": vs,
            "signal_version": "v0.2",
            "daily_agent_signal": round(sig, 6),
            "daily_direction": direction,
            "agent_label": "v0.2",
            "raw_daily_signal": round(sig, 6),
            "news_count": n,
            "event_count": 0,
            "model_count": 0,
            "mixed_intensity": 0.0,
            "risk_penalty": 1.0,
            "created_at": datetime.now().isoformat(),
        })
    return results
