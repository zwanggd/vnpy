""""""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path


def load_agent_signals(
    db_path: str | None = None,
    json_path: str | None = None,
    signal_version: str | None = None,
) -> dict[date, dict]:
    """Load daily agent signals from DB or JSON.

    Priority: agent_daily_signal table → legacy daily_agent_signal table → JSON.

    Args:
        db_path: Path to SQLite agent news DB.
        json_path: Path to JSON signal file.
        signal_version: Optional filter for signal_version column (DB only).

    Returns:
        dict mapping trading_date → {"signal": float, "direction": str}
    """
    if db_path and Path(db_path).exists():
        return _from_db(db_path, signal_version)
    if json_path and Path(json_path).exists():
        return _from_json(json_path)
    if db_path:
        raise FileNotFoundError(f"Database not found: {db_path}")
    if json_path:
        raise FileNotFoundError(f"JSON file not found: {json_path}")
    raise ValueError("Must provide db_path or json_path")


def _from_db(db_path: str, signal_version: str | None = None) -> dict[date, dict]:
    db = sqlite3.connect(db_path)

    # Try canonical table first: agent_daily_signal
    canonical_cols = db.execute("PRAGMA table_info(agent_daily_signal)").fetchall()
    if canonical_cols:
        col_names = {row[1] for row in canonical_cols}
        if "trading_date" in col_names and "daily_agent_signal" in col_names:
            return _query_canonical(db, signal_version)

    # Fallback: legacy daily_agent_signal table
    legacy_cols = db.execute("PRAGMA table_info(daily_agent_signal)").fetchall()
    if legacy_cols:
        col_names = {row[1] for row in legacy_cols}
        if "entry_date" in col_names:
            return _query_legacy(db, signal_version)

    db.close()
    raise ValueError(f"No signal table found in {db_path}")


def _query_canonical(db: sqlite3.Connection, signal_version: str | None) -> dict[date, dict]:
    if signal_version:
        rows = db.execute(
            "SELECT trading_date, daily_agent_signal, daily_direction "
            "FROM agent_daily_signal WHERE signal_version = ?",
            (signal_version,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT trading_date, daily_agent_signal, daily_direction FROM agent_daily_signal"
        ).fetchall()
    db.close()
    return _parse_rows(rows)


def _query_legacy(db: sqlite3.Connection, signal_version: str | None) -> dict[date, dict]:
    if signal_version:
        rows = db.execute(
            "SELECT entry_date, daily_agent_signal, daily_direction "
            "FROM daily_agent_signal WHERE signal_version = ?",
            (signal_version,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT entry_date, daily_agent_signal, daily_direction FROM daily_agent_signal"
        ).fetchall()
    db.close()
    return _parse_rows(rows)


def _parse_rows(rows: list[tuple]) -> dict[date, dict]:
    result: dict[date, dict] = {}
    for date_str, sig, direction in rows:
        if sig is None:
            continue
        d = date.fromisoformat(str(date_str)[:10])
        result[d] = {"signal": float(sig), "direction": direction or "neutral"}
    return result


def _from_json(json_path: str) -> dict[date, dict]:
    data = json.loads(Path(json_path).read_text())
    result: dict[date, dict] = {}
    for item in data:
        d = date.fromisoformat(item["trading_date"][:10])
        result[d] = {
            "signal": float(item.get("daily_agent_signal", 0) or 0),
            "direction": item.get("daily_direction", "neutral"),
        }
    return result
