#!/usr/bin/env python
"""Trace MACD crosses vs agent signals on 寒武纪."""
import sys, json
from datetime import datetime, date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.tech_agent_strategy import TechAgentStrategy

# Collect MACD cross dates via a global/list hack
MACD_LOG = []

class LoggingStrategy(TechAgentStrategy):
    def on_bar(self, bar):
        self.am.update_bar(bar)
        if not self.am.inited: return
        ts = self._indicator.update(bar, self.am)
        dt = str(bar.datetime)[:10]
        if ts.buy_signal:
            MACD_LOG.append((dt, "GOLDEN"))
        if ts.sell_signal:
            MACD_LOG.append((dt, "DEATH"))

e = BacktestingEngine()
e.set_parameters(vt_symbol="688256.SSE", interval=Interval.DAILY,
    start=datetime(2020,7,20), end=datetime(2026,5,15),
    rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
setting = {"fast":12,"slow":26,"signal_period":9,"pos_ratio":0.5,"agent_threshold":0.05,
           "init_capital":1_000_000,"signal_mode":"tech_only","indicator_name":"macd","agent_db_path":""}
e.add_strategy(LoggingStrategy, setting)
e.load_data(); e.run_backtesting()

sigs = json.loads(open("backtests/results/v0.22/signals/688256_v0_22.json").read())
agent = {s["trading_date"]: s for s in sigs}

goldens = [m for m in MACD_LOG if m[1]=="GOLDEN"]
deaths = [m for m in MACD_LOG if m[1]=="DEATH"]
print(f"MACD golden crosses: {len(goldens)}, death crosses: {len(deaths)}")

blocked = [(dt, agent[dt]["daily_agent_signal"]) for dt,_ in goldens if dt in agent and agent[dt]["daily_direction"]=="negative"]
print(f"Golden crosses BLOCKED by agent negative: {len(blocked)}/{len(goldens)} ({100*len(blocked)/max(len(goldens),1):.1f}%)")
agent_neg = {s["trading_date"] for s in sigs if s["daily_direction"]=="negative"}
print(f"Agent negative days: {len(agent_neg)} ({100*len(agent_neg)/1540:.1f}% of total)")

# Show blocked golden crosses in date order
print(f"\nBlocked golden crosses (agent_sell prevents MACD buy):")
for dt, sig in sorted(blocked):
    print(f"  {dt} agent={sig:.4f}")

# Check: what happens immediately after blocked crosses?
print(f"\nAgent-only negative days (no MACD event, but would force sell):")
macd_dates = {m[0] for m in MACD_LOG}
solo_neg = sorted(agent_neg - macd_dates)[:15]
for dt in solo_neg:
    s = agent[dt]
    print(f"  {dt} signal={s['daily_agent_signal']:.4f} events={s.get('event_count','?')}")
