#!/usr/bin/env python
"""v0.2 vs v0.22 backtest comparison with agent intervention tracing."""
from __future__ import annotations
import json, math, sqlite3, sys, tempfile, os
from datetime import datetime, date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.macd_agent_strategy import MacdAgentStrategy

STOCKS = {
    "600309": ("600309.SSE", "万华化学", "周期股", date(2020, 1, 1)),
    "688256": ("688256.SSE", "寒武纪", "概念股", date(2020, 7, 20)),
    "600036": ("600036.SSE", "招商银行", "银行股", date(2020, 1, 1)),
}
END_DATE = date(2026, 5, 15)
SIGNAL_DIR = Path("backtests/results/v0.22/signals")
MACD_PARAMS = {"fast": 12, "slow": 26, "signal_period": 9,
               "pos_ratio": 0.5, "agent_threshold": 0.05, "init_capital": 1_000_000}


def make_signal_db(signals):
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sig_")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE daily_agent_signal(
        entry_date TEXT, daily_agent_signal REAL, daily_direction TEXT,
        signal_version TEXT, agent_label TEXT,
        raw_daily_signal REAL, news_count INTEGER DEFAULT 0,
        event_count INTEGER DEFAULT 0, model_count INTEGER DEFAULT 0,
        mixed_intensity REAL DEFAULT 0.0, risk_penalty REAL DEFAULT 1.0,
        created_at TEXT)""")
    for s in signals:
        conn.execute("INSERT INTO daily_agent_signal VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            s.get("trading_date", ""), s.get("daily_agent_signal", 0),
            s.get("daily_direction", "neutral"),
            s.get("signal_version", ""),
            s.get("agent_label", ""),
            s.get("raw_daily_signal", 0),
            s.get("news_count", 0), s.get("event_count", 0),
            s.get("model_count", 0),
            s.get("mixed_intensity", 0), s.get("risk_penalty", 1.0),
            s.get("created_at", ""),
        ))
    conn.commit(); conn.close()
    return path


def backtest(vt_symbol, db_path, start, mode="either_safe"):
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start.year, start.month, start.day),
        end=datetime(END_DATE.year, END_DATE.month, END_DATE.day),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    setting = {**MACD_PARAMS, "signal_mode": mode, "agent_db_path": db_path}
    engine.add_strategy(MacdAgentStrategy, setting)
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    stats = engine.calculate_statistics(daily, output=False)

    all_trades = engine.get_all_trades()
    buy_dates = sorted(set(str(t.datetime)[:10] for t in all_trades
                          if str(t.direction.value) in ('Long', 'LONG')))
    sell_dates = sorted(set(str(t.datetime)[:10] for t in all_trades
                           if str(t.direction.value) in ('Short', 'SHORT')))
    trade_count = len(buy_dates)

    avg_hold = 0.0
    if buy_dates and sell_dates:
        holds = []
        for bd in buy_dates:
            later_sells = [sd for sd in sell_dates if sd > bd]
            if later_sells:
                holds.append((date.fromisoformat(later_sells[0]) - date.fromisoformat(bd)).days)
        if holds:
            avg_hold = sum(holds) / len(holds)

    daily_list = daily.to_dict("records") if hasattr(daily, "to_dict") else []
    wins = sum(1 for d in daily_list if float(d.get("net_pnl", 0)) > 0)
    total_t = max(sum(1 for d in daily_list if abs(float(d.get("net_pnl", 0))) > 1e-6), 1)
    wr = wins / total_t * 100

    return {
        "total_return": stats.get("total_return", 0),
        "annual_return": stats.get("annual_return", 0),
        "max_ddpercent": abs(stats.get("max_ddpercent", 0)),
        "sharpe": stats.get("sharpe_ratio", 0),
        "calmar": abs(stats.get("annual_return", 0)) / max(abs(stats.get("max_ddpercent", 0)), 1e-6),
        "win_rate": round(wr, 1),
        "trade_count": trade_count,
        "avg_hold_days": round(avg_hold, 1),
        "buy_dates": buy_dates,
        "sell_dates": sell_dates,
    }


def trace_intervention(agent_result, macd_result):
    a_buy = set(agent_result["buy_dates"])
    a_sell = set(agent_result["sell_dates"])
    m_buy = set(macd_result["buy_dates"])
    m_sell = set(macd_result["sell_dates"])
    return {
        "early_buy": len(a_buy - m_buy),
        "early_sell": len(a_sell - m_sell),
        "blocked_buy": len(m_buy - a_buy),
        "blocked_sell": len(m_sell - a_sell),
    }


def main():
    hdr = f"{'Stock':<10} {'Ver':<5} {'Return':>8} {'AnnRet':>8} {'MaxDD':>7} "
    hdr += f"{'Sharpe':>7} {'Calmar':>7} {'Win%':>6} {'Trades':>7} {'HoldD':>6} {'Δ MACD':>8}"
    print(hdr)
    print("-" * 92)

    for code, (symbol, name, stype, start) in STOCKS.items():
        v2p = SIGNAL_DIR / f"{code}_v0_2.json"
        v22p = SIGNAL_DIR / f"{code}_v0_22.json"
        if not v2p.exists() or not v22p.exists():
            continue

        v2_data = json.loads(v2p.read_text())
        v22_data = json.loads(v22p.read_text())
        db2 = make_signal_db(v2_data)
        db22 = make_signal_db(v22_data)

        m = backtest(symbol, "", start, "macd_only")
        r2 = backtest(symbol, db2, start)
        r22 = backtest(symbol, db22, start)

        ex2 = r2["total_return"] - m["total_return"]
        ex22 = r22["total_return"] - m["total_return"]

        ti2 = trace_intervention(r2, m)
        ti22 = trace_intervention(r22, m)

        def fmt(r, label, ver):
            print(f"{label:<10} {ver:<5} {r['total_return']:>7.1f}% {r['annual_return']:>7.1f}% "
                  f"{r['max_ddpercent']:>6.1f}% {r['sharpe']:>6.2f} {r['calmar']:>6.2f} "
                  f"{r['win_rate']:>5.1f}% {r['trade_count']:>6} {r['avg_hold_days']:>5.1f}d "
                  f"{'':>8}")

        fmt(m, name, "MACD")
        fmt(r2, "", "v0.2")
        fmt(r22, "", "v0.22")

        print(f"{'':<10} {'':<5} {'':>8} {'':>8} {'':>7} {'':>7} {'':>7} {'':>6} {'':>7} {'':>6} "
              f"{ex22-ex2:>+7.1f}% Δv22-v0.2")

        print(f"  Agent v0.2:  buy={ti2['early_buy']}+{ti2['blocked_buy']}blocked "
              f"sell={ti2['early_sell']}+{ti2['blocked_sell']}blocked")
        print(f"  Agent v0.22: buy={ti22['early_buy']}+{ti22['blocked_buy']}blocked "
              f"sell={ti22['early_sell']}+{ti22['blocked_sell']}blocked")
        print()

        for p in [db2, db22]:
            try: os.unlink(p)
            except: pass

    print("Done.")


if __name__ == "__main__":
    main()
