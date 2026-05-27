#!/usr/bin/env python
"""Comprehensive audit for either_safe MACD+Agent strategy on CATL (300750.SZSE).

Task 1: Audit 10 Agent early-exit trades
Task 2: Trading cost sensitivity analysis  
Task 3: MA trend filter testing
"""

import sys
sys.path.insert(0, '..')
sys.path.insert(0, '.')

import csv
import os
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, date as Date
from pathlib import Path

from vnpy.trader.constant import Interval, Direction, Offset
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.macd_agent_strategy import MacdAgentStrategy

DB_PATH = str(Path.home() / ".vntrader" / "database.db")
_AGENT_DB_PATH = str(Path.home() / ".vntrader" / "agent_news.db")
_RESULTS_DIR = str(Path(__file__).parent.parent / "results")
_VT_SYMBOL = "300750.SZSE"

AGENT_DB_PATH = _AGENT_DB_PATH
RESULTS_DIR = _RESULTS_DIR
VT_SYMBOL = _VT_SYMBOL
SYMBOL = "300750"
EXCHANGE = "SZSE"

os.makedirs(RESULTS_DIR, exist_ok=True)
START = datetime(2020, 1, 1)
END = datetime(2026, 5, 15)
FAST, SLOW, SIG = 12, 26, 9
THRESHOLD = 0.05
POS_RATIO = 0.5
CAPITAL = 1_000_000

BASE_SETTING = {
    "fast": FAST, "slow": SLOW, "signal_period": SIG,
    "pos_ratio": POS_RATIO, "agent_threshold": THRESHOLD,
    "init_capital": CAPITAL, "signal_mode": "either_safe",
}


def wf(s):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def run_backtest(setting, rate=0.0):
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=VT_SYMBOL, interval=Interval.DAILY,
        start=START, end=END,
        rate=rate, slippage=0.01, size=100, pricetick=0.01,
        capital=CAPITAL,
    )
    engine.add_strategy(MacdAgentStrategy, setting)
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    stats = engine.calculate_statistics(daily, output=False)
    return engine, stats


def load_bars_from_db():
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        "SELECT datetime, open_price, high_price, low_price, close_price, volume "
        "FROM dbbardata WHERE symbol=? AND exchange=? "
        "AND interval='d' ORDER BY datetime",
        (SYMBOL, EXCHANGE),
    ).fetchall()
    db.close()
    return [{"dt": datetime.fromisoformat(r[0]), "open": r[1], "high": r[2],
             "low": r[3], "close": r[4], "volume": r[5]} for r in rows]


def build_bar_lookup(bars):
    return {b["dt"].date(): i for i, b in enumerate(bars)}


def compute_macd_series(bars):
    import talib
    closes = np.array([b["close"] for b in bars], dtype=np.float64)
    dif, dea, hist = talib.MACD(closes, fastperiod=FAST, slowperiod=SLOW, signalperiod=SIG)
    return dif, dea, hist


def find_death_cross(dif, dea, start_idx, max_look=252):
    for i in range(start_idx + 1, min(start_idx + max_look + 1, len(dif))):
        if np.isnan(dif[i]) or np.isnan(dea[i]) or np.isnan(dif[i-1]) or np.isnan(dea[i-1]):
            continue
        if dif[i-1] >= dea[i-1] and dif[i] < dea[i]:
            return i
    return None


def run_custom_backtest(strategy_class, setting, rate=0.0):
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=VT_SYMBOL, interval=Interval.DAILY,
        start=START, end=END,
        rate=rate, slippage=0.01, size=100, pricetick=0.01,
        capital=CAPITAL,
    )
    engine.add_strategy(strategy_class, setting)
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    stats = engine.calculate_statistics(daily, output=False)
    return engine, stats, daily


def compute_annual_breakdown(daily_df):
    if daily_df is None or daily_df.empty:
        return {}
    if not isinstance(daily_df.index, (pd.DatetimeIndex, pd.Index)):
        return {}
    dti = pd.to_datetime(daily_df.index)
    annual = {}
    for yr in range(2020, 2027):
        mask = dti.year == yr
        yr_data = daily_df.loc[mask]
        if len(yr_data) > 1:
            start_bal = yr_data["balance"].iloc[0]
            end_bal = yr_data["balance"].iloc[-1]
            if start_bal > 0:
                annual[yr] = (end_bal - start_bal) / start_bal
    return annual


# ═══════════════════════════════════════════════════════════════════════
# Task 1 — Audit Agent Early-Exit Trades
# ═══════════════════════════════════════════════════════════════════════

def task1_audit_agent_exits():
    wf("\n" + "=" * 70)
    wf("TASK 1: Audit 10 Agent Early-Exit Trades")
    wf("=" * 70)

    engine, stats = run_backtest(BASE_SETTING, rate=0.0)
    strategy = engine.strategy
    trade_log = strategy._trade_log
    trades = engine.get_all_trades()

    wf(f"  Total trades: {len(trades)}")
    wf(f"  Trade log entries: {len(trade_log)}")

    buy_queue = []
    paired = []

    for t in trades:
        if t.direction == Direction.LONG and t.offset == Offset.OPEN:
            buy_queue.append((t.datetime, t.price))
        elif t.direction == Direction.SHORT and t.offset == Offset.CLOSE:
            if buy_queue:
                bdt, bprice = buy_queue.pop(0)
                paired.append({"buy_dt": bdt, "buy_price": bprice,
                               "sell_dt": t.datetime, "sell_price": t.price})

    wf(f"  Paired round-trips: {len(paired)}")

    macd_agent_trades = []
    for i, (log_entry, pair) in enumerate(zip(trade_log, paired)):
        if log_entry["entry_src"] == "MACD" and log_entry["exit_src"] == "Agent":
            pair["entry_src"] = log_entry["entry_src"]
            pair["exit_src"] = log_entry["exit_src"]
            pair["idx"] = i
            macd_agent_trades.append(pair)

    wf(f"  MACD->Agent exit trades: {len(macd_agent_trades)}")

    if not macd_agent_trades:
        wf("  No MACD-entry Agent-exit trades  -- skipping Task 1 output.")
        return

    macd_agent_trades = macd_agent_trades[:10]

    bars = load_bars_from_db()
    bar_lookup = build_bar_lookup(bars)
    dif_arr, dea_arr, _ = compute_macd_series(bars)

    agent_db = sqlite3.connect(AGENT_DB_PATH)
    agent_db.row_factory = sqlite3.Row

    def get_daily_signal(d):
        return agent_db.execute(
            "SELECT daily_agent_signal, top_news_id, top_news_title "
            "FROM daily_agent_signal WHERE entry_date = ?",
            (d.isoformat() + " 00:00:00",)
        ).fetchone()

    def get_rationale(news_id):
        row = agent_db.execute(
            "SELECT rationale FROM news_analysis WHERE news_id = ? LIMIT 1",
            (news_id,)
        ).fetchone()
        return row["rationale"] if row else None

    results = []
    for seq_id, pair in enumerate(macd_agent_trades, 1):
        buy_dt, sell_dt = pair["buy_dt"], pair["sell_dt"]
        buy_price, sell_price = pair["buy_price"], pair["sell_price"]
        entry_date = buy_dt.date()
        exit_date = sell_dt.date()
        trade_return = (sell_price - buy_price) / buy_price

        sig_row = get_daily_signal(exit_date)
        exit_agent_signal = sig_row["daily_agent_signal"] if sig_row else None
        exit_news_title = sig_row["top_news_title"] if sig_row else None
        exit_rationale = get_rationale(sig_row["top_news_id"]) if sig_row and sig_row["top_news_id"] else None

        exit_idx = bar_lookup.get(exit_date)
        macd_exit_date, return_if_macd_exit = None, None

        if exit_idx is not None and exit_idx < len(dif_arr):
            dc_idx = find_death_cross(dif_arr, dea_arr, exit_idx)
            if dc_idx is not None:
                macd_exit_date = bars[dc_idx]["dt"].date()
                macd_exit_price = bars[dc_idx]["close"]
                return_if_macd_exit = (macd_exit_price - buy_price) / buy_price
            else:
                macd_exit_date = "no MACD exit within 1 year"

        profit_saved = trade_return - return_if_macd_exit if return_if_macd_exit is not None else None

        post_returns = {}
        for ndays in [1, 3, 5, 10, 20]:
            key = f"post_exit_{ndays}d_return"
            if exit_idx is not None and exit_idx + ndays < len(bars):
                post_returns[key] = (bars[exit_idx + ndays]["close"] - sell_price) / sell_price
            else:
                post_returns[key] = None

        row = {
            "trade_id": seq_id,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry_price": round(buy_price, 2),
            "exit_price": round(sell_price, 2),
            "trade_return": round(trade_return, 6),
            "exit_agent_signal": round(exit_agent_signal, 6) if exit_agent_signal is not None else None,
            "exit_news_title": exit_news_title,
            "exit_rationale": exit_rationale,
            "macd_exit_date": macd_exit_date,
            "return_if_macd_exit": round(return_if_macd_exit, 6) if return_if_macd_exit is not None else None,
            "profit_saved_vs_macd_exit": round(profit_saved, 6) if profit_saved is not None else None,
            **post_returns,
        }
        results.append(row)

    agent_db.close()

    csv_path = os.path.join(RESULTS_DIR, "audit_agent_exits.csv")
    fieldnames = [
        "trade_id", "entry_date", "exit_date", "entry_price", "exit_price",
        "trade_return", "exit_agent_signal", "exit_news_title",
        "exit_rationale", "macd_exit_date", "return_if_macd_exit",
        "profit_saved_vs_macd_exit",
        "post_exit_1d_return", "post_exit_3d_return", "post_exit_5d_return",
        "post_exit_10d_return", "post_exit_20d_return",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    wf(f"  Wrote {csv_path}")

    md_path = os.path.join(RESULTS_DIR, "audit_agent_exits.md")
    with open(md_path, "w") as f:
        f.write("# Audit: Agent Early-Exit Trades (either_safe, CATL 300750.SZSE)\n\n")

        saved = [r["profit_saved_vs_macd_exit"] for r in results
                 if r["profit_saved_vs_macd_exit"] is not None]
        n_saved = sum(1 for v in saved if v > 0)
        n_hurt = sum(1 for v in saved if v < 0)
        avg_saved = sum(saved) / len(saved) if saved else 0
        has_macd = sum(1 for r in results if isinstance(r["macd_exit_date"], Date))

        f.write(f"**Trades analyzed**: {len(results)} (MACD entry -> Agent exit only)\n\n")
        f.write(f"**Question: Did Agent exits save money vs waiting for MACD?**\n\n")
        if saved:
            f.write(f"- Agent exit saved money in **{n_saved}/{len(saved)}** trades\n")
            f.write(f"- Agent exit lost money in **{n_hurt}/{len(saved)}** trades\n")
            f.write(f"- Average profit saved vs MACD exit: **{avg_saved:+.2%}**\n")
            f.write(f"- MACD death cross occurred within 1 year in **{has_macd}/{len(results)}** cases\n\n")

        if avg_saved > 0:
            f.write("**Verdict**: On balance, Agent early exits **saved money** vs waiting for MACD death cross.\n\n")
        elif avg_saved < 0:
            f.write("**Verdict**: On balance, Agent early exits **cost money** -- waiting for MACD would have been better.\n\n")
        else:
            f.write("**Verdict**: Mixed or inconclusive.\n\n")

        f.write("## Trade Details\n\n")
        headers = ["ID", "Entry", "Exit", "EntryPr", "ExitPr", "Return",
                   "AgtSig", "MACD Exit", "MACD Ret", "Saved",
                   "+1d", "+3d", "+5d", "+10d", "+20d"]
        f.write("| " + " | ".join(headers) + " |\n")
        f.write("|" + "|".join(["---"] * len(headers)) + "|\n")

        for r in results:
            cols = [
                str(r["trade_id"]),
                str(r["entry_date"]), str(r["exit_date"]),
                f'{r["entry_price"]:.2f}', f'{r["exit_price"]:.2f}',
                f'{r["trade_return"]:+.2%}',
                f'{r["exit_agent_signal"]:.4f}' if r["exit_agent_signal"] is not None else "-",
                str(r["macd_exit_date"]) if r["macd_exit_date"] else "-",
                f'{r["return_if_macd_exit"]:+.2%}' if r["return_if_macd_exit"] is not None else "-",
                f'{r["profit_saved_vs_macd_exit"]:+.2%}' if r["profit_saved_vs_macd_exit"] is not None else "-",
                f'{r["post_exit_1d_return"]:+.2%}' if r["post_exit_1d_return"] is not None else "-",
                f'{r["post_exit_3d_return"]:+.2%}' if r["post_exit_3d_return"] is not None else "-",
                f'{r["post_exit_5d_return"]:+.2%}' if r["post_exit_5d_return"] is not None else "-",
                f'{r["post_exit_10d_return"]:+.2%}' if r["post_exit_10d_return"] is not None else "-",
                f'{r["post_exit_20d_return"]:+.2%}' if r["post_exit_20d_return"] is not None else "-",
            ]
            f.write("| " + " | ".join(cols) + " |\n")

        f.write("\n## Top News Titles for Agent Exits\n\n")
        for r in results:
            f.write(f"- **Trade {r['trade_id']}** ({r['exit_date']}): {r['exit_news_title'] or 'N/A'}\n")
            if r["exit_rationale"]:
                f.write(f"  - Rationale: {r['exit_rationale']}\n")

    wf(f"  Wrote {md_path}")


# ═══════════════════════════════════════════════════════════════════════
# Task 2 — Trading Cost Sensitivity
# ═══════════════════════════════════════════════════════════════════════

def task2_cost_sensitivity():
    wf("\n" + "=" * 70)
    wf("TASK 2: Trading Cost Sensitivity")
    wf("=" * 70)

    modes = ["either_safe", "macd_only"]
    rates = [0.0, 0.001, 0.0015, 0.002]
    csv_path = os.path.join(RESULTS_DIR, "cost_sensitivity.csv")
    md_path = os.path.join(RESULTS_DIR, "cost_sensitivity.md")

    fieldnames = ["strategy_name", "cost_rate", "total_return", "annual_return",
                  "sharpe_ratio", "max_ddpercent", "trade_count"]

    all_rows = []
    for mode in modes:
        setting = {**BASE_SETTING, "signal_mode": mode}
        for rate in rates:
            wf(f"  Running {mode} rate={rate} ...")
            engine, stats = run_backtest(setting, rate=rate)
            row = {
                "strategy_name": mode,
                "cost_rate": rate,
                "total_return": round(stats.get("total_return", 0), 2),
                "annual_return": round(stats.get("annual_return", 0), 2),
                "sharpe_ratio": round(stats.get("sharpe_ratio", 0), 4),
                "max_ddpercent": round(stats.get("max_ddpercent", 0), 2),
                "trade_count": stats.get("total_trade_count", 0),
            }
            all_rows.append(row)
            wf(f"    Return={row['total_return']}% Ann={row['annual_return']}% "
               f"Sharpe={row['sharpe_ratio']} MaxDD={row['max_ddpercent']}% "
               f"Trades={row['trade_count']}")

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)
    wf(f"  Wrote {csv_path}")

    with open(md_path, "w") as f:
        f.write("# Cost Sensitivity Analysis (CATL 300750.SZSE)\n\n")
        f.write("| Strategy | Cost Rate | Total Return | Annual Return | Sharpe | Max DD | Trades |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in all_rows:
            f.write(f"| {r['strategy_name']} | {r['cost_rate']:.3%} | "
                    f"{r['total_return']:.1f}% | {r['annual_return']:.1f}% | "
                    f"{r['sharpe_ratio']:.2f} | {r['max_ddpercent']:.1f}% | "
                    f"{r['trade_count']} |\n")
        f.write("\n## Notes\n\n")
        f.write("- either_safe: buy=(MACD golden OR Agent>=0.05) AND NOT Agent<=-0.05, sell=MACD death OR Agent<=-0.05\n")
        f.write("- macd_only: pure MACD golden/death cross\n")
        f.write("- Rates: 0% (ideal), 0.1% (standard), 0.15% (premium), 0.2% (high per-side)\n")
    wf(f"  Wrote {md_path}")


# ═══════════════════════════════════════════════════════════════════════
# Task 3 — MA Trend Filter
# ═══════════════════════════════════════════════════════════════════════

class MaFilterStrategy(MacdAgentStrategy):
    ma_period: int = 120
    parameters = MacdAgentStrategy.parameters + ["ma_period"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        from vnpy.trader.utility import ArrayManager
        needed = max(self.ma_period + 10, self.slow * 3, 100)
        self.am = ArrayManager(size=needed)

    def _ma_allows_buy(self, bar):
        ma = self.am.sma(self.ma_period)
        if ma is None or np.isnan(ma):
            return True
        return bar.close_price > ma

    def on_bar(self, bar):
        self.am.update_bar(bar)
        if not self.am.inited:
            return
        result = self.am.macd(self.fast, self.slow, self.signal_period)
        if result is None:
            return
        dif, dea, hist = result
        if dif is None or dea is None:
            return
        self.dif_val = float(dif)
        self.dea_val = float(dea)
        bar_date = bar.datetime.date()

        macd_golden = self._prev_dif <= self._prev_dea and dif > dea
        macd_death = self._prev_dif >= self._prev_dea and dif < dea
        agent_buy = self._agent_buy(bar_date)
        agent_sell = self._agent_sell(bar_date)

        base_buy = (macd_golden or agent_buy) and not agent_sell
        should_buy = base_buy and self._ma_allows_buy(bar)
        should_sell = macd_death or agent_sell

        if should_buy and self.pos == 0:
            self._last_entry_macd = macd_golden
            self._last_entry_agent = agent_buy
            target_val = self.init_capital * self.pos_ratio
            shares = int(target_val / bar.close_price / 100) * 100
            lots = shares // 100
            if lots > 0:
                self.buy(bar.close_price, lots)
        elif should_sell and self.pos > 0:
            entry_src = "both" if self._last_entry_macd and self._last_entry_agent else (
                "MACD" if self._last_entry_macd else "Agent")
            exit_src = "both" if macd_death and agent_sell else (
                "MACD" if macd_death else "Agent")
            self._trade_log.append({
                "entry_date": str(bar.datetime.date()),
                "entry_src": entry_src, "exit_src": exit_src,
            })
            self.sell(bar.close_price, abs(self.pos))

        self._prev_dif = dif
        self._prev_dea = dea


def task3_ma_filters():
    wf("\n" + "=" * 70)
    wf("TASK 3: Market Environment (MA Trend) Filters")
    wf("=" * 70)

    db = sqlite3.connect(DB_PATH)
    idx_rows = db.execute(
        "SELECT DISTINCT symbol, exchange FROM dbbardata "
        "WHERE symbol IN ('000300','000001','399300','000905','399006','399001')"
    ).fetchall()
    db.close()
    has_index = len(idx_rows) > 0
    wf(f"  Index data available: {has_index} ({idx_rows})")

    variants = [
        ("no_filter", MacdAgentStrategy, {**BASE_SETTING, "signal_mode": "either_safe"}),
        ("ma120_filter", MaFilterStrategy, {**BASE_SETTING, "signal_mode": "either_safe", "ma_period": 120}),
        ("ma200_filter", MaFilterStrategy, {**BASE_SETTING, "signal_mode": "either_safe", "ma_period": 200}),
    ]

    csv_path = os.path.join(RESULTS_DIR, "ma_filter_results.csv")
    md_path = os.path.join(RESULTS_DIR, "ma_filter_results.md")

    fieldnames = ["variant", "ma_period", "total_return", "annual_return",
                  "sharpe_ratio", "max_ddpercent", "trade_count", "end_balance"]
    for yr in range(2020, 2027):
        fieldnames.append(f"return_{yr}")

    all_rows = []
    for variant_name, strat_class, setting in variants:
        wf(f"  Running {variant_name} ...")
        engine, stats, daily_df = run_custom_backtest(strat_class, setting)
        annual = compute_annual_breakdown(daily_df)

        ma_period = setting.get("ma_period", "-")
        row = {
            "variant": variant_name,
            "ma_period": ma_period,
            "total_return": round(stats.get("total_return", 0), 2),
            "annual_return": round(stats.get("annual_return", 0), 2),
            "sharpe_ratio": round(stats.get("sharpe_ratio", 0), 4),
            "max_ddpercent": round(stats.get("max_ddpercent", 0), 2),
            "trade_count": stats.get("total_trade_count", 0),
            "end_balance": round(stats.get("end_balance", 0), 0),
        }
        for yr in range(2020, 2027):
            val = annual.get(yr)
            row[f"return_{yr}"] = round(val * 100, 2) if val is not None else None

        all_rows.append(row)
        wf(f"    Return={row['total_return']}% Ann={row['annual_return']}% "
           f"Sharpe={row['sharpe_ratio']} MaxDD={row['max_ddpercent']}% "
           f"Trades={row['trade_count']} Bal={row['end_balance']}")

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)
    wf(f"  Wrote {csv_path}")

    with open(md_path, "w") as f:
        f.write("# MA Trend Filter Results (either_safe, CATL 300750.SZSE)\n\n")
        f.write("**Filter**: Only allow BUY when `close > SMA(period)`. Sell unchanged.\n\n")

        f.write("## Summary\n\n")
        f.write("| Variant | MA | Total Return | Annual Return | Sharpe | Max DD | Trades | End Bal |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in all_rows:
            ma_str = f"SMA({r['ma_period']})" if r['ma_period'] != '-' else "-"
            f.write(f"| {r['variant']} | {ma_str} | {r['total_return']:.1f}% | "
                    f"{r['annual_return']:.1f}% | {r['sharpe_ratio']:.2f} | "
                    f"{r['max_ddpercent']:.1f}% | {r['trade_count']} | "
                    f"{r['end_balance']:.0f} |\n")

        f.write("\n## Annual Returns\n\n")
        f.write("| Variant | " + " | ".join(str(yr) for yr in range(2020, 2027)) + " |\n")
        f.write("|" + "|".join(["---"] * 8) + "|\n")
        for r in all_rows:
            vals = [r["variant"]] + [f"{r[f'return_{yr}']}%" if r[f'return_{yr}'] is not None else "-"
                                     for yr in range(2020, 2027)]
            f.write("| " + " | ".join(vals) + " |\n")

        f.write("\n## Notes\n\n")
        f.write("- MA filter blocks BUY when price is below MA. Sell unchanged.\n")
        f.write("- MA computed from bar data using SMA (no look-ahead bias).\n")
        if not has_index:
            f.write("- No stock index found in dbbardata -- index+MA filter variant skipped.\n")

    wf(f"  Wrote {md_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Comprehensive audit for either_safe MACD+Agent strategy")
    parser.add_argument("--vt-symbol", default="300750.SZSE", help="Trading symbol (default: 300750.SZSE)")
    parser.add_argument("--exchange", default="SZSE", help="Exchange (default: SZSE)")
    parser.add_argument("--db-path", default="~/.vntrader/agent_news.db", help="Agent news database path")
    args = parser.parse_args()

    VT_SYMBOL = args.vt_symbol
    parts = VT_SYMBOL.split(".")
    SYMBOL = parts[0]
    EXCHANGE = parts[1] if len(parts) > 1 else args.exchange
    AGENT_DB_PATH = str(Path(args.db_path).expanduser())
    RESULTS_DIR = str(Path(__file__).parent.parent / "results" / "v0.21" / SYMBOL / "audit")
    os.makedirs(RESULTS_DIR, exist_ok=True)

    wf("Starting audit_either_safe.py ...")
    task1_audit_agent_exits()
    task2_cost_sensitivity()
    task3_ma_filters()
    wf("\nAll tasks complete.")
