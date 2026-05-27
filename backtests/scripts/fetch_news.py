#!/usr/bin/env python
"""Fetch stock news into agent DB (no LLM evaluation).

Usage::

    conda run -n vnpy43 python backtests/scripts/fetch_news.py \\
        --start 2020-01-14 --end 2026-05-15 \\
        --symbols 600309.SSE,600036.SSE,688256.SSE \\
        --sources eastmoney \\
        --agent-db-path ~/.vntrader/agent_news_em_600309.db
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from myQuant.news_ingestion import RecallStrength, Source  # noqa: E402
from myQuant.news_ingestion.pipeline import BackfillPipeline  # noqa: E402
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository  # noqa: E402


def parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch stock news into agent DB")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--symbols", default="", help="Comma-separated vt_symbols")
    parser.add_argument("--agent-db-path", required=True, help="Path to agent news DB")
    parser.add_argument("--sources", default="eastmoney", help="Comma-separated source names (default: eastmoney)")
    parser.add_argument("--recall-strength", default="medium", choices=["low", "medium", "high"])
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("Error: --symbols is required", file=sys.stderr)
        return 1

    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]
    source_map = {"eastmoney": Source.EASTMONEY, "cninfo": Source.CNINFO, "cls_telegraph": Source.CLS_TELEGRAPH}
    sources = tuple(source_map[n] for n in source_names if n in source_map)
    if not sources:
        print("Error: no valid sources specified", file=sys.stderr)
        return 1

    db_path = Path(args.agent_db_path).expanduser()
    repo = AgentNewsSqliteRepository(db_path=db_path, enable_backup=True)
    pipeline = BackfillPipeline(repo=repo)

    print(f"[fetch] {len(symbols)} symbols, sources: {[s.value for s in sources]}, {args.start}~{args.end}")
    result = pipeline.run(
        start=parse_date(args.start),
        end=parse_date(args.end),
        symbols=symbols,
        sources=sources,
        recall_strength=RecallStrength(args.recall_strength),
        skip_llm=True,
        resume=False,
    )

    summary = {
        "run_id": result.run_id,
        "raw_count": result.raw_count,
        "mapped_count": result.mapped_count,
        "signal_count": result.signal_count,
        "errors": result.errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
