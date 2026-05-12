#!/usr/bin/env python
"""Offline agent news backfill CLI.

Usage::

    conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py \\
        --start 2024-01-01 --end 2024-01-31 \\
        --symbols 300750.SZSE --recall-strength medium \\
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from myQuant.news_ingestion import RecallStrength, Source  # noqa: E402
from myQuant.news_ingestion.pipeline import BackfillPipeline  # noqa: E402
from myQuant.news_ingestion.profiles import discover_vt_symbols_from_market_db  # noqa: E402
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository  # noqa: E402


def parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Agent News v0.1 offline backfill pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start date YYYY-MM-DD (required)",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date YYYY-MM-DD (required)",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated vt_symbols, e.g. 300750.SZSE,600519.SSE",
    )
    parser.add_argument(
        "--symbols-from-market-db",
        action="store_true",
        help="Discover symbols from market DB",
    )
    parser.add_argument(
        "--market-db-path",
        default="~/.vntrader/database.db",
        help="Path to market database (default: ~/.vntrader/database.db)",
    )
    parser.add_argument(
        "--agent-db-path",
        default="~/.vntrader/agent_news.db",
        help="Path to agent news database (default: ~/.vntrader/agent_news.db)",
    )
    parser.add_argument(
        "--sources",
        default="cninfo,cls_telegraph,eastmoney",
        help="Comma-separated source names (default: cninfo,cls_telegraph,eastmoney)",
    )
    parser.add_argument(
        "--recall-strength",
        default="medium",
        choices=["low", "medium", "high"],
        help="Recall strength: low, medium, or high (default: medium)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: no live HTTP, no LLM calls",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM evaluation",
    )
    parser.add_argument(
        "--no-skip-llm",
        action="store_true",
        help="Explicitly enable LLM evaluation (requires DEEPSEEK_API_KEY)",
    )
    parser.add_argument(
        "--max-llm-items",
        type=int,
        default=0,
        help="Max LLM evaluations (0 = no cap)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume: skip already saved raw news",
    )
    parser.add_argument(
        "--report-path",
        default="",
        help="Optional path to write run report",
    )

    args = parser.parse_args(argv)

    # -- Validate at least one symbol source -------------------------------
    if not args.symbols and not args.symbols_from_market_db:
        parser.error("Must specify --symbols or --symbols-from-market-db")

    # -- Resolve symbols ----------------------------------------------------
    if args.symbols_from_market_db:
        symbols = discover_vt_symbols_from_market_db(
            Path(args.market_db_path).expanduser()
        )
        print(f"[discover] {len(symbols)} symbols from market DB", file=sys.stderr)
    else:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    # -- Resolve sources ----------------------------------------------------
    source_map = {
        "cninfo": Source.CNINFO,
        "cls_telegraph": Source.CLS_TELEGRAPH,
        "eastmoney": Source.EASTMONEY,
    }
    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]
    sources = tuple(source_map[name] for name in source_names if name in source_map)

    if not sources:
        print("Error: no valid sources specified", file=sys.stderr)
        return 1

    recall_strength = RecallStrength(args.recall_strength)

    # -- Init repo ----------------------------------------------------------
    if args.dry_run:
        repo = AgentNewsSqliteRepository(db_path=None)
    else:
        repo = AgentNewsSqliteRepository(
            db_path=Path(args.agent_db_path).expanduser()
        )

    # -- Determine skip-llm behavior ---------------------------------------
    do_skip_llm = args.skip_llm
    evaluator = None

    if args.no_skip_llm and not args.dry_run:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            print(
                "Warning: DEEPSEEK_API_KEY not set. LLM evaluation will be skipped.",
                file=sys.stderr,
            )
            do_skip_llm = True
        else:
            from myQuant.news_ingestion.llm.evaluator import DeepSeekNewsEvaluator  # noqa: E402
            evaluator = DeepSeekNewsEvaluator()
            do_skip_llm = False
    elif args.no_skip_llm and args.dry_run:
        print(
            "Warning: --no-skip-llm is incompatible with --dry-run. LLM skipped.",
            file=sys.stderr,
        )
        do_skip_llm = True

    # -- Run pipeline -------------------------------------------------------
    pipeline = BackfillPipeline(
        repo=repo,
        dry_run=args.dry_run,
        evaluator=evaluator,
    )

    result = pipeline.run(
        start=parse_date(args.start),
        end=parse_date(args.end),
        symbols=symbols,
        sources=sources,
        recall_strength=recall_strength,
        max_llm_items=args.max_llm_items,
        skip_llm=do_skip_llm,
        resume=args.resume,
    )

    # -- Print summary ------------------------------------------------------
    summary = {
        "run_id": result.run_id,
        "raw_count": result.raw_count,
        "mapped_count": result.mapped_count,
        "signal_count": result.signal_count,
        "errors": result.errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # -- Write report if requested ------------------------------------------
    if args.report_path:
        from myQuant.news_ingestion.reporting import generate_report  # noqa: E402

        report_config: dict = {
            "start": args.start,
            "end": args.end,
            "symbols": symbols,
            "sources": source_names,
            "recall_strength": args.recall_strength,
            "command": " ".join(argv) if argv else "run_agent_news_backfill.py",
            "source_coverage": result.source_coverage,
            "signals": result.signals,
            "llm_run_count": result.llm_run_count,
            "invalid_signals": result.invalid_signals,
        }
        report_text = generate_report(result, report_config)

        report_path = Path(args.report_path).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"[report] written to {report_path}", file=sys.stderr)

    return 0 if not result.errors else 2


if __name__ == "__main__":
    sys.exit(main())
