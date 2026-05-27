#!/usr/bin/env python
"""Analyze agent signal timing vs price action on 寒武纪."""
import sys, json
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.tech_agent_strategy import TechAgentStrategy

PRICES = []

class Collector(TechAgentStrategy):
    def on_bar(self, bar):
        PRICES.append((str(bar.datetime)[:10], float(bar.close_price)))

e = BacktestingEngine()
e.set_parameters(vt_symbol="688256.SSE", interval=Interval.DAILY,
    start=datetime(2020,7,20), end=datetime(2026,5,15),
    rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
s = {"fast":12,"slow":26,"signal_period":9,"pos_ratio":0.5,"agent_threshold":0.05,
     "init_capital":1_000_000,"signal_mode":"tech_only","indicator_name":"macd","agent_db_path":""}
e.add_strategy(Collector, s); e.load_data(); e.run_backtesting()
prices = dict(PRICES)
dates = sorted(prices.keys())

sigs = json.loads(open("backtests/results/v0.22/signals/688256_v0_22.json").read())
neg_dates = sorted([s["trading_date"] for s in sigs if s["daily_direction"]=="negative"])
pos_dates = sorted([s["trading_date"] for s in sigs if s["daily_direction"]=="positive"])

def fwd(dt, days):
    if dt not in dates: return None
    i = dates.index(dt)
    if i+days >= len(dates): return None
    return (prices[dates[i+days]]-prices[dt])/prices[dt]*100

for label, dlist in [("NEGATIVE", neg_dates), ("POSITIVE", pos_dates), ("ALL", dates)]:
    print(f"\n{label} days — forward returns:")
    for h in [1,3,5,10,20]:
        rets = [r for dt in dlist[:-h] if (r:=fwd(dt,h)) is not None]
        if not rets: continue
        avg = sum(rets)/len(rets)
        wr = sum(1 for r in rets if r>0)/len(rets)*100
        print(f"  T+{h:>2}: avg={avg:+.2f}% wr={wr:.0f}% n={len(rets)}")

# Check: what happens if strategy buys at positive signal and holds until next negative?
print(f"\nAgent signal round-trips (positive→negative):")
pos_idx = 0
trips = []
for nd in neg_dates:
    while pos_idx < len(pos_dates) and pos_dates[pos_idx] <= nd:
        pos_idx += 1
    if pos_idx == 0: continue
    entry = pos_dates[pos_idx-1]
    if entry > nd: continue
    if entry not in prices or nd not in prices: continue
    r = (prices[nd]-prices[entry])/prices[entry]*100
    trips.append(r)
if trips:
    avg = sum(trips)/len(trips)
    wr = sum(1 for r in trips if r>0)/len(trips)*100
    print(f"  {len(trips)} trips, avg={avg:+.1f}%, win_rate={wr:.0f}%")
    print(f"  Best: {max(trips):+.1f}%, Worst: {min(trips):+.1f}%")
