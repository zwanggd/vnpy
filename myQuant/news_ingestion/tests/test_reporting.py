from __future__ import annotations

from myQuant.news_ingestion.pipeline import PipelineResult
from myQuant.news_ingestion.reporting import generate_report

_SEED_SYMBOLS = [
    "000333.SZSE","002475.SZSE","002594.SZSE","300750.SZSE",
    "600036.SSE","600276.SSE","600309.SSE","600519.SSE",
    "601318.SSE","601899.SSE",
]

def _fake_result(**kw):
    return PipelineResult(run_id="test123", raw_count=150, mapped_count=42, signal_count=8, errors=kw.get("errors", []))

def _base_config(**kw):
    return {
        "start": "2024-01-01", "end": "2024-01-31",
        "symbols": _SEED_SYMBOLS,
        "sources": ["cninfo", "cls_telegraph", "eastmoney"],
        "recall_strength": "medium",
        "source_coverage": {
            "cninfo": {"items": 80, "errors": 1, "coverage_status": "partial"},
            "cls_telegraph": {"items": 50, "errors": 0},
            "eastmoney": {"items": 20, "errors": 2, "coverage_status": "partial"},
        },
        "llm_run_count": 42, "invalid_signals": 3,
        "signals": [
            {"vt_symbol": "300750.SZSE", "event": "New battery line", "impact_direction": "positive", "impact_strength": 0.72, "confidence": 0.68},
            {"vt_symbol": "600519.SSE", "event": "Price increase", "impact_direction": "positive", "impact_strength": 0.85, "confidence": 0.90},
        ],
        **kw,
    }

class TestReporting:
    def test_report_contains_required_sections(self):
        report = generate_report(_fake_result(), _base_config())
        assert "## Run Metadata" in report
        assert "## Source Coverage" in report
        assert "## Counts" in report
        assert "## Top Sample Signals" in report
        assert "## Failures / Gaps" in report
        assert "## Short Conclusion" in report

    def test_report_does_not_include_api_key(self):
        config = _base_config()
        config["command"] = "export DEEPSEEK_API_KEY=sk-abc123def456ghijklmnopqrstuv"
        report = generate_report(_fake_result(), config)
        assert "sk-abc123def456ghijklmnopqrstuv" not in report
        assert "sk-" not in report or "[REDACTED]" in report

    def test_report_contains_10_symbols(self):
        report = generate_report(_fake_result(), _base_config())
        for sym in _SEED_SYMBOLS:
            assert sym in report

    def test_report_handles_empty_errors(self):
        report = generate_report(_fake_result(errors=[]), _base_config())
        assert "No errors" in report or "_No errors_" in report

    def test_report_uses_config_command(self):
        config = _base_config()
        config["command"] = "python -m myQuant.news_ingestion.cli --start 2024-01-01"
        report = generate_report(_fake_result(), config)
        assert "python -m myQuant.news_ingestion.cli --start 2024-01-01" in report

    def test_report_by_source_month(self):
        config = _base_config()
        config["source_coverage_by_month"] = {
            "cninfo": {
                "2024-01": {"items": 50, "errors": 0},
                "2024-02": {"items": 30, "errors": 1},
            },
            "cls_telegraph": {
                "2024-01": {"items": 25, "errors": 0},
                "2024-02": {"items": 25, "errors": 0},
            },
        }
        report = generate_report(_fake_result(), config)
        assert "50" in report  # cninfo Jan items
        assert "30" in report  # cninfo Feb items
        assert "2024-01" in report  # month column
        assert "2024-02" in report  # month column
