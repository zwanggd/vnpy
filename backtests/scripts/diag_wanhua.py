#!/usr/bin/env python
"""Diagnose why 万华化学 agent signals decayed."""
import sys, json
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
from datetime import datetime
from collections import defaultdict
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.tech_agent_strategy import TechAgentStrategy

sigs = json.loads(open("backtests/results/v0.22/signals/600309_v0_22.json").read())
by_year = defaultdict(lambda: {"positive":0,"negative":0,"neutral":0,"events":0,"total_sig":0})
for s in sigs:
    yr = s["trading_date"][:4]
    by_year[yr][s["daily_direction"]] += 1
    by_year[yr]["events"] += s.get("event_count",0)
    by_year[yr]["total_sig"] += s["daily_agent_signal"]

print("Agent Signal Evolution by Year:")
print(f"{'Year':<8} {'Pos':>5} {'Neg':>5} {'Neu':>5} {'Neg%':>5} {'Events/d':>8} {'AvgDir':>7}")
for yr in sorted(by_year)[1:]:
    d = by_year[yr]
    t = d["positive"]+d["negative"]+d["neutral"]
    neg_pct = d["negative"]/t*100 if t else 0
    avg = d["total_sig"]/t if t else 0
    ev_d = d["events"]/t if t else 0
    print(f"{yr:<8} {d['positive']:>5} {d['negative']:>5} {d['neutral']:>5} {neg_pct:>4.0f}% {ev_d:>7.1f} {avg:>+6.3f}")

# Price data
PRICES = []
class PC(TechAgentStrategy):
    def on_bar(self, bar): PRICES.append((str(bar.datetime)[:10], float(bar.close_price)))

e = BacktestingEngine()
e.set_parameters(vt_symbol="600309.SSE",interval=Interval.DAILY,start=datetime(2020,1,1),end=datetime(2026,5,15),rate=0.0003,slippage=0.01,size=100,pricetick=0.01,capital=1_000_000)
e.add_strategy(PC,{"fast":12,"slow":26,"signal_period":9,"pos_ratio":0.5,"agent_threshold":0.05,"init_capital":1_000_000,"signal_mode":"tech_only","indicator_name":"macd","agent_db_path":""})
e.load_data(); e.run_backtesting()
prices = dict(PRICES)
dates = sorted(prices.keys())

print("\nSignal Direction Quality by Year (forward return of agent signals):")
print(f"{'Year':<8} {'NegT+5':>8} {'NegT+20':>8} {'PosT+5':>8} {'PosT+20':>8} {'PriceChg':>8}")
for yr in sorted(by_year)[1:]:
    y_neg = [s["trading_date"] for s in sigs if s["trading_date"].startswith(yr) and s["daily_direction"]=="negative"]
    y_pos = [s["trading_date"] for s in sigs if s["trading_date"].startswith(yr) and s["daily_direction"]=="positive"]
    def fwd(dt_list, days):
        rets = []
        for dt in dt_list:
            if dt not in dates: continue
            i = dates.index(dt)
            if i+days >= len(dates): continue
            rets.append((prices[dates[i+days]]-prices[dt])/prices[dt]*100)
        return sum(rets)/len(rets) if rets else 0
    n5 = fwd(y_neg,5); n20 = fwd(y_neg,20)
    p5 = fwd(y_pos,5); p20 = fwd(y_pos,20)
    yr_start = next((dt for dt in dates if dt[:4]==yr), None)
    yr_end = next((dt for dt in reversed(dates) if dt[:4]==yr), None)
    chg = (prices[yr_end]-prices[yr_start])/prices[yr_start]*100 if yr_start and yr_end else 0
    print(f"{yr:<8} {n5:>+7.1f}% {n20:>+7.1f}% {p5:>+7.1f}% {p20:>+7.1f}% {chg:>+7.1f}%")

# Price volatility
print("\nYearly Price Stats:")
for yr in sorted(by_year)[1:]:
    yr_prices = [prices[dt] for dt in dates if dt[:4]==yr]
    if len(yr_prices) < 2: continue
    rets = [(yr_prices[i]-yr_prices[i-1])/yr_prices[i-1]*100 for i in range(1,len(yr_prices))]
    import statistics
    avg_r = statistics.mean(rets)
    std_r = statistics.stdev(rets)
    print(f"  {yr}: avg_daily={avg_r:+.2f}% std={std_r:.2f}% range={min(yr_prices):.0f}-{max(yr_prices):.0f}")
