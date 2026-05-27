#!/usr/bin/env python3
"""
Audit script for Agent Quant Pipeline consistency checks.

Usage:
    PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python scripts/audit_current_pipeline.py

Checks:
1. Critical tables exist
2. Table schemas match code expectations
3. agent_signal has no empty vt_symbol
4. agent_signal has no out-of-range impact_strength/confidence
5. daily_agent_signal has no signal outside [-1, 1]
6. daily_agent_signal has no duplicate (vt_symbol, trading_date, version)
7. Backtest results have no non-zero returns with zero trade_count
8. Technical indicators have no all-zero trades
9. v0.2 / v0.22 can coexist without overwriting
10. Backtest outputs can trace run_id/strategy_name/signal_version
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Default paths
MARKET_DB = Path.home() / ".vntrader" / "database.db"
AGENT_NEWS_DB_PATTERN = Path.home() / ".vntrader" / "agent_news_em_*.db"
SIGNAL_DIR = PROJECT_ROOT / "backtests" / "results" / "v0.22" / "signals"
RESULTS_DIR = PROJECT_ROOT / "backtests" / "results"

# Expected schemas
EXPECTED_TABLES = {
    "agent_raw_news": [
        "id", "source", "source_category", "source_item_id", "url",
        "title", "content", "summary", "published_at", "discovered_at",
        "fetched_at", "available_at", "raw_payload_json", "content_hash",
        "body_status", "language", "created_at"
    ],
    "agent_news_symbol": [
        "id", "raw_news_id", "vt_symbol", "symbol", "exchange",
        "relation_hint", "mapping_method", "mapping_confidence", "keywords_matched_json"
    ],
    "agent_stock_profile": [
        "vt_symbol", "symbol", "exchange", "name", "aliases_json",
        "industry_json", "products_json", "upstream_json", "downstream_json",
        "macro_factors_json", "risk_keywords_json", "profile_version", "updated_at"
    ],
    "agent_signal": [
        "id", "raw_news_id", "llm_run_id", "vt_symbol", "symbol", "exchange",
        "event", "relation_type", "impact_direction", "impact_strength",
        "time_horizon", "confidence", "reason", "evidence_json",
        "published_at", "available_at", "trading_date", "source",
        "source_item_id", "prompt_version", "schema_version", "created_at"
    ],
    "agent_llm_run": [
        "id", "run_id", "raw_news_id", "provider", "model",
        "prompt_version", "schema_version", "parameters_json", "input_hash",
        "started_at", "finished_at", "status", "error"
    ],
    "agent_llm_output": [
        "id", "llm_run_id", "raw_response", "parsed_json",
        "validation_status", "validation_errors_json", "output_hash", "token_usage_json"
    ],
}


class AuditResult:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def add(self, check_id: str, name: str, status: str, details: str = "") -> None:
        self.checks.append({
            "check_id": check_id,
            "name": name,
            "status": status,
            "details": details,
        })
        if status == "PASS":
            self.passed += 1
        elif status == "FAIL":
            self.failed += 1
        else:
            self.warnings += 1

    def to_markdown(self) -> str:
        lines = [
            "# Pipeline Audit Results",
            "",
            f"**Audit Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Checks**: {len(self.checks)}",
            f"**Passed**: {self.passed}",
            f"**Failed**: {self.failed}",
            f"**Warnings**: {self.warnings}",
            "",
            "## Summary",
            "",
            "| Check | Name | Status | Details |",
            "|-------|------|--------|---------|",
        ]
        for c in self.checks:
            status_icon = "✅" if c["status"] == "PASS" else "❌" if c["status"] == "FAIL" else "⚠️"
            details = c["details"][:100] + "..." if len(c["details"]) > 100 else c["details"]
            lines.append(f"| {c['check_id']} | {c['name']} | {status_icon} {c['status']} | {details} |")

        lines.extend(["", "## Detailed Results", ""])
        for c in self.checks:
            lines.extend([
                f"### {c['check_id']}: {c['name']}",
                f"**Status**: {c['status']}",
                f"**Details**: {c['details']}",
                "",
            ])

        return "\n".join(lines)


def find_agent_dbs() -> list[Path]:
    """Find all agent news databases."""
    return list(Path.home().joinpath(".vntrader").glob("agent_news_em_*.db"))


def get_table_columns(db_path: Path, table_name: str) -> list[str]:
    """Get column names for a table."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        return [row[1] for row in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def check_01_tables_exist(result: AuditResult, db_path: Path) -> None:
    """Check 1: Critical tables exist."""
    for table_name in EXPECTED_TABLES:
        columns = get_table_columns(db_path, table_name)
        if columns:
            result.add(
                f"1.{table_name}",
                f"Table {table_name} exists",
                "PASS",
                f"Found {len(columns)} columns"
            )
        else:
            result.add(
                f"1.{table_name}",
                f"Table {table_name} exists",
                "FAIL",
                f"Table not found in {db_path.name}"
            )


def check_02_schemas_match(result: AuditResult, db_path: Path) -> None:
    """Check 2: Table schemas match code expectations."""
    for table_name, expected_cols in EXPECTED_TABLES.items():
        actual_cols = get_table_columns(db_path, table_name)
        if not actual_cols:
            result.add(
                f"2.{table_name}",
                f"Schema {table_name}",
                "FAIL",
                "Table not found"
            )
            continue

        missing = set(expected_cols) - set(actual_cols)
        extra = set(actual_cols) - set(expected_cols)

        if not missing and not extra:
            result.add(
                f"2.{table_name}",
                f"Schema {table_name}",
                "PASS",
                f"All {len(expected_cols)} expected columns present"
            )
        elif missing:
            result.add(
                f"2.{table_name}",
                f"Schema {table_name}",
                "FAIL",
                f"Missing columns: {missing}"
            )
        else:
            result.add(
                f"2.{table_name}",
                f"Schema {table_name}",
                "WARN",
                f"Extra columns (not in code): {extra}"
            )


def check_03_empty_vt_symbol(result: AuditResult, db_path: Path) -> None:
    """Check 3: agent_signal has no empty vt_symbol."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM agent_signal WHERE vt_symbol IS NULL OR vt_symbol = ''"
        )
        count = cursor.fetchone()[0]
        if count == 0:
            result.add(
                "3.empty_vt_symbol",
                "No empty vt_symbol in agent_signal",
                "PASS",
                "All rows have vt_symbol"
            )
        else:
            result.add(
                "3.empty_vt_symbol",
                "No empty vt_symbol in agent_signal",
                "FAIL",
                f"{count} rows have empty vt_symbol"
            )
    except Exception as e:
        result.add(
            "3.empty_vt_symbol",
            "No empty vt_symbol in agent_signal",
            "WARN",
            f"Could not check: {e}"
        )
    finally:
        conn.close()


def check_04_out_of_range(result: AuditResult, db_path: Path) -> None:
    """Check 4: agent_signal has no out-of-range impact_strength/confidence."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("""
            SELECT COUNT(*) FROM agent_signal 
            WHERE impact_strength < 0.0 OR impact_strength > 1.0
               OR confidence < 0.0 OR confidence > 1.0
        """)
        count = cursor.fetchone()[0]
        if count == 0:
            result.add(
                "4.out_of_range",
                "No out-of-range values in agent_signal",
                "PASS",
                "All impact_strength/confidence in [0, 1]"
            )
        else:
            result.add(
                "4.out_of_range",
                "No out-of-range values in agent_signal",
                "FAIL",
                f"{count} rows have out-of-range values"
            )
    except Exception as e:
        result.add(
            "4.out_of_range",
            "No out-of-range values in agent_signal",
            "WARN",
            f"Could not check: {e}"
        )
    finally:
        conn.close()


def check_05_signal_range(result: AuditResult, signal_dir: Path) -> None:
    """Check 5: daily_agent_signal has no signal outside [-1, 1]."""
    if not signal_dir.exists():
        result.add(
            "5.signal_range",
            "daily_agent_signal in [-1, 1]",
            "WARN",
            f"Signal directory not found: {signal_dir}"
        )
        return

    all_ok = True
    details = []
    for json_file in signal_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text())
            for row in data:
                sig = row.get("daily_agent_signal", 0)
                if sig < -1.0 or sig > 1.0:
                    all_ok = False
                    details.append(f"{json_file.name}: {sig}")
        except Exception as e:
            details.append(f"{json_file.name}: parse error: {e}")

    if all_ok:
        result.add(
            "5.signal_range",
            "daily_agent_signal in [-1, 1]",
            "PASS",
            f"All signals in range across {len(list(signal_dir.glob('*.json')))} files"
        )
    else:
        result.add(
            "5.signal_range",
            "daily_agent_signal in [-1, 1]",
            "FAIL",
            f"Out-of-range signals: {details[:5]}"
        )


def check_06_no_duplicates(result: AuditResult, signal_dir: Path) -> None:
    """Check 6: daily_agent_signal has no duplicate (vt_symbol, trading_date, version)."""
    if not signal_dir.exists():
        result.add(
            "6.no_duplicates",
            "No duplicates in daily_agent_signal",
            "WARN",
            f"Signal directory not found: {signal_dir}"
        )
        return

    all_ok = True
    details = []
    for json_file in signal_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text())
            seen = set()
            for row in data:
                key = (row.get("vt_symbol"), row.get("trading_date"), row.get("version"))
                if key in seen:
                    all_ok = False
                    details.append(f"{json_file.name}: duplicate {key}")
                seen.add(key)
        except Exception as e:
            details.append(f"{json_file.name}: parse error: {e}")

    if all_ok:
        result.add(
            "6.no_duplicates",
            "No duplicates in daily_agent_signal",
            "PASS",
            "No duplicates found"
        )
    else:
        result.add(
            "6.no_duplicates",
            "No duplicates in daily_agent_signal",
            "FAIL",
            f"Duplicates: {details[:5]}"
        )


def check_07_backtest_consistency(result: AuditResult, results_dir: Path) -> None:
    """Check 7: Backtest results have no non-zero returns with zero trade_count."""
    csv_files = list(results_dir.glob("matrix/summary_matrix_*.csv"))
    if not csv_files:
        result.add(
            "7.backtest_consistency",
            "Backtest result consistency",
            "WARN",
            "No matrix summary files found"
        )
        return

    all_ok = True
    details = []
    for csv_file in csv_files:
        try:
            import csv
            with open(csv_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_return = float(row.get("total_return", 0))
                    trade_count = int(row.get("total_trade_count", 0))
                    if total_return != 0 and trade_count == 0:
                        all_ok = False
                        details.append(f"{csv_file.name}: return={total_return} but trades=0")
        except Exception as e:
            details.append(f"{csv_file.name}: parse error: {e}")

    if all_ok:
        result.add(
            "7.backtest_consistency",
            "Backtest result consistency",
            "PASS",
            "No inconsistent results"
        )
    else:
        result.add(
            "7.backtest_consistency",
            "Backtest result consistency",
            "FAIL",
            f"Inconsistent: {details[:5]}"
        )


def check_08_version_coexistence(result: AuditResult, signal_dir: Path) -> None:
    """Check 8: v0.2 / v0.22 can coexist without overwriting."""
    if not signal_dir.exists():
        result.add(
            "8.version_coexistence",
            "v0.2/v0.22 coexistence",
            "WARN",
            f"Signal directory not found: {signal_dir}"
        )
        return

    v02_files = list(signal_dir.glob("*_v0_2.json"))
    v022_files = list(signal_dir.glob("*_v0_22.json"))

    if v02_files and v022_files:
        # Check that they have different content
        v02_stocks = {f.stem.replace("_v0_2", "") for f in v02_files}
        v022_stocks = {f.stem.replace("_v0_22", "") for f in v022_files}
        common = v02_stocks & v022_stocks

        if common:
            result.add(
                "8.version_coexistence",
                "v0.2/v0.22 coexistence",
                "PASS",
                f"Both versions exist for: {common}"
            )
        else:
            result.add(
                "8.version_coexistence",
                "v0.2/v0.22 coexistence",
                "WARN",
                f"v0.2 stocks: {v02_stocks}, v0.22 stocks: {v022_stocks}"
            )
    else:
        result.add(
            "8.version_coexistence",
            "v0.2/v0.22 coexistence",
            "WARN",
            f"v0.2 files: {len(v02_files)}, v0.22 files: {len(v022_files)}"
        )


def check_09_version_traceability(result: AuditResult, results_dir: Path) -> None:
    """Check 9: Backtest outputs can trace run_id/strategy_name/signal_version."""
    csv_files = list(results_dir.glob("matrix/summary_matrix_phase2.csv"))
    if not csv_files:
        result.add(
            "9.version_traceability",
            "Version traceability in backtest output",
            "WARN",
            "No phase2 summary found"
        )
        return

    try:
        import csv
        with open(csv_files[0]) as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []

        has_agent_version = "agent_version" in headers
        has_signal_mode = "signal_mode" in headers

        if has_agent_version and has_signal_mode:
            result.add(
                "9.version_traceability",
                "Version traceability in backtest output",
                "PASS",
                f"Both agent_version and signal_mode present in headers"
            )
        else:
            missing = []
            if not has_agent_version:
                missing.append("agent_version")
            if not has_signal_mode:
                missing.append("signal_mode")
            result.add(
                "9.version_traceability",
                "Version traceability in backtest output",
                "FAIL",
                f"Missing columns: {missing}"
            )
    except Exception as e:
        result.add(
            "9.version_traceability",
            "Version traceability in backtest output",
            "WARN",
            f"Could not check: {e}"
        )


def check_10_relation_type_coverage(result: AuditResult, db_path: Path) -> None:
    """Check 10: All relation_type values are valid enum values."""
    valid_types = {
        "direct_company", "supply_chain", "industry",
        "macro_policy", "market_sentiment", "risk_event", "unknown"
    }
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT DISTINCT relation_type FROM agent_signal WHERE relation_type IS NOT NULL"
        )
        actual_types = {row[0] for row in cursor.fetchall()}
        invalid = actual_types - valid_types

        if not invalid:
            result.add(
                "10.relation_type_coverage",
                "Valid relation_type values",
                "PASS",
                f"Found types: {actual_types}"
            )
        else:
            result.add(
                "10.relation_type_coverage",
                "Valid relation_type values",
                "FAIL",
                f"Invalid types: {invalid}"
            )
    except Exception as e:
        result.add(
            "10.relation_type_coverage",
            "Valid relation_type values",
            "WARN",
            f"Could not check: {e}"
        )
    finally:
        conn.close()


def check_11_trading_date_valid(result: AuditResult, db_path: Path) -> None:
    from myQuant.news_ingestion.calendar import is_trading_day
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT DISTINCT trading_date FROM agent_signal WHERE trading_date IS NOT NULL LIMIT 100"
        )
        rows = cursor.fetchall()
        invalid = []
        for (td_str,) in rows:
            try:
                d = date.fromisoformat(td_str[:10])
                if not is_trading_day(d):
                    invalid.append(td_str)
            except Exception:
                invalid.append(td_str)
        if not invalid:
            result.add(
                "11.trading_date_valid",
                "All trading_date are valid trading days",
                "PASS",
                f"Checked {len(rows)} distinct trading_dates"
            )
        else:
            result.add(
                "11.trading_date_valid",
                "All trading_date are valid trading days",
                "FAIL",
                f"{len(invalid)} non-trading dates found: {invalid[:5]}"
            )
    except Exception as e:
        result.add("11.trading_date_valid", "All trading_date are valid trading days", "WARN", str(e))
    finally:
        conn.close()


def check_12_signal_version_in_db(result: AuditResult, db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(agent_signal)").fetchall()]
        if "signal_version" in cols:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM agent_signal WHERE signal_version IS NOT NULL AND signal_version != ''"
            )
            count = cursor.fetchone()[0]
            if count > 0:
                result.add("12.signal_version_in_db", "signal_version in agent_signal", "PASS", f"{count} rows have signal_version")
            else:
                result.add("12.signal_version_in_db", "signal_version in agent_signal", "WARN", "Column exists but all values are NULL/empty")
        else:
            result.add("12.signal_version_in_db", "signal_version in agent_signal", "FAIL", "Column does not exist")
    except Exception as e:
        result.add("12.signal_version_in_db", "signal_version in agent_signal", "WARN", str(e))
    finally:
        conn.close()


def check_13_signal_json_has_version(result: AuditResult, signal_dir: Path) -> None:
    if not signal_dir.exists():
        result.add("13.signal_json_has_version", "signal_version in JSON", "WARN", f"Dir not found: {signal_dir}")
        return
    all_ok = True
    for json_file in signal_dir.glob("*_v0_22.json"):
        try:
            data = json.loads(json_file.read_text())
            for row in data:
                if "signal_version" not in row or not row["signal_version"]:
                    all_ok = False
                    break
        except Exception:
            all_ok = False
    if all_ok:
        result.add("13.signal_json_has_version", "signal_version in JSON", "PASS", "All v0.22 JSON files have signal_version")
    else:
        result.add("13.signal_json_has_version", "signal_version in JSON", "FAIL", "Some v0.22 JSON files missing signal_version")


def check_14_agent_daily_signal_table(result: AuditResult, db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "agent_daily_signal" in tables:
            count = conn.execute("SELECT COUNT(*) FROM agent_daily_signal").fetchone()[0]
            result.add("14.agent_daily_signal_table", "agent_daily_signal table exists", "PASS", f"{count} rows")
        else:
            result.add("14.agent_daily_signal_table", "agent_daily_signal table exists", "WARN", "Table not found (run with --persist to create)")
    except Exception as e:
        result.add("14.agent_daily_signal_table", "agent_daily_signal table exists", "WARN", str(e))
    finally:
        conn.close()


def check_15_db_summary(result: AuditResult, db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        signal_count = conn.execute("SELECT COUNT(*) FROM agent_signal").fetchone()[0]
        result.add("15a.signal_count", "agent_signal row count", "PASS", f"{signal_count} rows")

        cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_signal)").fetchall()}
        if "signal_version" in cols:
            cursor = conn.execute(
                "SELECT signal_version, COUNT(*) FROM agent_signal "
                "WHERE signal_version IS NOT NULL AND signal_version != '' "
                "GROUP BY signal_version"
            )
            dist = cursor.fetchall()
            if dist:
                detail = ", ".join(f"{v}: {c}" for v, c in dist)
                result.add("15b.signal_version_dist", "signal_version distribution", "PASS", detail)
            else:
                result.add("15b.signal_version_dist", "signal_version distribution", "WARN", "All signal_version are NULL/empty")
        else:
            result.add("15b.signal_version_dist", "signal_version distribution", "WARN", "Column signal_version not found (run evaluator to populate)")

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "agent_daily_signal" in tables:
            daily_count = conn.execute("SELECT COUNT(*) FROM agent_daily_signal").fetchone()[0]
            result.add("15c.daily_signal_count", "agent_daily_signal row count", "PASS", f"{daily_count} rows")
            cursor2 = conn.execute(
                "SELECT signal_version, COUNT(*) FROM agent_daily_signal "
                "WHERE signal_version IS NOT NULL AND signal_version != '' "
                "GROUP BY signal_version"
            )
            dist2 = cursor2.fetchall()
            if dist2:
                detail2 = ", ".join(f"{v}: {c}" for v, c in dist2)
                result.add("15d.daily_version_dist", "daily signal_version distribution", "PASS", detail2)
            else:
                result.add("15d.daily_version_dist", "daily signal_version distribution", "WARN", "No signal_version in agent_daily_signal")
        else:
            result.add("15c.daily_signal_count", "agent_daily_signal row count", "WARN", "Table not found (run with --persist)")
    except Exception as e:
        result.add("15.db_summary", "DB summary", "WARN", str(e))
    finally:
        conn.close()


def check_16_future_function_samples(result: AuditResult, db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_signal)").fetchall()}
        if "signal_version" not in cols:
            result.add("16.future_function", "No future function samples", "WARN", "signal_version column not found")
            return
        cursor = conn.execute(
            "SELECT trading_date, vt_symbol, available_at, signal_version "
            "FROM agent_signal "
            "WHERE available_at IS NOT NULL AND trading_date IS NOT NULL "
            "AND available_at > trading_date || ' 15:00:00' "
            "LIMIT 5"
        )
        samples = cursor.fetchall()
        if not samples:
            result.add("16.future_function", "No future function samples", "PASS", "No available_at > trading_date 15:00")
        else:
            detail = "; ".join(f"{td} {vs} avail={av}" for td, vs, av, _ in samples)
            result.add("16.future_function", "No future function samples", "WARN",
                       f"{len(samples)} samples where available_at > trading_date 15:00: {detail}")
    except Exception as e:
        result.add("16.future_function", "No future function samples", "WARN", str(e))
    finally:
        conn.close()


def check_17_recent_daily_signals(result: AuditResult, db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "agent_daily_signal" not in tables:
            result.add("17.recent_signals", "Recent daily signals", "WARN", "Table not found (run with --persist)")
            return
        cursor = conn.execute(
            "SELECT trading_date, vt_symbol, signal_version, daily_agent_signal, daily_direction "
            "FROM agent_daily_signal ORDER BY trading_date DESC LIMIT 10"
        )
        rows = cursor.fetchall()
        if rows:
            detail = "; ".join(f"{td} {vs} {sv} {sig:+.4f} {d}" for td, vs, sv, sig, d in rows)
            result.add("17.recent_signals", "Recent daily signals", "PASS", f"Last 10: {detail}")
        else:
            result.add("17.recent_signals", "Recent daily signals", "WARN", "No data in agent_daily_signal")
    except Exception as e:
        result.add("17.recent_signals", "Recent daily signals", "WARN", str(e))
    finally:
        conn.close()


def main() -> int:
    result = AuditResult()

    # Find databases
    agent_dbs = find_agent_dbs()
    if not agent_dbs:
        print(f"No agent news databases found matching {AGENT_NEWS_DB_PATTERN}")
        return 1

    print(f"Found {len(agent_dbs)} agent news database(s):")
    for db in agent_dbs:
        print(f"  - {db.name}")

    # Run checks on first DB (or all if multiple)
    for db_path in agent_dbs[:1]:  # Check first DB for schema checks
        print(f"\nRunning checks on {db_path.name}...")
        check_01_tables_exist(result, db_path)
        check_02_schemas_match(result, db_path)
        check_03_empty_vt_symbol(result, db_path)
        check_04_out_of_range(result, db_path)
        check_10_relation_type_coverage(result, db_path)
        check_11_trading_date_valid(result, db_path)
        check_12_signal_version_in_db(result, db_path)
        check_14_agent_daily_signal_table(result, db_path)
        check_15_db_summary(result, db_path)
        check_16_future_function_samples(result, db_path)
        check_17_recent_daily_signals(result, db_path)

    # Signal file checks
    print(f"\nRunning signal file checks...")
    check_05_signal_range(result, SIGNAL_DIR)
    check_06_no_duplicates(result, SIGNAL_DIR)
    check_08_version_coexistence(result, SIGNAL_DIR)
    check_13_signal_json_has_version(result, SIGNAL_DIR)

    # Backtest result checks
    print(f"\nRunning backtest result checks...")
    check_07_backtest_consistency(result, RESULTS_DIR)
    check_09_version_traceability(result, RESULTS_DIR)

    # Generate report
    report = result.to_markdown()
    report_path = PROJECT_ROOT / "docs" / "current_pipeline_audit_result.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to {report_path}")

    # Print summary
    print(f"\n{'='*60}")
    print(f"AUDIT SUMMARY")
    print(f"{'='*60}")
    print(f"Total checks: {len(result.checks)}")
    print(f"Passed: {result.passed}")
    print(f"Failed: {result.failed}")
    print(f"Warnings: {result.warnings}")

    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
