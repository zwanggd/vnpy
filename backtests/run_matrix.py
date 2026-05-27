#!/usr/bin/env python
"""Technical × Agent Matrix Runner — Phases 1-2.

Runs backtest matrix: stocks × indicators × agent_versions × signal_modes.
Outputs: backtests/results/matrix/summary_matrix.csv

Usage:
    conda run -n vnpy43 python backtests/run_matrix.py --phase 1
    conda run -n vnpy43 python backtests/run_matrix.py --phase 2
"""
from __future__ import annotations
import argparse, csv, json, sqlite3, sys, tempfile, os
from collections import OrderedDict
from datetime import datetime, date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.tech_agent_strategy import TechAgentStrategy

STOCKS = OrderedDict([
    ("600309.SSE", ("万华化学", "周期股", date(2020, 1, 1))),
    ("600036.SSE", ("招商银行", "银行/低波", date(2020, 1, 1))),
    ("688256.SSE", ("寒武纪", "概念股", date(2020, 7, 20))),
])
END_DATE = date(2026, 5, 15)
SIGNAL_DIR = Path("backtests/results/v0.22/signals")
OUTPUT_DIR = Path("backtests/results/matrix")
BASE_SETTING = {
    "fast": 12, "slow": 26, "signal_period": 9,
    "pos_ratio": 0.5, "agent_threshold": 0.05, "init_capital": 1_000_000,
}

INDICATORS = ["macd", "ma_adx", "donchian", "bollinger", "rsi"]
COMBO_INDICATORS = ["macd_adx", "donchian_atr", "bollinger_ma"]
AGENT_VERSIONS = ["v0.2", "v0.22"]
SIGNAL_MODES = ["tech_confirm_veto", "tech_veto_only", "agent_overlay", "legacy_either_safe"]


def make_signal_db(signals, version):
    fd, path = tempfile.mkstemp(suffix=".db", prefix=f"sig_{version}_")
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
            s.get("signal_version", version),
            s.get("agent_label", version),
            s.get("raw_daily_signal", 0),
            s.get("news_count", 0), s.get("event_count", 0),
            s.get("model_count", 0),
            s.get("mixed_intensity", 0), s.get("risk_penalty", 1.0),
            s.get("created_at", ""),
        ))
    conn.commit(); conn.close()
    return path


def run_tech_only(vt_symbol, indicator_name, start_date):
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start_date.year, start_date.month, start_date.day),
        end=datetime(END_DATE.year, END_DATE.month, END_DATE.day),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    setting = {**BASE_SETTING, "signal_mode": "tech_only",
               "indicator_name": indicator_name, "agent_db_path": ""}
    engine.add_strategy(TechAgentStrategy, setting)
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    stats = engine.calculate_statistics(daily, output=False)
    trades = engine.get_all_trades()
    buy_dates = len({str(t.datetime)[:10] for t in trades if str(t.direction.value) == 'Long'})
    return _extract_stats(stats, buy_dates)


def run_agent_backtest(vt_symbol, indicator_name, agent_version, signal_mode, start_date, signals):
    db_path = make_signal_db(signals, agent_version)
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start_date.year, start_date.month, start_date.day),
        end=datetime(END_DATE.year, END_DATE.month, END_DATE.day),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    setting = {**BASE_SETTING, "signal_mode": signal_mode,
               "indicator_name": indicator_name, "agent_db_path": db_path}
    engine.add_strategy(TechAgentStrategy, setting)
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    stats = engine.calculate_statistics(daily, output=False)
    trades = engine.get_all_trades()
    buy_dates = len({str(t.datetime)[:10] for t in trades if str(t.direction.value) == 'Long'})
    try: os.unlink(db_path)
    except: pass
    return _extract_stats(stats, buy_dates)


def compute_buy_hold(vt_symbol, start_date):
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start_date.year, start_date.month, start_date.day),
        end=datetime(END_DATE.year, END_DATE.month, END_DATE.day),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    engine.load_data()
    bars = engine.history_data
    if not bars:
        return {}
    first_close = float(bars[0].close_price)
    last_close = float(bars[-1].close_price)
    total_return = (last_close - first_close) / first_close * 100
    days = len(bars)
    annual_return = ((1 + total_return/100) ** (240/max(days, 1)) - 1) * 100
    return {
        "total_return": round(total_return, 2),
        "annual_return": round(annual_return, 2),
        "max_ddpercent": 0, "sharpe_ratio": 0, "calmar": 0,
        "trade_count": 1, "win_rate": 0, "avg_hold_days": 0,
    }


def _extract_stats(stats, trade_count):
    ann = stats.get("annual_return", 0)
    dd = abs(stats.get("max_ddpercent", 0))
    return {
        "total_return": round(stats.get("total_return", 0), 2),
        "annual_return": round(ann, 2),
        "max_ddpercent": round(dd, 2),
        "sharpe_ratio": round(stats.get("sharpe_ratio", 0), 3),
        "calmar": round(abs(ann) / max(dd, 1e-6), 2),
        "trade_count": trade_count,
        "win_rate": 0,
        "avg_hold_days": 0,
    }


def write_csv(rows, filepath):
    fieldnames = [
        "vt_symbol", "stock_name", "stock_type", "strategy_name", "strategy_family",
        "technical_indicator", "agent_version", "fusion_mode",
        "total_return", "annual_return", "max_drawdown", "sharpe", "calmar",
        "trade_count", "win_rate", "avg_holding_days",
    ]
    with open(filepath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def run_phase1():
    rows = []
    for vt_symbol, (name, stype, start) in STOCKS.items():
        code = vt_symbol.split(".")[0]
        print(f"\n{name} ({vt_symbol}) — {stype}")

        bh = compute_buy_hold(vt_symbol, start)
        rows.append({**bh, "vt_symbol": vt_symbol, "stock_name": name, "stock_type": stype,
                     "strategy_name": "buy_and_hold", "strategy_family": "buy_and_hold",
                     "technical_indicator": "", "agent_version": "", "fusion_mode": ""})
        print(f"  buy_and_hold: return={bh.get('total_return','?'):.1f}%")

        for ind in INDICATORS:
            r = run_tech_only(vt_symbol, ind, start)
            rows.append({**r, "vt_symbol": vt_symbol, "stock_name": name, "stock_type": stype,
                         "strategy_name": f"{ind}_only", "strategy_family": "tech_only",
                         "technical_indicator": ind, "agent_version": "", "fusion_mode": ""})
            print(f"  {ind}_only: return={r['total_return']:.1f}% maxDD={r['max_ddpercent']:.1f}% sharpe={r['sharpe_ratio']:.2f} trades={r['trade_count']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUTPUT_DIR / "summary_matrix_phase1.csv"
    write_csv(rows, p)
    print(f"\nSaved: {p} ({len(rows)} rows)")


def run_phase2():
    rows = []
    for vt_symbol, (name, stype, start) in STOCKS.items():
        code = vt_symbol.split(".")[0]
        print(f"\n{name} ({vt_symbol}) — {stype}")

        for ind in INDICATORS:
            tech_only = run_tech_only(vt_symbol, ind, start)
            print(f"  {ind}_only: return={tech_only['total_return']:.1f}% maxDD={tech_only['max_ddpercent']:.1f}%")

            for ver in AGENT_VERSIONS:
                sig_filename = f"{code}_{ver.replace('.','_')}.json"
                sig_file = SIGNAL_DIR / sig_filename
                if not sig_file.exists():
                    print(f"    SKIP {ver}: no signal file ({sig_filename})")
                    continue
                signals = json.loads(sig_file.read_text())

                for mode in SIGNAL_MODES:
                    r = run_agent_backtest(vt_symbol, ind, ver, mode, start, signals)
                    delta = round(r["total_return"] - tech_only["total_return"], 2)
                    rows.append({**r, "vt_symbol": vt_symbol, "stock_name": name, "stock_type": stype,
                                 "strategy_name": f"{ind}_{ver}_{mode}",
                                 "strategy_family": "tech_agent",
                                 "technical_indicator": ind, "agent_version": ver, "fusion_mode": mode})
                    print(f"    {ver}_{mode}: return={r['total_return']:.1f}% (delta={delta:+.1f}%) maxDD={r['max_ddpercent']:.1f}%")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUTPUT_DIR / "summary_matrix_phase2.csv"
    write_csv(rows, p)
    print(f"\nSaved: {p} ({len(rows)} rows)")


def run_phase3():
    rows = []
    for vt_symbol, (name, stype, start) in STOCKS.items():
        code = vt_symbol.split(".")[0]
        print(f"\n{name} ({vt_symbol}) — {stype}")

        for ind in COMBO_INDICATORS:
            tech_only = run_tech_only(vt_symbol, ind, start)
            print(f"  {ind}_only: return={tech_only['total_return']:.1f}% maxDD={tech_only['max_ddpercent']:.1f}%")

            sig_file_22 = SIGNAL_DIR / f"{code}_v0_22.json"
            if not sig_file_22.exists():
                print(f"    SKIP: no v0.22 signal file")
                continue
            signals = json.loads(sig_file_22.read_text())

            for mode in SIGNAL_MODES:
                r = run_agent_backtest(vt_symbol, ind, "v0.22", mode, start, signals)
                delta = round(r["total_return"] - tech_only["total_return"], 2)
                rows.append({**r, "vt_symbol": vt_symbol, "stock_name": name, "stock_type": stype,
                             "strategy_name": f"{ind}_v022_{mode}",
                             "strategy_family": "combo_agent",
                             "technical_indicator": ind, "agent_version": "v0.22", "fusion_mode": mode})
                print(f"    v0.22_{mode}: return={r['total_return']:.1f}% (delta={delta:+.1f}%) maxDD={r['max_ddpercent']:.1f}%")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUTPUT_DIR / "summary_matrix_phase3.csv"
    write_csv(rows, p)
    print(f"\nSaved: {p} ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, required=True, choices=[1, 2, 3])
    args = ap.parse_args()
    if args.phase == 1:
        run_phase1()
    elif args.phase == 2:
        run_phase2()
    elif args.phase == 3:
        run_phase3()


if __name__ == "__main__":
    main()
