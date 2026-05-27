#!/usr/bin/env python
"""Full report with yearly breakout."""
import sys, json, sqlite3, tempfile, os
from datetime import datetime, date
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.tech_agent_strategy import TechAgentStrategy

STOCKS = {"600309.SSE":("万华化学",date(2020,1,1)),"600036.SSE":("招商银行",date(2020,1,1)),"688256.SSE":("寒武纪",date(2020,7,20))}
INDS = ["macd","ma_adx","bollinger","rsi"]
MODES = ["tech_only","tech_confirm_veto","tech_veto_only","agent_overlay","legacy_either_safe"]
BASE = {"fast":12,"slow":26,"signal_period":9,"pos_ratio":0.5,"agent_threshold":0.05,"init_capital":1_000_000}
SIGNAL_DIR = Path("backtests/results/v0.22/signals")

def make_db(sigs):
    fd,dbp = tempfile.mkstemp(suffix=".db"); os.close(fd)
    c = sqlite3.connect(dbp); c.execute("CREATE TABLE daily_agent_signal(entry_date TEXT,daily_agent_signal REAL,daily_direction TEXT,signal_version TEXT,agent_label TEXT,raw_daily_signal REAL,news_count INTEGER DEFAULT 0,event_count INTEGER DEFAULT 0,model_count INTEGER DEFAULT 0,mixed_intensity REAL DEFAULT 0.0,risk_penalty REAL DEFAULT 1.0,created_at TEXT)")
    for s in sigs: c.execute("INSERT INTO daily_agent_signal VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(s["trading_date"],s["daily_agent_signal"],s["daily_direction"],s.get("signal_version",""),s.get("agent_label",""),s.get("raw_daily_signal",0),s.get("news_count",0),s.get("event_count",0),s.get("model_count",0),s.get("mixed_intensity",0),s.get("risk_penalty",1.0),s.get("created_at","")))
    c.commit(); c.close(); return dbp

def backtest(vt, mode, ind, start_d, dbp=""):
    e = BacktestingEngine()
    e.set_parameters(vt_symbol=vt, interval=Interval.DAILY,start=datetime(start_d.year,start_d.month,start_d.day),end=datetime(2026,5,15),rate=0.0003,slippage=0.01,size=100,pricetick=0.01,capital=1_000_000)
    e.add_strategy(TechAgentStrategy,{**BASE,"signal_mode":mode,"indicator_name":ind,"agent_db_path":dbp})
    e.load_data(); e.run_backtesting()
    daily = e.calculate_result(); stats = e.calculate_statistics(daily,output=False)
    dlist = daily.to_dict("records") if hasattr(daily,"to_dict") else []
    ret,ann,dd,sr = stats.get("total_return",0),stats.get("annual_return",0),abs(stats.get("max_ddpercent",0)),stats.get("sharpe_ratio",0)
    cal = abs(ann)/max(dd,1e-6) if ann and dd else 0
    trades = e.get_all_trades()
    buys = len([t for t in trades if str(t.direction.value)=="Long"])
    td = [d for d in dlist if abs(float(d.get("net_pnl",0)))>1e-6]
    wr = sum(1 for d in td if float(d.get("net_pnl",0))>0)/max(len(td),1)*100
    ex = sum(1 for d in dlist if float(d.get("end_pos",0))>0)/max(len(dlist),1)*100
    daily_pnls = sorted([float(d.get("net_pnl",0)) for d in dlist], reverse=True)
    tp = sum(p for p in daily_pnls if p>0)+abs(sum(p for p in daily_pnls if p<0))+1e-6
    top3c = sum(daily_pnls[:3])/tp*100
    yearly = defaultdict(float)
    for i, d in enumerate(dlist):
        idx = daily.index[i] if hasattr(daily,'index') and i < len(daily.index) else None
        if idx is None: continue
        yr = str(idx)[:4]
        yearly[yr] += float(d.get("net_pnl",0))
    yrs_str = " ".join(f"{y}:{v/10000:+.0f}w" for y,v in sorted(yearly.items())[1:])
    return {"ret":ret,"dd":dd,"sr":sr,"cal":cal,"tc":buys,"wr":wr,"ex":ex,"top3":top3c,"yrs":yrs_str}

for vt,(name,sd) in STOCKS.items():
    code = vt.split(".")[0]
    sp = SIGNAL_DIR / f"{code}_v0_22.json"
    sigs = json.loads(open(sp).read())
    dbp = make_db(sigs)
    print(f"\n{name} ({vt})")
    for ind in INDS:
        tech = backtest(vt,"tech_only",ind,sd)
        print(f"  [{ind}]")
        print(f"  {'Mode':<22} {'Ret':>7} {'MaxDD':>7} {'Shp':>5} {'Cal':>5} {'Trd':>4} {'WR%':>4} {'Expo':>5} {'Top3%':>5} | Yearly PnL (万)")
        for mode in MODES:
            r = tech if mode=="tech_only" else backtest(vt,mode,ind,sd,dbp)
            print(f"  {mode:<22} {r['ret']:>6.1f}% {r['dd']:>6.1f}% {r['sr']:>4.2f} {r['cal']:>4.2f} {r['tc']:>4} {r['wr']:>3.0f}% {r['ex']:>4.0f}% {r['top3']:>4.0f}% | {r['yrs']}")
    os.unlink(dbp)
