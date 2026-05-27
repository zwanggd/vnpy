#!/usr/bin/env python
"""Evaluate ALL unevaluated mapped news items with LLM (DeepSeek API / local Qwen).

Reads from any agent_news DB, finds agent_news_symbol rows whose raw_news_id
has no corresponding signal, constructs MappedNews + RawNewsItem, runs LLM
evaluation, and persists results.

Usage::

    conda run -n vnpy43 python backtests/scripts/eval_all_unevaluated.py \\
        --db-path ~/.vntrader/agent_news_600309.db \\
        --provider deepseek --max-items 10

    conda run -n vnpy43 python backtests/scripts/eval_all_unevaluated.py \\
        --db-path ~/.vntrader/agent_news_688256.db \\
        --provider llama_cpp --workers 4
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tqdm import tqdm  # noqa: E402

from myQuant.news_ingestion.contracts import (  # noqa: E402
    RawNewsItem,
    RelationType,
    Source,
    SourceCategory,
)
from myQuant.news_ingestion.llm.evaluator import DeepSeekNewsEvaluator  # noqa: E402
from myQuant.news_ingestion.recall.engine import MappedNews  # noqa: E402
from myQuant.news_ingestion.storage.sqlite import (  # noqa: E402
    AgentNewsSqliteRepository,
)

# ─────────────────────────────────────────────────────────────────────
# SQL: find all mapped news items that have NOT been evaluated yet
# ─────────────────────────────────────────────────────────────────────
_UNEVALUATED_QUERY = """
SELECT
    ans.raw_news_id,
    ans.vt_symbol,
    ans.symbol,
    ans.exchange,
    ans.relation_hint,
    ans.mapping_method,
    ans.mapping_confidence,
    ans.keywords_matched_json,
    rn.id          AS rn_id,
    rn.title,
    rn.content,
    rn.source,
    rn.source_category,
    rn.source_item_id,
    rn.url,
    rn.published_at,
    rn.available_at,
    rn.summary,
    rn.discovered_at,
    rn.fetched_at,
    rn.body_status,
    rn.language,
    rn.content_hash
FROM agent_news_symbol ans
JOIN agent_raw_news rn ON ans.raw_news_id = rn.id
WHERE ans.raw_news_id NOT IN (
    SELECT DISTINCT raw_news_id FROM agent_signal
) AND rn.content IS NOT NULL AND rn.content != '' AND length(rn.content) >= 20
ORDER BY ans.raw_news_id
"""

_GAP_FILL_QUERY = """
SELECT
    ans.raw_news_id, ans.vt_symbol, ans.symbol, ans.exchange,
    ans.relation_hint, ans.mapping_method, ans.mapping_confidence,
    ans.keywords_matched_json,
    rn.id AS rn_id, rn.title, rn.content, rn.source, rn.source_category,
    rn.source_item_id, rn.url, rn.published_at, rn.available_at,
    rn.summary, rn.discovered_at, rn.fetched_at, rn.body_status,
    rn.language, rn.content_hash
FROM agent_news_symbol ans
JOIN agent_raw_news rn ON ans.raw_news_id = rn.id
WHERE ans.raw_news_id IN (
    SELECT DISTINCT s.raw_news_id FROM agent_signal s
    JOIN agent_llm_run r ON s.llm_run_id = r.id WHERE r.provider = 'deepseek'
) AND ans.raw_news_id NOT IN (
    SELECT DISTINCT s.raw_news_id FROM agent_signal s
    JOIN agent_llm_run r ON s.llm_run_id = r.id WHERE r.provider = :target_provider
)
ORDER BY ans.raw_news_id
"""


def _parse_keywords(keywords_json: str | None) -> tuple[str, ...]:
    """Parse keywords_matched_json column into a tuple."""
    if not keywords_json:
        return ()
    try:
        parsed = json.loads(keywords_json)
    except (json.JSONDecodeError, TypeError):
        return ()
    if isinstance(parsed, list):
        return tuple(str(k) for k in parsed)
    return ()


def _datetime_or_none(value: str | None) -> datetime | None:  # noqa: F821
    """Convert ISO-ish string to datetime, or return None."""
    if value is None:
        return None
    from datetime import datetime as dt

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return dt.strptime(str(value).split("+")[0].split("Z")[0].strip(), fmt)
        except ValueError:
            continue
    return None


def fetch_unevaluated(
    db_path: str,
    max_items: int = 0,
    target_provider: str | None = None,
) -> list[dict]:
    """Return a list of dicts, one per unevaluated mapped news row.

    If target_provider is set, find items with DeepSeek signals but NOT
    target_provider signals (gap-fill mode). Otherwise, find items with no
    signals at all.
    """
    import sqlite3

    conn = sqlite3.connect(str(Path(db_path).expanduser()))
    conn.row_factory = sqlite3.Row
    if target_provider:
        cursor = conn.execute(_GAP_FILL_QUERY, {"target_provider": target_provider})
    else:
        cursor = conn.execute(_UNEVALUATED_QUERY)
    rows = list(cursor)
    conn.close()

    if max_items > 0:
        rows = rows[:max_items]

    results: list[dict] = []
    for row in rows:
        r = dict(row)
        r["published_at"] = _datetime_or_none(r.get("published_at"))
        r["available_at"] = _datetime_or_none(r.get("available_at"))
        r["discovered_at"] = _datetime_or_none(r.get("discovered_at"))
        r["fetched_at"] = _datetime_or_none(r.get("fetched_at"))
        results.append(r)
    return results


def build_evaluator(provider: str, base_url: str, model: str) -> DeepSeekNewsEvaluator:
    """Create a DeepSeekNewsEvaluator for the given provider."""
    if provider == "deepseek":
        evaluator = DeepSeekNewsEvaluator(provider="deepseek")
        return evaluator
    elif provider == "llama_cpp":
        evaluator = DeepSeekNewsEvaluator.for_llama_cpp(
            base_url=base_url,
            model=model,
        )
        return evaluator
    else:
        raise ValueError(f"Unknown provider: {provider}")


def make_mapped_news(row: dict) -> MappedNews:
    """Build a MappedNews from a DB row dict."""
    available_at = row["published_at"]
    if available_at is None:
        available_at = row["available_at"]
    if available_at is None:
        from datetime import datetime

        available_at = datetime.now()

    return MappedNews(
        raw_news_id=row["raw_news_id"],
        vt_symbol=row["vt_symbol"],
        symbol=row["symbol"],
        exchange=row["exchange"],
        relation_hint=RelationType(row["relation_hint"]),
        mapping_method=row["mapping_method"] or "",
        mapping_confidence=float(row["mapping_confidence"] or 0.0),
        keywords_matched=_parse_keywords(row.get("keywords_matched_json")),
        available_at=available_at,
    )


def make_raw_news_item(row: dict) -> RawNewsItem:
    """Build a RawNewsItem from a DB row dict."""
    source = Source(row["source"]) if row.get("source") else Source.CNINFO
    source_category = (
        SourceCategory(row["source_category"])
        if row.get("source_category")
        else SourceCategory.UNKNOWN
    )
    return RawNewsItem(
        source=source,
        source_category=source_category,
        title=row["title"] or "",
        content=row["content"] or "",
        content_hash=row["content_hash"] or "",
        source_item_id=row["source_item_id"] or "",
        url=row["url"] or "",
        summary=row["summary"] or "",
        published_at=row["published_at"],
        discovered_at=row["discovered_at"],
        fetched_at=row["fetched_at"],
        available_at=row["available_at"],
        body_status=row["body_status"] or "",
        language=row["language"] or "zh",
    )


def persist_result(
    repo: AgentNewsSqliteRepository,
    evaluator: DeepSeekNewsEvaluator,
    mapped: MappedNews,
    llm_run,
    llm_output,
    signal,
) -> int:
    """Save LLM run, output, retry attempts, and signal (if any). Returns signal count delta (0 or 1)."""
    run_db_id = repo.save_llm_run(llm_run)
    llm_output.llm_run_id = run_db_id
    repo.save_llm_output(llm_output)

    # Save any retry attempts (failed JSON repair attempts)
    attempts = list(evaluator.attempt_records)
    if len(attempts) > 1:
        for prev_run, prev_output in attempts[:-1]:
            prev_run.input_hash = f"{prev_run.input_hash}-retry-{prev_run.run_id}"
            prev_db_id = repo.save_llm_run(prev_run)
            prev_output.llm_run_id = prev_db_id
            repo.save_llm_output(prev_output)

    if signal is not None:
        signal.raw_news_id = mapped.raw_news_id
        signal.llm_run_id = run_db_id
        repo.save_signal(signal)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate unevaluated mapped news with LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to agent_news_*.db (required)",
    )
    parser.add_argument(
        "--provider",
        default="deepseek",
        choices=["deepseek", "llama_cpp"],
        help="LLM backend: deepseek or llama_cpp (default: deepseek)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="Max items to evaluate (0 = no limit)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel LLM workers (default: 1)",
    )
    parser.add_argument(
        "--llm-base-url",
        default="http://127.0.0.1:8080/v1",
        help="Base URL for llama_cpp (default: http://127.0.0.1:8080/v1)",
    )
    parser.add_argument(
        "--llm-model",
        default="Qwen3.6-35B-A3B-Q4_K_M.gguf",
        help="Model name for llama_cpp",
    )
    parser.add_argument(
        "--target-provider",
        default=None,
        help="Gap-fill mode: evaluate items with DeepSeek but NOT this provider (e.g. 'llama_cpp')",
    )

    args = parser.parse_args(argv)

    # ── Resolve DB path ─────────────────────────────────────────────────
    db_path = str(Path(args.db_path).expanduser())
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        return 1

    # ── Fetch unevaluated items ─────────────────────────────────────────
    print(f"[fetch] Scanning {db_path} for unevaluated mapped news...", file=sys.stderr)
    rows = fetch_unevaluated(db_path, max_items=args.max_items, target_provider=args.target_provider)
    total = len(rows)
    print(f"[fetch] Found {total} unevaluated items", file=sys.stderr)
    if total == 0:
        print("No unevaluated items. Nothing to do.")
        return 0

    # ── Build evaluator ─────────────────────────────────────────────────
    if args.provider == "deepseek":
        import os

        if not os.environ.get("DEEPSEEK_API_KEY"):
            print(
                "Error: DEEPSEEK_API_KEY environment variable not set.",
                file=sys.stderr,
            )
            return 1

    print(f"[eval] Creating evaluator: provider={args.provider}", file=sys.stderr)
    evaluator = build_evaluator(
        provider=args.provider,
        base_url=args.llm_base_url,
        model=args.llm_model,
    )

    # ── Init repository ─────────────────────────────────────────────────
    repo = AgentNewsSqliteRepository(db_path=db_path)

    # ── Evaluation loop ─────────────────────────────────────────────────
    evaluated = 0
    signal_count = 0
    errors: list[str] = []

    items = [
        (make_mapped_news(row), make_raw_news_item(row))
        for row in rows
    ]

    if args.workers == 1:
        # Sequential
        for mapped, news_item in tqdm(items, desc="LLM evaluating", unit="item"):
            try:
                llm_run, llm_output, signal = evaluator.evaluate(mapped, news_item)
                signal_count += persist_result(
                    repo, evaluator, mapped, llm_run, llm_output, signal,
                )
                evaluated += 1
            except Exception as exc:
                errors.append(f"raw_news_id={mapped.raw_news_id}: {exc}")
    else:
        # Multi-worker: create one evaluator per thread to avoid
        # sharing attempt_records across concurrent calls
        import concurrent.futures
        import threading

        thread_local = threading.local()

        def _get_evaluator():
            if not hasattr(thread_local, "evaluator"):
                thread_local.evaluator = build_evaluator(
                    provider=args.provider,
                    base_url=args.llm_base_url,
                    model=args.llm_model,
                )
            return thread_local.evaluator

        def _evaluate_one(mapped, news_item):
            ev = _get_evaluator()
            return ev.evaluate(mapped, news_item), ev.attempt_records

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers,
        ) as executor:
            futures = {
                executor.submit(_evaluate_one, m, ni): (m, ni)
                for m, ni in items
            }
            for future in tqdm(
                concurrent.futures.as_completed(futures),
                total=len(futures),
                desc="LLM evaluating",
                unit="item",
            ):
                mapped, news_item = futures[future]
                try:
                    (llm_run, llm_output, signal), attempts = future.result()
                    # Merge attempts into a temporary evaluator for persist
                    from dataclasses import dataclass, field as dc_field

                    @dataclass
                    class _FakeEvaluator:
                        attempt_records: list = dc_field(default_factory=list)

                    fake_eval = _FakeEvaluator(attempt_records=list(attempts))
                    signal_count += persist_result(
                        repo, fake_eval, mapped, llm_run, llm_output, signal,
                    )
                    evaluated += 1
                except Exception as exc:
                    errors.append(f"raw_news_id={mapped.raw_news_id}: {exc}")

    # ── Print summary ───────────────────────────────────────────────────
    print(file=sys.stderr)
    print("─── Evaluation Summary ───", file=sys.stderr)
    print(f"  Total fetched  : {total}", file=sys.stderr)
    print(f"  Evaluated      : {evaluated}", file=sys.stderr)
    print(f"  Signals        : {signal_count}", file=sys.stderr)
    print(f"  Errors         : {len(errors)}", file=sys.stderr)
    if errors:
        for e in errors[:10]:
            print(f"    - {e}", file=sys.stderr)
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more", file=sys.stderr)

    # JSON summary to stdout for scripting
    summary = {
        "total": total,
        "evaluated": evaluated,
        "signals": signal_count,
        "errors": len(errors),
    }
    print(json.dumps(summary, ensure_ascii=False))

    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
