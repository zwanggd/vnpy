"""
Comprehensive either_safe strategy analysis:
1. Threshold grid
2. Trading cost sensitivity
3. Annual breakdown
4. Per-trade attribution (entry/exit source)
"""
import sys; sys.path.insert(0, '.')
from datetime import datetime
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.macd_agent_strategy import MacdAgentStrategy

base = {"fast": 12, "slow": 26, "signal_period": 9, "pos_ratio": 0.5, "agent_threshold": 0.05, "init_capital": 1_000_000, "signal_mode": "either_safe"}

def run(params):
    engine = BacktestingEngine()
    engine.set_parameters(vt_symbol="300750.SZSE", interval=Interval.DAILY, start=datetime(2020,1,1), end=datetime(2026,5,15), rate=params.get("rate",0.0003), slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    s = {**base, **params}
    engine.add_strategy(MacdAgentStrategy, s)
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    stats = engine.calculate_statistics(daily, output=False)
    return stats, daily

# ── 1. Threshold Grid ──
print("=" * 90)
print("1. THRESHOLD GRID (either_safe, rate=0.03%)")
print(f"{'Threshold':<12} {'Return':>8} {'Annual':>8} {'Sharpe':>7} {'MaxDD':>7} {'Trades':>7} {'End Bal':>12}")
print("-" * 70)
for t in [0.03, 0.05, 0.08, 0.10, 0.15]:
    s, _ = run({"agent_threshold": t})
    print(f"{t:<12.2f} {s['total_return']:>7.1f}% {s['annual_return']:>7.1f}% {s['sharpe_ratio']:>6.2f} {s['max_ddpercent']:>6.1f}% {s['total_trade_count']:>7} {s['end_balance']:>12.0f}")

# ── 2. Trading Cost ──
print("\n" + "=" * 90)
print("2. COST SENSITIVITY (either_safe, threshold=0.05)")
print(f"{'Rate':<12} {'Return':>8} {'Annual':>8} {'Sharpe':>7} {'MaxDD':>7} {'Trades':>7} {'End Bal':>12}")
print("-" * 70)
for r in [0, 0.001, 0.0015]:
    s, _ = run({"rate": r})
    print(f"{r*100:<11.1f}% {s['total_return']:>7.1f}% {s['annual_return']:>7.1f}% {s['sharpe_ratio']:>6.2f} {s['max_ddpercent']:>6.1f}% {s['total_trade_count']:>7} {s['end_balance']:>12.0f}")

# ── 3. Annual Breakdown ──
print("\n" + "=" * 90)
print("3. ANNUAL BREAKDOWN (either_safe, threshold=0.05, rate=0.03%)")
_, daily = run({"agent_threshold": 0.05})
daily["year"] = daily.index.year
for yr in sorted(daily["year"].unique()):
    dy = daily[daily["year"] == yr]
    ret = (dy["balance"].iloc[-1] / dy["balance"].iloc[0] - 1) * 100 if len(dy) > 1 else 0
    dd = (dy["balance"] / dy["balance"].cummax() - 1).min() * 100 if len(dy) > 1 else 0
    trades = dy["trade_count"].sum() if "trade_count" in dy.columns else 0
    print(f"  {yr}: return={ret:>7.1f}%  maxdd={dd:>6.1f}%  trades={int(trades)}")
print()

# ── 4. Per-Trade Attribution ──
print("=" * 90)
print("4. PER-TRADE ATTRIBUTION (either_safe)")
import sqlite3, json
from pathlib import Path
import pandas as pd
import numpy as np

AGENT_DB = Path.home() / ".vntrader" / "agent_news.db"
PRICE_DB = Path.home() / ".vntrader" / "database.db"

# Load agent signals and price bars
adb = sqlite3.connect(str(AGENT_DB))
asigs = {}
for row in adb.execute("SELECT entry_date, daily_agent_signal FROM daily_agent_signal"):
    d = row[0][:10] if isinstance(row[0], str) else str(row[0])[:10]
    asigs[d] = row[1] if row[1] else 0
adb.close()

pdb = sqlite3.connect(str(PRICE_DB))
bars = []
for row in pdb.execute("""SELECT datetime, close_price FROM dbbardata 
    WHERE symbol='300750' AND exchange='SZSE' AND interval='d' 
    AND datetime >= '2020-01-01' AND datetime <= '2026-05-15' ORDER BY datetime"""):
    bars.append({"date": row[0][:10] if isinstance(row[0], str) else str(row[0])[:10], "close": row[1]})
pdb.close()

# Simulate MACD + agent signals
fast, slow, sig = 12, 26, 9
threshold = 0.05

prices = [b["close"] for b in bars]
ema_fast = pd.Series(prices).ewm(span=fast).mean()
ema_slow = pd.Series(prices).ewm(span=slow).mean()
dif = ema_fast - ema_slow
dea = dif.ewm(span=sig).mean()

pos = 0
entry_price = 0
entry_date = ""
trades = []
entry_macd = entry_agent = False
exit_macd = exit_agent = False

for i in range(50, len(bars)):  # skip warmup
    d = bars[i]["date"]
    close = bars[i]["close"]

    # MACD signals
    macd_golden = dif.iloc[i-1] <= dea.iloc[i-1] and dif.iloc[i] > dea.iloc[i]
    macd_death = dif.iloc[i-1] >= dea.iloc[i-1] and dif.iloc[i] < dea.iloc[i]

    # Agent signals
    a = asigs.get(d, 0)
    agent_buy = a >= threshold
    agent_sell = a <= -threshold

    # either_safe logic
    should_buy = (macd_golden or agent_buy) and not agent_sell
    should_sell = macd_death or agent_sell

    if should_buy and pos == 0:
        pos = 1
        entry_price = close
        entry_date = d
        entry_macd = macd_golden
        entry_agent = agent_buy
    elif should_sell and pos > 0:
        ret = (close - entry_price) / entry_price
        exit_macd = macd_death
        exit_agent = agent_sell
        # Classify entry source
        if entry_macd and entry_agent:
            entry_src = "both"
        elif entry_macd:
            entry_src = "MACD"
        else:
            entry_src = "Agent"
        # Classify exit source
        if exit_macd and exit_agent:
            exit_src = "both"
        elif exit_macd:
            exit_src = "MACD"
        else:
            exit_src = "Agent"
        trades.append({"entry": entry_date, "exit": d, "ret": ret, "entry_src": entry_src, "exit_src": exit_src})
        pos = 0

# Summarize by source
print(f"Total trades: {len(trades)}")
print()
for src in ["MACD", "Agent", "both"]:
    e_trades = [t for t in trades if t["entry_src"] == src]
    if e_trades:
        avg_r = np.mean([t["ret"] for t in e_trades])
        win_r = sum(1 for t in e_trades if t["ret"] > 0) / len(e_trades)
        print(f"  Entry by {src:<6}: {len(e_trades):>3} trades, avg_ret={avg_r:>7.2%}, win_rate={win_r:>5.1%}")

print()
for src in ["MACD", "Agent", "both"]:
    x_trades = [t for t in trades if t["exit_src"] == src]
    if x_trades:
        avg_r = np.mean([t["ret"] for t in x_trades])
        print(f"  Exit  by {src:<6}: {len(x_trades):>3} trades, avg_ret_after_exit={avg_r:>7.2%}")

# Total contribution by entry/exit combo
print()
print("Entry × Exit matrix:")
for entry_src in ["MACD", "Agent", "both"]:
    for exit_src in ["MACD", "Agent", "both"]:
        combo = [t for t in trades if t["entry_src"] == entry_src and t["exit_src"] == exit_src]
        if combo:
            avg_r = np.mean([t["ret"] for t in combo])
            print(f"  {entry_src:>6} → {exit_src:<6}: {len(combo):>3} trades, avg_ret={avg_r:>7.2%}")

# Total P&L by source
print()
print("Cumulative P&L by entry source:")
for src in ["MACD", "Agent", "both"]:
    total = sum(t["ret"] for t in trades if t["entry_src"] == src)
    print(f"  {src:<6}: {total:>8.2%}")
