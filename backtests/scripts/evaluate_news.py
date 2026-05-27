#!/usr/bin/env python
"""Evaluate ALL mapped news items with a specified LLM model.

Must be run AFTER fetch_news.py. Reads from an agent news DB, evaluates
every mapped item, and persists signals.

Usage::

    conda run -n vnpy43 python backtests/scripts/evaluate_news.py \\
        --db-path ~/.vntrader/agent_news_em_600309.db \\
        --provider deepseek

    conda run -n vnpy43 python backtests/scripts/evaluate_news.py \\
        --db-path ~/.vntrader/agent_news_em_600309.db \\
        --provider opencode-go --model qwen3.5-plus --workers 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tqdm import tqdm  # noqa: E402

from myQuant.news_ingestion.contracts import (  # noqa: E402
    RawNewsItem,
    Source,
    SourceCategory,
)
from myQuant.news_ingestion.llm.evaluator import DeepSeekNewsEvaluator  # noqa: E402
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository  # noqa: E402


def _datetime_or_none(value: str | None) -> datetime | None:
    if value is None:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value).split("+")[0].split("Z")[0].strip(), fmt)
        except ValueError:
            continue
    return None


def _load_mapped_news(db_path: Path) -> list[tuple[int, str, str]]:
    """Return (raw_news_id, symbol, exchange) for all mapped items."""
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute("SELECT raw_news_id, symbol, exchange FROM agent_news_symbol ORDER BY raw_news_id").fetchall()
    conn.close()
    return [(r[0], r[1], r[2]) for r in rows]


def _load_raw_news_items(db_path: Path, raw_ids: list[int]) -> dict[int, str]:
    """Return {raw_news_id: content} for the given IDs."""
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    placeholders = ",".join("?" * len(raw_ids))
    rows = conn.execute(
        f"SELECT id, content FROM agent_raw_news WHERE id IN ({placeholders})", raw_ids
    ).fetchall()
    conn.close()
    return {r[0]: r[1] or "" for r in rows}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate mapped news with LLM")
    parser.add_argument("--db-path", required=True, help="Path to agent news DB")
    parser.add_argument("--provider", default="deepseek", choices=["deepseek", "opencode-go", "llama_cpp"])
    parser.add_argument("--model", default="", help="Model name (auto-detected from provider)")
    parser.add_argument("--workers", type=int, default=3, help="LLM concurrency (default: 3)")
    parser.add_argument("--max-items", type=int, default=0, help="Limit items (0=all)")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path).expanduser()
    if not db_path.exists():
        print(f"Error: DB not found: {db_path}", file=sys.stderr)
        return 1

    # --- Resolve evaluator ---
    if args.provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            print("Error: DEEPSEEK_API_KEY not set", file=sys.stderr)
            return 1
        evaluator = DeepSeekNewsEvaluator()
    elif args.provider == "opencode-go":
        api_key = os.environ.get("OPENCODE_GO_API_KEY", "")
        if not api_key:
            print("Error: OPENCODE_GO_API_KEY not set", file=sys.stderr)
            return 1
        model = args.model or "qwen3.5-plus"
        evaluator = DeepSeekNewsEvaluator.for_opencode_go(model=model)
    elif args.provider == "llama_cpp":
        base_url = os.environ.get("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080/v1")
        evaluator = DeepSeekNewsEvaluator.for_llama_cpp(base_url=base_url)
    else:
        print(f"Error: unknown provider {args.provider}", file=sys.stderr)
        return 1

    # --- Load mapped items ---
    mapped = _load_mapped_news(db_path)
    if args.max_items > 0:
        mapped = mapped[: args.max_items]

    raw_ids = [m[0] for m in mapped]
    raw_items = _load_raw_news_full(db_path, raw_ids)

    repo = AgentNewsSqliteRepository(db_path=db_path, enable_backup=True)
    repo.initialize_schema()

    # Cache already-evaluated raw_news_ids to skip duplicates
    _cached_existing_signal_ids: set[int] = set()
    import sqlite3 as _sql
    _con = _sql.connect(f"file:{db_path}?mode=ro", uri=True)
    for row in _con.execute(
        "SELECT DISTINCT raw_news_id FROM agent_llm_run WHERE model = ? AND status = 'success'",
        (evaluator.model,),
    ).fetchall():
        _cached_existing_signal_ids.add(row[0])
    _con.close()

    success = 0
    fail_count = 0
    total_tokens_in = 0
    total_tokens_out = 0
    t_start = datetime.now(timezone.utc)

    pbar = tqdm(total=len(mapped), desc=f"{evaluator.provider}/{evaluator.model}",
                unit="news", dynamic_ncols=True)

    for raw_id, symbol, exchange in mapped:
        raw = raw_items.get(raw_id)
        if raw is None:
            pbar.update(1)
            continue

        # Skip already-evaluated
        if raw_id in _cached_existing_signal_ids:
            success += 1
            pbar.update(1)
            continue

        from myQuant.news_ingestion.recall.engine import MappedNews  # noqa: E402
        from myQuant.news_ingestion.contracts import RelationType  # noqa: E402

        mapped_news = MappedNews(
            raw_news_id=raw_id,
            vt_symbol=f"{symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            relation_hint=RelationType.DIRECT_COMPANY,
            mapping_method="direct",
            mapping_confidence=1.0,
            keywords_matched=(),
            available_at=raw.published_at or datetime.now(timezone.utc),
        )

        try:
            run_record, output_record, signal = evaluator.evaluate(mapped_news, raw)
            db_run_id = repo.save_llm_run(run_record)
            output_record.llm_run_id = db_run_id
            repo.save_llm_output(output_record)
            if signal:
                signal.llm_run_id = db_run_id
                repo.save_signal(signal)
                success += 1
            else:
                fail_count += 1
            tok = output_record.token_usage
            total_tokens_in += tok.get("prompt_tokens", 0)
            total_tokens_out += tok.get("completion_tokens", 0)
        except Exception:
            fail_count += 1

        pbar.update(1)
        pbar.set_postfix({"✅": success, "❌": fail_count, "in": total_tokens_in, "out": total_tokens_out, "": raw.title[:30]})
    pbar.close()
    repo.close()

    print(json.dumps({
        "provider": args.provider,
        "model": evaluator.model,
        "mapped_count": len(mapped),
        "signal_count": success,
    }, ensure_ascii=False, indent=2))
    return 0


def _load_raw_news_full(db_path: Path, raw_ids: list[int]) -> dict[int, RawNewsItem]:
    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(raw_ids))
    rows = conn.execute(
        f"SELECT * FROM agent_raw_news WHERE id IN ({placeholders})", raw_ids
    ).fetchall()
    conn.close()
    result: dict[int, RawNewsItem] = {}
    for row in rows:
        d = dict(row)
        result[d["id"]] = RawNewsItem(
            source=Source(d.get("source", "eastmoney")),
            source_category=SourceCategory(d.get("source_category", "financial_news")),
            title=d.get("title", ""),
            content=d.get("content", ""),
            content_hash=d.get("content_hash", ""),
            source_item_id=d.get("source_item_id", ""),
            url=d.get("url", ""),
            published_at=_datetime_or_none(d.get("published_at")),
            language=d.get("language", "zh"),
            body_status=d.get("body_status", ""),
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
