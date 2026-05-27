#!/usr/bin/env python
"""Generate daily_agent_signal using v0.22 (and v0.2 for comparison).

Usage:
    PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py \
        --db-path ~/.vntrader/agent_news_em_600309.db --vt-symbol 600309.SSE

    PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py \
        --db-path ~/.vntrader/agent_news_em_600309.db --compare
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from myQuant.news_ingestion.scoring.daily_aggregator import (
    run_v0_22_pipeline,
    run_v0_2_pipeline,
)


def load_signals(db_path: str, vt_symbol: str | None = None) -> list[dict]:
    """Load all agent_signal rows from the DB as dicts."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    
    if vt_symbol:
        rows = conn.execute(
            "SELECT * FROM agent_signal WHERE vt_symbol = ? ORDER BY trading_date, raw_news_id",
            (vt_symbol,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM agent_signal ORDER BY vt_symbol, trading_date, raw_news_id"
        ).fetchall()
    
    conn.close()
    return [dict(r) for r in rows]


def print_comparison(v0_2_results: list[dict], v0_22_results: list[dict]) -> None:
    """Print v0.2 vs v0.22 comparison."""
    # Index by (trading_date, vt_symbol)
    v2_map = {(r["trading_date"], r["vt_symbol"]): r for r in v0_2_results}
    v22_map = {(r["trading_date"], r["vt_symbol"]): r for r in v0_22_results}
    
    all_keys = sorted(set(v2_map.keys()) | set(v22_map.keys()))
    
    # Direction distribution
    v2_dirs = {"positive": 0, "negative": 0, "neutral": 0}
    v22_dirs = {"positive": 0, "negative": 0, "neutral": 0}
    for r in v0_2_results:
        v2_dirs[r["daily_direction"]] = v2_dirs.get(r["daily_direction"], 0) + 1
    for r in v0_22_results:
        v22_dirs[r["daily_direction"]] = v22_dirs.get(r["daily_direction"], 0) + 1
    
    print()
    print("=" * 60)
    print("v0.2 vs v0.22 Comparison")
    print("=" * 60)
    
    print(f"\nTotal days: v0.2={len(v0_2_results)}, v0.22={len(v0_22_results)}")
    
    print("\nDirection distribution:")
    print(f"  v0.2:  neg={v2_dirs['negative']}, neu={v2_dirs['neutral']}, pos={v2_dirs['positive']}")
    print(f"  v0.22: neg={v22_dirs['negative']}, neu={v22_dirs['neutral']}, pos={v22_dirs['positive']}")
    
    # Correlation
    common_keys = sorted(set(v2_map.keys()) & set(v22_map.keys()))
    if common_keys:
        v2_vals = [v2_map[k]["daily_agent_signal"] for k in common_keys]
        v22_vals = [v22_map[k]["daily_agent_signal"] for k in common_keys]
        
        n = len(common_keys)
        mean_v2 = sum(v2_vals) / n
        mean_v22 = sum(v22_vals) / n
        
        cov = sum((a - mean_v2) * (b - mean_v22) for a, b in zip(v2_vals, v22_vals)) / n
        std_v2 = (sum((a - mean_v2) ** 2 for a in v2_vals) / n) ** 0.5
        std_v22 = (sum((b - mean_v22) ** 2 for b in v22_vals) / n) ** 0.5
        
        corr = cov / (std_v2 * std_v22 + 1e-10)
        print(f"\nCorrelation (daily_agent_signal): {corr:.4f} (n={n})")
    
    # v0.22 specific stats
    if v0_22_results:
        event_counts = [r.get("event_count", 0) for r in v0_22_results]
        mixed_vals = [r.get("mixed_intensity", 0) for r in v0_22_results]
        print(f"\nv0.22 event_count: min={min(event_counts)}, max={max(event_counts)}, "
              f"mean={sum(event_counts)/len(event_counts):.1f}")
        print(f"v0.22 mixed_intensity: min={min(mixed_vals):.3f}, max={max(mixed_vals):.3f}, "
              f"mean={sum(mixed_vals)/len(mixed_vals):.3f}")
    
    # Top 10 days
    print("\nTop 10 days (v0.22):")
    sorted_v22 = sorted(v0_22_results, key=lambda r: abs(r["daily_agent_signal"]), reverse=True)[:10]
    for r in sorted_v22:
        print(f"  {r['trading_date']} {r['vt_symbol']}: {r['daily_agent_signal']:+.4f} "
              f"({r['daily_direction']}, events={r.get('event_count','?')})")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate daily_agent_signal for v0.22")
    parser.add_argument("--db-path", required=True, help="Path to agent news DB")
    parser.add_argument("--vt-symbol", default=None, help="Filter by vt_symbol (e.g. 600309.SSE)")
    parser.add_argument("--compare", action="store_true", help="Run v0.2 comparison")
    parser.add_argument("--output", default="", help="Output JSON file path (optional)")
    parser.add_argument("--persist", action="store_true", help="Persist to agent_daily_signal table in DB")
    args = parser.parse_args(argv)
    
    db_path = str(Path(args.db_path).expanduser())
    if not Path(db_path).exists():
        print(f"Error: DB not found: {db_path}", file=sys.stderr)
        return 1
    
    print(f"Loading signals from {db_path}...")
    rows = load_signals(db_path, args.vt_symbol)
    print(f"Loaded {len(rows)} signal rows")
    
    if not rows:
        print("No signals found.", file=sys.stderr)
        return 1
    
    # Relation type sample distribution
    from collections import Counter
    rt_counts = Counter(r.get("relation_type", "?") for r in rows)
    print("\nRelation type distribution:")
    for rt, count in rt_counts.most_common():
        print(f"  {rt}: {count} ({100*count/len(rows):.1f}%)")
    
    # Run v0.22
    print(f"\nRunning v0.22 pipeline...")
    v0_22_results = run_v0_22_pipeline(rows)
    print(f"v0.22: {len(v0_22_results)} daily records generated")
    
    # Run v0.2 for comparison
    if args.compare:
        print("Running v0.2 pipeline...")
        v0_2_results = run_v0_2_pipeline(rows)
        print(f"v0.2: {len(v0_2_results)} daily records generated")
        print_comparison(v0_2_results, v0_22_results)
    
    # Output JSON if requested
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(v0_22_results, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nSaved to {output_path}")

    # Persist to DB if requested
    if args.persist:
        from myQuant.news_ingestion.storage import AgentNewsSqliteRepository
        repo = AgentNewsSqliteRepository(db_path=db_path)
        saved = 0
        for rec in v0_22_results:
            repo.save_daily_signal(rec)
            saved += 1
        print(f"Persisted {saved} daily signals to {db_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
