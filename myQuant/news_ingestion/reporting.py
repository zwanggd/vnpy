"""Markdown report generator for agent news backfill runs."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from myQuant.news_ingestion.pipeline import PipelineResult

_API_KEY_RE = re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE)

def _redact(value: str) -> str:
    return _API_KEY_RE.sub("[REDACTED]", value)


def generate_report(result: PipelineResult, config: dict) -> str:
    today = date.today().isoformat()
    lines = [
        f"# Agent News v0.1 Backfill Report \u2014 {today}", "",
        "## Run Metadata", "",
        f"- **Run ID**: `{result.run_id}`",
        f"- **Command**: `{config.get('command', 'conda run -n vnpy43 (vnpy43 env)')}`",
        f"- **Date Range**: {config.get('start','?')} to {config.get('end','?')}",
        f"- **Sources**: {', '.join(config.get('sources',[]))}",
        f"- **Recall Strength**: {config.get('recall_strength','?')}", "",
        "## Stock List", "",
    ]
    for sym in config.get("symbols", []):
        lines.append(f"- `{sym}`")
    lines.append("")

    lines.append("## Source Coverage")
    lines.append("")
    coverage = config.get("source_coverage", {})
    by_month = config.get("source_coverage_by_month", {})
    if coverage:
        lines.append("| Source | Items Fetched | Errors |")
        lines.append("|--------|--------------|--------|")
        for src, info in coverage.items():
            items = info.get("items", 0)
            errs = info.get("errors", 0)
            coverage_note = " (partial)" if info.get("coverage_status") == "partial" else ""
            lines.append(f"| {src}{coverage_note} | {items} | {errs} |")
            if src in by_month:
                lines.append("| | Month | Items | Errors |")
                lines.append("| |-------|-------|--------|")
                for month, data in sorted(by_month[src].items()):
                    m_items = data.get("items", 0)
                    m_errs = data.get("errors", 0)
                    lines.append(f"| | {month} | {m_items} | {m_errs} |")
    else:
        lines.append("_No source coverage data available._")
    lines.append("")

    lines.append("## Counts")
    lines.append("")
    lines.append(f"- **Raw Items**: {result.raw_count}")
    lines.append(f"- **Filtered Candidates (after recall/dedupe)**: {result.mapped_count}")
    lines.append(f"- **LLM Runs**: {config.get('llm_run_count', 0)}")
    lines.append(f"- **Valid Signals**: {result.signal_count}")
    lines.append(f"- **Invalid Signals**: {config.get('invalid_signals', 0)}")
    lines.append("")

    lines.append("## Top Sample Signals")
    lines.append("")
    signals = config.get("signals", [])[:5]
    if signals:
        for s in signals:
            lines.append(f"- **{s.get('vt_symbol','?')}** | {s.get('event','?')} | {s.get('impact_direction','?')} | strength={s.get('impact_strength',0)} | confidence={s.get('confidence',0)}")
    else:
        lines.append("_No signals generated._")
    lines.append("")

    lines.append("## Failures / Gaps")
    lines.append("")
    if result.errors:
        for e in result.errors:
            lines.append(f"- {e}")
    else:
        lines.append("_No errors._")
    lines.append("")

    lines.append("## Short Conclusion")
    lines.append("")
    r = result
    lines.append(f"Backfill run `{r.run_id}` completed: {r.raw_count} raw items \u2192 {r.mapped_count} candidates \u2192 {r.signal_count} signals. {'Errors encountered; see Failures/Gaps above.' if r.errors else 'No errors.'}")

    output = "\n".join(lines)
    return _redact(output)
