"""Pipeline contract tests — verify schema, field names, and data flow integrity."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

from myQuant.news_ingestion.calendar import available_at_to_trading_date, is_trading_day
from myQuant.news_ingestion.contracts import AgentSignal, StockProfile
from myQuant.news_ingestion.scoring.config import CONFIG_VERSION
from myQuant.news_ingestion.scoring.daily_aggregator import run_v0_22_pipeline, run_v0_2_pipeline
from myQuant.news_ingestion.storage.sqlite import AgentDailySignalModel, AgentNewsSqliteRepository, AgentSignalModel


# ── Schema Tests ──


def test_agent_signal_has_signal_version():
    cols = {f.name for f in AgentSignalModel._meta.sorted_fields}
    assert "signal_version" in cols


def test_agent_daily_signal_table_exists():
    assert hasattr(AgentDailySignalModel, "trading_date")
    assert hasattr(AgentDailySignalModel, "vt_symbol")
    assert hasattr(AgentDailySignalModel, "signal_version")
    assert hasattr(AgentDailySignalModel, "daily_agent_signal")


def test_agent_daily_signal_unique_constraint():
    indexes = AgentDailySignalModel._meta.indexes
    found = False
    for idx in indexes:
        if isinstance(idx, tuple) and len(idx) == 2:
            cols, unique = idx
            if unique and "trading_date" in cols and "vt_symbol" in cols and "signal_version" in cols:
                found = True
    assert found, "Unique constraint (trading_date, vt_symbol, signal_version) not found"


def test_make_signal_db_schema_12_columns():
    from backtests.run_matrix import make_signal_db
    signals = [{"trading_date": "2020-01-02", "daily_agent_signal": 0.5, "daily_direction": "positive"}]
    db_path = make_signal_db(signals, "v0.22")
    conn = sqlite3.connect(db_path)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(daily_agent_signal)").fetchall()]
        assert len(cols) == 12, f"Expected 12 columns, got {len(cols)}: {cols}"
        expected = [
            "entry_date", "daily_agent_signal", "daily_direction",
            "signal_version", "agent_label", "raw_daily_signal",
            "news_count", "event_count", "model_count",
            "mixed_intensity", "risk_penalty", "created_at",
        ]
        assert cols == expected
    finally:
        conn.close()
        Path(db_path).unlink(missing_ok=True)


# ── Trading Date Tests ──


def test_evaluator_uses_calendar_not_raw_date():
    src = Path(__file__).resolve().parent.parent.parent.parent / "myQuant" / "news_ingestion" / "llm" / "evaluator.py"
    content = src.read_text()
    assert "available_at_to_trading_date" in content
    assert "available_at.date().isoformat()" not in content


def test_weekend_news_maps_to_monday():
    saturday = datetime(2026, 5, 23, 10, 0)
    assert available_at_to_trading_date(saturday) == "2026-05-25"


def test_after_close_maps_to_next_day():
    friday_close = datetime(2026, 5, 22, 15, 30)
    result = available_at_to_trading_date(friday_close)
    assert result == "2026-05-25"


def test_intraday_maps_to_same_day():
    friday_intraday = datetime(2026, 5, 22, 10, 30)
    assert available_at_to_trading_date(friday_intraday) == "2026-05-22"


def test_holiday_maps_to_next_trading_day():
    new_year = datetime(2026, 1, 1, 10, 0)
    result = available_at_to_trading_date(new_year)
    d = date.fromisoformat(result)
    assert is_trading_day(d)


# ── Daily Signal Tests ──


def _make_mock_rows(n: int = 3) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append({
            "raw_news_id": i + 1,
            "llm_run_id": 1,
            "vt_symbol": "600309.SSE",
            "trading_date": "2020-01-02",
            "event": f"event_{i}",
            "impact_direction": "positive",
            "impact_strength": 0.7,
            "confidence": 0.6,
            "relation_type": "direct_company",
            "time_horizon": "short",
        })
    return rows


DAILY_SIGNAL_FIELDS = [
    "trading_date", "vt_symbol", "signal_version", "daily_agent_signal",
    "daily_direction", "agent_label", "raw_daily_signal", "news_count",
    "event_count", "model_count", "mixed_intensity", "risk_penalty", "created_at",
]


def test_v022_pipeline_output_fields():
    results = run_v0_22_pipeline(_make_mock_rows())
    assert len(results) > 0
    for field in DAILY_SIGNAL_FIELDS:
        assert field in results[0], f"Missing field: {field}"


def test_v02_pipeline_output_fields():
    results = run_v0_2_pipeline(_make_mock_rows())
    assert len(results) > 0
    for field in DAILY_SIGNAL_FIELDS:
        assert field in results[0], f"Missing field: {field}"


def test_v022_signal_clamped_to_unit_range():
    big_rows = []
    for i in range(20):
        big_rows.append({
            "raw_news_id": i + 1,
            "llm_run_id": 1,
            "vt_symbol": "600309.SSE",
            "trading_date": "2020-01-02",
            "event": f"event_{i}",
            "impact_direction": "positive",
            "impact_strength": 1.0,
            "confidence": 1.0,
            "relation_type": "direct_company",
            "time_horizon": "short",
        })
    results = run_v0_22_pipeline(big_rows)
    for r in results:
        assert -1.0 <= r["daily_agent_signal"] <= 1.0


def test_v02_signal_clamped_to_unit_range():
    big_rows = []
    for i in range(20):
        big_rows.append({
            "raw_news_id": i + 1,
            "llm_run_id": 1,
            "vt_symbol": "600309.SSE",
            "trading_date": "2020-01-02",
            "event": f"event_{i}",
            "impact_direction": "positive",
            "impact_strength": 1.0,
            "confidence": 1.0,
            "relation_type": "direct_company",
            "time_horizon": "short",
        })
    results = run_v0_2_pipeline(big_rows)
    for r in results:
        assert -1.0 <= r["daily_agent_signal"] <= 1.0


def test_daily_direction_matches_signal_sign():
    rows = _make_mock_rows()
    results = run_v0_22_pipeline(rows)
    for r in results:
        sig = r["daily_agent_signal"]
        direction = r["daily_direction"]
        if sig >= 0.25:
            assert direction == "positive"
        elif sig <= -0.25:
            assert direction == "negative"
        else:
            assert direction == "neutral"


def test_v022_signal_version_is_config_version():
    results = run_v0_22_pipeline(_make_mock_rows())
    assert results[0]["signal_version"] == CONFIG_VERSION


def test_v02_signal_version_is_v02():
    results = run_v0_2_pipeline(_make_mock_rows())
    assert results[0]["signal_version"] == "v0.2"


def test_created_at_exists_and_iso_format():
    results = run_v0_22_pipeline(_make_mock_rows())
    assert "created_at" in results[0]
    datetime.fromisoformat(results[0]["created_at"])


def test_defaults_for_missing_fields():
    rows = [{"raw_news_id": 1, "llm_run_id": 1, "vt_symbol": "600309.SSE",
             "trading_date": "2020-01-02", "event": "test",
             "impact_direction": "positive", "impact_strength": 0.5,
             "confidence": 0.5, "relation_type": "direct_company",
             "time_horizon": "short"}]
    results = run_v0_22_pipeline(rows)
    assert results[0]["news_count"] == 0
    assert results[0]["model_count"] == 0


# ── Persist Idempotency Tests ──


def test_persist_idempotent_no_duplicates(tmp_path):
    db_path = tmp_path / "test.db"
    repo = AgentNewsSqliteRepository(db_path=db_path)
    signal = {
        "trading_date": "2020-01-02",
        "vt_symbol": "600309.SSE",
        "signal_version": "v0.22",
        "daily_agent_signal": 0.5,
        "daily_direction": "positive",
        "agent_label": "v0.22",
        "raw_daily_signal": 0.6,
        "news_count": 0,
        "event_count": 3,
        "model_count": 0,
        "mixed_intensity": 0.0,
        "risk_penalty": 1.0,
    }
    repo.save_daily_signal(signal)
    repo.save_daily_signal(signal)
    count = AgentDailySignalModel.select().count()
    assert count == 1


def test_persist_different_versions_coexist(tmp_path):
    db_path = tmp_path / "test.db"
    repo = AgentNewsSqliteRepository(db_path=db_path)
    base = {
        "trading_date": "2020-01-02",
        "vt_symbol": "600309.SSE",
        "daily_agent_signal": 0.5,
        "daily_direction": "positive",
        "agent_label": "v0.22",
        "raw_daily_signal": 0.6,
        "news_count": 0,
        "event_count": 3,
        "model_count": 0,
        "mixed_intensity": 0.0,
        "risk_penalty": 1.0,
    }
    repo.save_daily_signal({**base, "signal_version": "v0.2"})
    repo.save_daily_signal({**base, "signal_version": "v0.22"})
    count = AgentDailySignalModel.select().count()
    assert count == 2


# ── Backtest Compatibility Tests ──


def test_old_json_compatible_with_make_signal_db():
    from backtests.run_matrix import make_signal_db
    old_json = [{"trading_date": "2020-01-02", "daily_agent_signal": 0.5,
                 "daily_direction": "positive", "event_count": 3,
                 "raw_daily": 0.6, "mixed_intensity": 0.0,
                 "risk_penalty": 1.0, "version": "v0.22"}]
    db_path = make_signal_db(old_json, "v0.22")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT * FROM daily_agent_signal").fetchone()
        assert row is not None
        assert row[0] == "2020-01-02"
        assert row[1] == 0.5
    finally:
        conn.close()
        Path(db_path).unlink(missing_ok=True)


def test_new_json_fields_complete_in_signal_db():
    from backtests.run_matrix import make_signal_db
    new_json = [{"trading_date": "2020-01-02", "vt_symbol": "600309.SSE",
                 "signal_version": "v0.22", "daily_agent_signal": 0.5,
                 "daily_direction": "positive", "agent_label": "v0.22",
                 "raw_daily_signal": 0.6, "news_count": 0, "event_count": 3,
                 "model_count": 0, "mixed_intensity": 0.0, "risk_penalty": 1.0,
                 "created_at": "2026-05-27T10:00:00"}]
    db_path = make_signal_db(new_json, "v0.22")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT signal_version, agent_label, event_count FROM daily_agent_signal").fetchone()
        assert row[0] == "v0.22"
        assert row[1] == "v0.22"
        assert row[2] == 3
    finally:
        conn.close()
        Path(db_path).unlink(missing_ok=True)
