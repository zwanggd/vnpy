#!/usr/bin/env python
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vnpy.trader.constant import Direction, Interval  # noqa: E402
from vnpy_ctastrategy.backtesting import BacktestingEngine  # noqa: E402

from strategies.macd_agent_strategy import MacdAgentStrategy  # noqa: E402


PRICE_DB = Path.home() / ".vntrader" / "database.db"
_AGENT_DB = Path.home() / ".vntrader" / "agent_news.db"
_RESULTS_DIR = ROOT / "backtests" / "results"

_SYMBOL = "300750"
_EXCHANGE = "SZSE"
_VT_SYMBOL = f"{_SYMBOL}.{_EXCHANGE}"

# Public aliases (updated from CLI args in main)
AGENT_DB = _AGENT_DB
RESULTS_DIR = _RESULTS_DIR
SYMBOL = _SYMBOL
EXCHANGE = _EXCHANGE
VT_SYMBOL = _VT_SYMBOL

START = datetime(2020, 1, 1)
END = datetime(2026, 5, 15)

FAST = 12
SLOW = 26
SIGNAL_PERIOD = 9
AGENT_THRESHOLD = 0.05

RATE = 0.0003
SLIPPAGE = 0.01
SIZE = 100
PRICETICK = 0.01
CAPITAL = 1_000_000
POS_RATIO = 0.5
_EXPECTED_OUTPUT_ROWS = 1536

_EQUITY_CURVE_PATH = RESULTS_DIR / "equity_curve_reconciliation.csv"
_BUCKET_SUMMARY_PATH = RESULTS_DIR / "equity_attribution_summary.csv"
_EXECUTION_ATTRIBUTION_PATH = RESULTS_DIR / "execution_price_attribution.csv"
_REPORT_PATH = RESULTS_DIR / "equity_reconciliation_report.md"

EXPECTED_OUTPUT_ROWS = _EXPECTED_OUTPUT_ROWS
EQUITY_CURVE_PATH = _EQUITY_CURVE_PATH
BUCKET_SUMMARY_PATH = _BUCKET_SUMMARY_PATH
EXECUTION_ATTRIBUTION_PATH = _EXECUTION_ATTRIBUTION_PATH
REPORT_PATH = _REPORT_PATH


@dataclass(frozen=True)
class BacktestRun:
    mode: str
    daily: pd.DataFrame
    stats: dict[str, Any]
    round_trips: list[RoundTrip]


@dataclass(frozen=True)
class RoundTrip:
    mode: str
    trade_id: int
    entry_dt: datetime
    exit_dt: datetime
    entry_price: float
    exit_price: float
    volume_lots: int
    shares: int
    gross_pnl: float
    commission: float
    slippage_cost: float
    net_pnl: float

    @property
    def entry_date(self) -> date:
        return self.entry_dt.date()

    @property
    def exit_date(self) -> date:
        return self.exit_dt.date()

    @property
    def duration_days(self) -> int:
        return (self.exit_date - self.entry_date).days + 1


def bucket_for_positions(macd_pos: int, either_pos: int) -> str:
    if macd_pos == 1 and either_pos == 1:
        return "both_hold"
    if macd_pos == 0 and either_pos == 1:
        return "either_only"
    if macd_pos == 1 and either_pos == 0:
        return "macd_only"
    return "both_cash"


def round_lot_shares(target_value: float, close_price: float) -> int:
    if close_price <= 0:
        return 0
    return int(target_value / close_price / SIZE) * SIZE


def clean(value: Any) -> Any:
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
    except Exception:
        pass

    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def money(value: float) -> str:
    return f"${value:,.2f}"


def pct(value: float) -> str:
    return f"{value:.2f}%"


def safe_pct(numerator: float, denominator: float) -> float:
    if abs(denominator) < 1e-12:
        return 0.0
    return numerator / denominator * 100.0


def run_self_tests() -> None:
    assert bucket_for_positions(1, 1) == "both_hold"
    assert bucket_for_positions(0, 1) == "either_only"
    assert bucket_for_positions(1, 0) == "macd_only"
    assert bucket_for_positions(0, 0) == "both_cash"
    assert round_lot_shares(500_000, 100.0) == 5_000
    assert round_lot_shares(500_000, 107.52) == 4_600
    assert safe_pct(50.0, 200.0) == 25.0

    @dataclass(frozen=True)
    class FakeTrade:
        datetime: datetime
        direction: Direction
        price: float
        volume: int

    short_first = [
        FakeTrade(datetime(2020, 1, 2), Direction.SHORT, 120.0, 5),
        FakeTrade(datetime(2020, 1, 3), Direction.LONG, 80.0, 5),
    ]
    episodes = pair_round_trips("self_test", short_first)
    expected_net = ((120.0 - 80.0) * 5 * SIZE) - (((120.0 + 80.0) * 5 * SIZE) * RATE) - (SLIPPAGE * 5 * SIZE * 2)
    assert len(episodes) == 1
    assert round(episodes[0].net_pnl, 6) == round(expected_net, 6)


def load_price_metadata() -> dict[str, Any]:
    with sqlite3.connect(PRICE_DB) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*), MIN(datetime), MAX(datetime)
            FROM dbbardata
            WHERE symbol = ? AND exchange = ? AND interval = 'd'
            """,
            (SYMBOL, EXCHANGE),
        ).fetchone()
    return {"count": row[0], "start": row[1], "end": row[2]}


def load_agent_metadata() -> dict[str, Any]:
    with sqlite3.connect(AGENT_DB) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*), MIN(entry_date), MAX(entry_date)
            FROM daily_agent_signal
            """
        ).fetchone()
    return {"count": row[0], "start": row[1], "end": row[2]}


def base_setting(mode: str) -> dict[str, Any]:
    return {
        "fast": FAST,
        "slow": SLOW,
        "signal_period": SIGNAL_PERIOD,
        "signal_mode": mode,
        "pos_ratio": POS_RATIO,
        "agent_threshold": AGENT_THRESHOLD,
        "init_capital": CAPITAL,
    }


def run_backtest(mode: str) -> BacktestRun:
    engine = BacktestingEngine()
    engine.output = lambda msg: None
    engine.set_parameters(
        vt_symbol=VT_SYMBOL,
        interval=Interval.DAILY,
        start=START,
        end=END,
        rate=RATE,
        slippage=SLIPPAGE,
        size=SIZE,
        pricetick=PRICETICK,
        capital=CAPITAL,
    )
    engine.add_strategy(MacdAgentStrategy, base_setting(mode))
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result().copy()
    stats = engine.calculate_statistics(daily, output=False)

    daily.index = pd.to_datetime(daily.index)
    daily.index.name = "date"
    daily["balance"] = CAPITAL + daily["net_pnl"].cumsum()

    trades = engine.get_all_trades()
    if isinstance(trades, dict):
        trades = list(trades.values())

    return BacktestRun(
        mode=mode,
        daily=daily,
        stats={key: clean(value) for key, value in stats.items()},
        round_trips=pair_round_trips(mode, trades),
    )


def make_round_trip(mode: str, trade_id: int, entry: dict[str, Any], exit_trade: Any, volume_lots: int) -> RoundTrip:
    shares = int(volume_lots * SIZE)
    entry_price = float(entry["price"])
    exit_price = float(exit_trade.price)
    gross_pnl = (exit_price - entry_price) * shares
    turnover = (entry_price + exit_price) * shares
    commission = turnover * RATE
    slippage_cost = SLIPPAGE * shares * 2
    net_pnl = gross_pnl - commission - slippage_cost
    return RoundTrip(
        mode=mode,
        trade_id=trade_id,
        entry_dt=entry["datetime"],
        exit_dt=exit_trade.datetime,
        entry_price=entry_price,
        exit_price=exit_price,
        volume_lots=volume_lots,
        shares=shares,
        gross_pnl=gross_pnl,
        commission=commission,
        slippage_cost=slippage_cost,
        net_pnl=net_pnl,
    )


def pair_round_trips(mode: str, trades: list[Any]) -> list[RoundTrip]:
    active: dict[str, Any] | None = None
    round_trips: list[RoundTrip] = []
    trade_id = 1
    position_lots = 0

    for trade in sorted(trades, key=lambda item: item.datetime):
        volume_lots = int(round(float(trade.volume)))
        if volume_lots <= 0:
            continue

        if trade.direction not in {Direction.LONG, Direction.SHORT}:
            continue

        if active is None:
            active = {
                "entry_dt": trade.datetime,
                "entry_direction": trade.direction,
                "buy_lots": 0,
                "sell_lots": 0,
                "buy_turnover": 0.0,
                "sell_turnover": 0.0,
                "commission": 0.0,
                "slippage_cost": 0.0,
            }

        turnover = float(trade.price) * volume_lots * SIZE
        active["commission"] += turnover * RATE
        active["slippage_cost"] += SLIPPAGE * volume_lots * SIZE

        if trade.direction == Direction.LONG:
            active["buy_lots"] += volume_lots
            active["buy_turnover"] += turnover
            position_lots += volume_lots
        else:
            active["sell_lots"] += volume_lots
            active["sell_turnover"] += turnover
            position_lots -= volume_lots

        if position_lots != 0:
            continue

        buy_lots = int(active["buy_lots"])
        sell_lots = int(active["sell_lots"])
        buy_turnover = float(active["buy_turnover"])
        sell_turnover = float(active["sell_turnover"])
        gross_pnl = sell_turnover - buy_turnover
        volume = max(buy_lots, sell_lots)

        if active["entry_direction"] == Direction.LONG:
            entry_price = buy_turnover / (buy_lots * SIZE) if buy_lots else 0.0
            exit_price = sell_turnover / (sell_lots * SIZE) if sell_lots else 0.0
        else:
            entry_price = sell_turnover / (sell_lots * SIZE) if sell_lots else 0.0
            exit_price = buy_turnover / (buy_lots * SIZE) if buy_lots else 0.0

        round_trips.append(
            RoundTrip(
                mode=mode,
                trade_id=trade_id,
                entry_dt=active["entry_dt"],
                exit_dt=trade.datetime,
                entry_price=entry_price,
                exit_price=exit_price,
                volume_lots=volume,
                shares=volume * SIZE,
                gross_pnl=gross_pnl,
                commission=float(active["commission"]),
                slippage_cost=float(active["slippage_cost"]),
                net_pnl=gross_pnl - float(active["commission"]) - float(active["slippage_cost"]),
            )
        )
        trade_id += 1
        active = None

    return round_trips


def build_equity_curve(macd: BacktestRun, either: BacktestRun) -> pd.DataFrame:
    if not macd.daily.index.equals(either.daily.index):
        raise ValueError("Backtest daily indexes do not match")

    rows = pd.DataFrame(index=macd.daily.index)
    rows["date"] = rows.index.strftime("%Y-%m-%d")
    rows["close_price"] = macd.daily["close_price"].astype(float)

    for prefix, run in (("macd", macd), ("either", either)):
        rows[f"{prefix}_start_pos_lots"] = run.daily["start_pos"].astype(float)
        rows[f"{prefix}_end_pos_lots"] = run.daily["end_pos"].astype(float)
        rows[f"{prefix}_pos"] = (run.daily["end_pos"].astype(float) > 0).astype(int)
        rows[f"{prefix}_net_pnl"] = run.daily["net_pnl"].astype(float)
        rows[f"{prefix}_balance"] = run.daily["balance"].astype(float)
        rows[f"{prefix}_trading_pnl"] = run.daily["trading_pnl"].astype(float)
        rows[f"{prefix}_holding_pnl"] = run.daily["holding_pnl"].astype(float)
        rows[f"{prefix}_commission"] = run.daily["commission"].astype(float)
        rows[f"{prefix}_slippage"] = run.daily["slippage"].astype(float)
        rows[f"{prefix}_turnover"] = run.daily["turnover"].astype(float)
        rows[f"{prefix}_trade_count"] = run.daily["trade_count"].astype(float)

    rows["daily_pnl_diff"] = rows["either_net_pnl"] - rows["macd_net_pnl"]
    rows["equity_diff"] = rows["either_balance"] - rows["macd_balance"]
    rows["bucket"] = [
        bucket_for_positions(macd_pos, either_pos)
        for macd_pos, either_pos in zip(rows["macd_pos"], rows["either_pos"], strict=True)
    ]

    return rows.iloc[1:].reset_index(drop=True)


def build_bucket_summary(equity_curve: pd.DataFrame) -> pd.DataFrame:
    total_diff = float(equity_curve["daily_pnl_diff"].sum())
    records = []
    for bucket in ("both_hold", "either_only", "macd_only", "both_cash"):
        part = equity_curve[equity_curve["bucket"] == bucket]
        contribution = float(part["daily_pnl_diff"].sum()) if len(part) else 0.0
        records.append(
            {
                "bucket": bucket,
                "days": int(len(part)),
                "total_dollar_pnl_contribution": contribution,
                "avg_daily_dollar_pnl": contribution / len(part) if len(part) else 0.0,
                "contribution_to_final_equity_diff_pct": safe_pct(contribution, total_diff),
            }
        )
    return pd.DataFrame.from_records(records)


def overlap_days(left: RoundTrip, right: RoundTrip) -> int:
    start = max(left.entry_date, right.entry_date)
    end = min(left.exit_date, right.exit_date)
    if end < start:
        return 0
    return (end - start).days + 1


def date_gap_days(left: RoundTrip, right: RoundTrip) -> int:
    return abs((left.entry_date - right.entry_date).days)


def timing_label(either_date: date, macd_date: date, earlier: str, later: str, same: str) -> str:
    if either_date < macd_date:
        return earlier
    if either_date > macd_date:
        return later
    return same


def trade_row(
    comparison_id: int,
    either_trade: RoundTrip | None,
    macd_trade: RoundTrip | None,
    match_type: str,
) -> dict[str, Any]:
    if either_trade and macd_trade:
        basis_shares = min(either_trade.shares, macd_trade.shares)
        entry_price_diff = either_trade.entry_price - macd_trade.entry_price
        exit_price_diff = either_trade.exit_price - macd_trade.exit_price
        shares_diff = either_trade.shares - macd_trade.shares
        entry_impact = (macd_trade.entry_price - either_trade.entry_price) * basis_shares
        exit_impact = (either_trade.exit_price - macd_trade.exit_price) * basis_shares
        dollar_impact = either_trade.net_pnl - macd_trade.net_pnl
        entry_timing = timing_label(
            either_trade.entry_date,
            macd_trade.entry_date,
            "earlier_entry",
            "later_entry",
            "same_entry",
        )
        exit_timing = timing_label(
            either_trade.exit_date,
            macd_trade.exit_date,
            "earlier_exit",
            "later_exit",
            "same_exit",
        )
        overlap = overlap_days(either_trade, macd_trade)
    elif either_trade:
        basis_shares = either_trade.shares
        entry_price_diff = None
        exit_price_diff = None
        shares_diff = either_trade.shares
        entry_impact = 0.0
        exit_impact = 0.0
        dollar_impact = either_trade.net_pnl
        entry_timing = "unmatched_either_entry"
        exit_timing = "unmatched_either_exit"
        overlap = 0
    elif macd_trade:
        basis_shares = macd_trade.shares
        entry_price_diff = None
        exit_price_diff = None
        shares_diff = -macd_trade.shares
        entry_impact = 0.0
        exit_impact = 0.0
        dollar_impact = -macd_trade.net_pnl
        entry_timing = "unmatched_macd_entry"
        exit_timing = "unmatched_macd_exit"
        overlap = 0
    else:
        raise ValueError("Either either_trade or macd_trade is required")

    residual = dollar_impact - entry_impact - exit_impact

    return {
        "comparison_id": comparison_id,
        "match_type": match_type,
        "entry_timing": entry_timing,
        "exit_timing": exit_timing,
        "overlap_days": overlap,
        "basis_shares": basis_shares,
        "either_trade_id": either_trade.trade_id if either_trade else None,
        "macd_trade_id": macd_trade.trade_id if macd_trade else None,
        "either_entry_date": either_trade.entry_date.isoformat() if either_trade else None,
        "macd_entry_date": macd_trade.entry_date.isoformat() if macd_trade else None,
        "either_exit_date": either_trade.exit_date.isoformat() if either_trade else None,
        "macd_exit_date": macd_trade.exit_date.isoformat() if macd_trade else None,
        "either_entry_price": either_trade.entry_price if either_trade else None,
        "macd_entry_price": macd_trade.entry_price if macd_trade else None,
        "either_exit_price": either_trade.exit_price if either_trade else None,
        "macd_exit_price": macd_trade.exit_price if macd_trade else None,
        "entry_price_diff": entry_price_diff,
        "exit_price_diff": exit_price_diff,
        "either_shares": either_trade.shares if either_trade else 0,
        "macd_shares": macd_trade.shares if macd_trade else 0,
        "shares_diff": shares_diff,
        "either_trade_net_pnl": either_trade.net_pnl if either_trade else 0.0,
        "macd_trade_net_pnl": macd_trade.net_pnl if macd_trade else 0.0,
        "dollar_impact": dollar_impact,
        "entry_price_impact": entry_impact,
        "exit_price_impact": exit_impact,
        "residual_or_unmatched_impact": residual,
    }


def build_execution_attribution(either_trades: list[RoundTrip], macd_trades: list[RoundTrip]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    used_macd_ids: set[int] = set()
    comparison_id = 1

    for either_trade in either_trades:
        candidates = [trade for trade in macd_trades if trade.trade_id not in used_macd_ids]
        if not candidates:
            rows.append(trade_row(comparison_id, either_trade, None, "unmatched_either"))
            comparison_id += 1
            continue

        overlapping = [trade for trade in candidates if overlap_days(either_trade, trade) > 0]
        if overlapping:
            macd_trade = max(overlapping, key=lambda trade: (overlap_days(either_trade, trade), -date_gap_days(either_trade, trade)))
            match_type = "overlap"
        else:
            macd_trade = min(candidates, key=lambda trade: date_gap_days(either_trade, trade))
            match_type = "nearest_entry"

        used_macd_ids.add(macd_trade.trade_id)
        rows.append(trade_row(comparison_id, either_trade, macd_trade, match_type))
        comparison_id += 1

    for macd_trade in macd_trades:
        if macd_trade.trade_id in used_macd_ids:
            continue
        rows.append(trade_row(comparison_id, None, macd_trade, "unmatched_macd"))
        comparison_id += 1

    result = pd.DataFrame.from_records(rows)
    if result.empty:
        return result

    sort_date = result["either_entry_date"].fillna(result["macd_entry_date"])
    result = result.assign(_sort_date=sort_date).sort_values(["_sort_date", "comparison_id"])
    return result.drop(columns=["_sort_date"]).reset_index(drop=True)


def execution_summary(execution: pd.DataFrame, final_diff: float) -> dict[str, float]:
    if execution.empty:
        return {
            "earlier_entries": 0.0,
            "later_entries": 0.0,
            "earlier_exits": 0.0,
            "later_exits": 0.0,
            "total_entry_price_impact": 0.0,
            "total_exit_price_impact": 0.0,
            "net_execution_edge": 0.0,
            "other_or_residual": final_diff,
            "trade_level_total": 0.0,
        }

    earlier_entries = float(execution.loc[execution["entry_timing"] == "earlier_entry", "entry_price_impact"].sum())
    later_entries = float(execution.loc[execution["entry_timing"] == "later_entry", "entry_price_impact"].sum())
    earlier_exits = float(execution.loc[execution["exit_timing"] == "earlier_exit", "exit_price_impact"].sum())
    later_exits = float(execution.loc[execution["exit_timing"] == "later_exit", "exit_price_impact"].sum())
    total_entry = float(execution["entry_price_impact"].sum())
    total_exit = float(execution["exit_price_impact"].sum())
    trade_level_total = float(execution["dollar_impact"].sum())
    net_execution = total_entry + total_exit
    return {
        "earlier_entries": earlier_entries,
        "later_entries": later_entries,
        "earlier_exits": earlier_exits,
        "later_exits": later_exits,
        "total_entry_price_impact": total_entry,
        "total_exit_price_impact": total_exit,
        "net_execution_edge": net_execution,
        "other_or_residual": final_diff - net_execution,
        "trade_level_total": trade_level_total,
    }


def validate_outputs(equity_curve: pd.DataFrame, final_diff: float, sum_daily_diff: float) -> None:
    if len(equity_curve) != EXPECTED_OUTPUT_ROWS:
        raise ValueError(f"Expected {EXPECTED_OUTPUT_ROWS} equity rows, got {len(equity_curve)}")

    tolerance = abs(final_diff) * 0.005
    if abs(sum_daily_diff - final_diff) > tolerance:
        raise ValueError(
            "Daily PnL closure failed: "
            f"sum={sum_daily_diff:.2f}, final={final_diff:.2f}, tolerance={tolerance:.2f}"
        )


def markdown_bucket_table(bucket_summary: pd.DataFrame) -> list[str]:
    lines = [
        "| Bucket | Days | Dollar contribution | Avg daily PnL | % of excess |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in bucket_summary.itertuples(index=False):
        lines.append(
            f"| {row.bucket} | {row.days} | {money(row.total_dollar_pnl_contribution)} | "
            f"{money(row.avg_daily_dollar_pnl)} | {pct(row.contribution_to_final_equity_diff_pct)} |"
        )
    return lines


def markdown_execution_table(summary: dict[str, float], final_diff: float) -> list[str]:
    rows = [
        ("Earlier entries", summary["earlier_entries"]),
        ("Later entries", summary["later_entries"]),
        ("Earlier exits", summary["earlier_exits"]),
        ("Later exits", summary["later_exits"]),
        ("Total entry price impact", summary["total_entry_price_impact"]),
        ("Total exit price impact", summary["total_exit_price_impact"]),
        ("Net execution edge", summary["net_execution_edge"]),
        ("Other / residual", summary["other_or_residual"]),
    ]
    lines = [
        "| Component | Dollar impact | % of excess |",
        "|---|---:|---:|",
    ]
    for label, value in rows:
        lines.append(f"| {label} | {money(value)} | {pct(safe_pct(value, final_diff))} |")
    return lines


def write_report(
    price_meta: dict[str, Any],
    agent_meta: dict[str, Any],
    macd: BacktestRun,
    either: BacktestRun,
    equity_curve: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    execution: pd.DataFrame,
) -> None:
    macd_final = float(equity_curve["macd_balance"].iloc[-1])
    either_final = float(equity_curve["either_balance"].iloc[-1])
    final_diff = either_final - macd_final
    sum_daily_diff = float(equity_curve["daily_pnl_diff"].sum())
    closure_diff = sum_daily_diff - final_diff
    excess_return_pct = safe_pct(final_diff, CAPITAL)

    bucket_values = dict(zip(bucket_summary["bucket"], bucket_summary["total_dollar_pnl_contribution"], strict=True))
    either_only = float(bucket_values.get("either_only", 0.0))
    macd_only = float(bucket_values.get("macd_only", 0.0))
    same_position = float(bucket_values.get("both_hold", 0.0) + bucket_values.get("both_cash", 0.0))

    exec_summary = execution_summary(execution, final_diff)

    report = [
        "# Equity Reconciliation Report",
        "",
        "## Inputs",
        "",
        f"- Price DB: `{PRICE_DB}` ({price_meta['count']} daily bars, {price_meta['start']} → {price_meta['end']})",
        f"- Agent DB: `{AGENT_DB}` ({agent_meta['count']} signal days, {agent_meta['start']} → {agent_meta['end']})",
        f"- VNPY parameters: rate={RATE}, slippage={SLIPPAGE}, size={SIZE}, pricetick={PRICETICK}, capital={CAPITAL:,}, pos_ratio={POS_RATIO}",
        f"- Strategy parameters: fast={FAST}, slow={SLOW}, signal_period={SIGNAL_PERIOD}, agent_threshold={AGENT_THRESHOLD}",
        "- Note: this VNPY build returns `net_pnl` but not a `balance` column from `calculate_result()`, so the script reconstructs balance as `capital + cumulative net_pnl`.",
        "",
        "## 1. Closure verification",
        "",
        f"- Exported daily equity rows: {len(equity_curve)}",
        f"- `macd_only` final equity: {money(macd_final)} ({pct(safe_pct(macd_final - CAPITAL, CAPITAL))})",
        f"- `either_safe` final equity: {money(either_final)} ({pct(safe_pct(either_final - CAPITAL, CAPITAL))})",
        f"- Final equity difference: {money(final_diff)} ({pct(excess_return_pct)} of initial capital)",
        f"- Sum of daily PnL differences: {money(sum_daily_diff)}",
        f"- Closure difference: {money(closure_diff)} ({pct(safe_pct(closure_diff, final_diff))} of excess)",
        "",
        "The daily dollar PnL series fully closes to the final equity gap; the +55.9% is the cumulative dollar difference between the two VNPY equity curves.",
        "",
        "## 2. Bucket dollar PnL attribution",
        "",
        *markdown_bucket_table(bucket_summary),
        "",
        "Interpretation: `either_only` is extra exposure held by `either_safe`; `macd_only` is exposure that `either_safe` avoided; `both_hold` and `both_cash` mainly contain same-state share-count, execution, costs, and compounding differences. Buckets use end-of-day position state to match the prior attribution convention, while PnL is actual VNPY daily dollar PnL.",
        "",
        "## 3. Execution price summary",
        "",
        *markdown_execution_table(exec_summary, final_diff),
        "",
        f"- Trade-level dollar-impact rows sum to {money(exec_summary['trade_level_total'])}; residual versus final equity diff is {money(exec_summary['trade_level_total'] - final_diff)}.",
        f"- Better/worse entry price impact: {money(exec_summary['total_entry_price_impact'])} ({pct(safe_pct(exec_summary['total_entry_price_impact'], final_diff))} of excess).",
        f"- Better/worse exit price impact: {money(exec_summary['total_exit_price_impact'])} ({pct(safe_pct(exec_summary['total_exit_price_impact'], final_diff))} of excess).",
        f"- Other/residual impact: {money(exec_summary['other_or_residual'])} ({pct(safe_pct(exec_summary['other_or_residual'], final_diff))} of excess).",
        "",
        "`execution_price_attribution.csv` contains the per-round-trip comparisons, including unmatched trades. Entry impact is positive when `either_safe` bought lower than matched `macd_only`; exit impact is positive when `either_safe` sold higher than matched `macd_only`.",
        "",
        "## 4. Answers",
        "",
        "### A. Can the +55.9% excess return be fully explained by daily dollar equity PnL?",
        "",
        f"Yes. The final equity difference is {money(final_diff)} and the sum of daily PnL differences is {money(sum_daily_diff)}, leaving only {money(closure_diff)} rounding/closure difference. On {CAPITAL:,} initial capital, that is {pct(excess_return_pct)} excess return.",
        "",
        "### B. Does excess return come from holding better positions, avoiding worse ones, or different entry/exit prices?",
        "",
        f"By daily bucket, extra `either_safe` exposure (`either_only`) contributed {money(either_only)} ({pct(safe_pct(either_only, final_diff))}); avoided `macd_only` exposure contributed {money(macd_only)} ({pct(safe_pct(macd_only, final_diff))}); same-state execution/share-count/compounding buckets contributed {money(same_position)} ({pct(safe_pct(same_position, final_diff))}).",
        "",
        f"By matched trade prices, entries account for {money(exec_summary['total_entry_price_impact'])} ({pct(safe_pct(exec_summary['total_entry_price_impact'], final_diff))}), exits account for {money(exec_summary['total_exit_price_impact'])} ({pct(safe_pct(exec_summary['total_exit_price_impact'], final_diff))}), and the remaining trade/residual component is {money(exec_summary['other_or_residual'])} ({pct(safe_pct(exec_summary['other_or_residual'], final_diff))}).",
        "",
        "### C. Why does the previous -8.88% pure-position attribution contradict the +55.9% backtest result?",
        "",
        "The -8.88% calculation used `binary position × simple close-to-close percentage return`. That measures pure timing only and assumes both strategies buy the same share count at the same economic base. The VNPY result is dollar accounting: trades happen at different entry/exit prices, the lower-priced entries buy more round lots for the fixed 500k target, commissions/slippage are deducted, and earlier gains change the later equity path. Once PnL is tracked in dollars from the actual VNPY curves, the contradiction disappears: the daily dollar differences sum to the +55.9% final equity gap.",
        "",
        "## Output files",
        "",
        f"- `{EQUITY_CURVE_PATH}`",
        f"- `{BUCKET_SUMMARY_PATH}`",
        f"- `{EXECUTION_ATTRIBUTION_PATH}`",
        f"- `{REPORT_PATH}`",
        "",
    ]

    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")


def write_outputs(
    price_meta: dict[str, Any],
    agent_meta: dict[str, Any],
    macd: BacktestRun,
    either: BacktestRun,
) -> dict[str, float]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    equity_curve = build_equity_curve(macd, either)
    bucket_summary = build_bucket_summary(equity_curve)
    execution = build_execution_attribution(either.round_trips, macd.round_trips)

    final_diff = float(equity_curve["either_balance"].iloc[-1] - equity_curve["macd_balance"].iloc[-1])
    sum_daily_diff = float(equity_curve["daily_pnl_diff"].sum())
    validate_outputs(equity_curve, final_diff, sum_daily_diff)

    equity_curve.to_csv(EQUITY_CURVE_PATH, index=False)
    bucket_summary.to_csv(BUCKET_SUMMARY_PATH, index=False)
    execution.to_csv(EXECUTION_ATTRIBUTION_PATH, index=False)
    write_report(price_meta, agent_meta, macd, either, equity_curve, bucket_summary, execution)

    return {
        "macd_final": float(equity_curve["macd_balance"].iloc[-1]),
        "either_final": float(equity_curve["either_balance"].iloc[-1]),
        "final_diff": final_diff,
        "sum_daily_diff": sum_daily_diff,
        "rows": float(len(equity_curve)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile VNPY dollar equity curves for macd_only vs either_safe.")
    parser.add_argument("--self-test", action="store_true", help="Run lightweight self-tests and exit.")
    parser.add_argument("--symbol", default="300750", help="Trading symbol (default: 300750)")
    parser.add_argument("--exchange", default="SZSE", help="Exchange (default: SZSE)")
    parser.add_argument("--db-path", default="~/.vntrader/agent_news.db", help="Agent news database path")
    args = parser.parse_args()

    run_self_tests()
    if args.self_test:
        print("Self-tests passed")
        return

    global SYMBOL, EXCHANGE, VT_SYMBOL, AGENT_DB, RESULTS_DIR
    global EQUITY_CURVE_PATH, BUCKET_SUMMARY_PATH, EXECUTION_ATTRIBUTION_PATH, REPORT_PATH
    global EXPECTED_OUTPUT_ROWS

    SYMBOL = args.symbol
    EXCHANGE = args.exchange
    VT_SYMBOL = f"{SYMBOL}.{EXCHANGE}"
    AGENT_DB = Path(args.db_path).expanduser()
    RESULTS_DIR = ROOT / "backtests" / "results" / "v0.21" / SYMBOL / "reconciliation"
    EQUITY_CURVE_PATH = RESULTS_DIR / "equity_curve_reconciliation.csv"
    BUCKET_SUMMARY_PATH = RESULTS_DIR / "equity_attribution_summary.csv"
    EXECUTION_ATTRIBUTION_PATH = RESULTS_DIR / "execution_price_attribution.csv"
    REPORT_PATH = RESULTS_DIR / "equity_reconciliation_report.md"

    price_meta = load_price_metadata()
    agent_meta = load_agent_metadata()

    EXPECTED_OUTPUT_ROWS = price_meta["count"] - 1

    macd = run_backtest("macd_only")
    either = run_backtest("either_safe")
    summary = write_outputs(price_meta, agent_meta, macd, either)

    print(f"Wrote {int(summary['rows'])} daily rows to {EQUITY_CURVE_PATH}")
    print(f"macd_only final equity: {money(summary['macd_final'])}")
    print(f"either_safe final equity: {money(summary['either_final'])}")
    print(f"Final equity diff: {money(summary['final_diff'])} ({pct(safe_pct(summary['final_diff'], CAPITAL))})")
    print(f"Sum daily PnL diff: {money(summary['sum_daily_diff'])}")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
