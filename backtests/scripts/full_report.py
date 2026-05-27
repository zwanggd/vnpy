#!/usr/bin/env python
"""Full metrics + trade attribution + year stability for all clean modes."""
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

def make_db(sigs):
    fd,dbp = tempfile.mkstemp(suffix=".db"); os.close(fd)
    c = sqlite3.connect(dbp)
    c.execute("CREATE TABLE daily_agent_signal(entry_date TEXT,daily_agent_signal REAL,daily_direction TEXT,signal_version TEXT,agent_label TEXT,raw_daily_signal REAL,news_count INTEGER DEFAULT 0,event_count INTEGER DEFAULT 0,model_count INTEGER DEFAULT 0,mixed_intensity REAL DEFAULT 0.0,risk_penalty REAL DEFAULT 1.0,created_at TEXT)")
    for s in sigs: c.execute("INSERT INTO daily_agent_signal VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(s["trading_date"],s["daily_agent_signal"],s["daily_direction"],s.get("signal_version",""),s.get("agent_label",""),s.get("raw_daily_signal",0),s.get("news_count",0),s.get("event_count",0),s.get("model_count",0),s.get("mixed_intensity",0),s.get("risk_penalty",1.0),s.get("created_at","")))
    c.commit(); c.close()
    return dbp

def backtest(vt, mode, ind, start_d, dbp=""):
    e = BacktestingEngine()
    e.set_parameters(vt_symbol=vt, interval=Interval.DAILY,
        start=datetime(start_d.year,start_d.month,start_d.day), end=datetime(2026,5,15),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    s = {**BASE,"signal_mode":mode,"indicator_name":ind,"agent_db_path":dbp}
    e.add_strategy(TechAgentStrategy, s); e.load_data(); e.run_backtesting()
    daily = e.calculate_result()
    stats = e.calculate_statistics(daily, output=False)
    trades = e.get_all_trades()
    dlist = daily.to_dict("records") if hasattr(daily,"to_dict") else []

    ret = stats.get("total_return",0); ann = stats.get("annual_return",0)
    dd = abs(stats.get("max_ddpercent",0)); sr = stats.get("sharpe_ratio",0)
    cal = abs(ann)/max(dd,1e-6) if ann and dd else 0

    buys = [t for t in trades if str(t.direction.value)=="Long"]
    tc = len(buys)
    trading_days = [d for d in dlist if abs(float(d.get("net_pnl",0)))>1e-6]
    wins = sum(1 for d in trading_days if float(d.get("net_pnl",0))>0)
    wr = wins/max(len(trading_days),1)*100

    avg_h = 0
    if buys:
        bds = sorted(set(str(t.datetime)[:10] for t in buys))
        sds = sorted(set(str(t.datetime)[:10] for t in trades if str(t.direction.value)=="Short"))
        holds = []
        for bd in bds:
            later = [sd for sd in sds if sd>bd]
            if later: holds.append((date.fromisoformat(later[0])-date.fromisoformat(bd)).days)
        if holds: avg_h = sum(holds)/len(holds)

    max_loss = min(float(d.get("net_pnl",0)) for d in dlist) if dlist else 0
    max_loss_pct = max_loss/1_000_000*100

    expo = sum(1 for d in dlist if float(d.get("end_pos",0))>0)/max(len(dlist),1)*100

    # ── Trade attribution: concentration ──
    daily_pnls = sorted([float(d.get("net_pnl",0)) for d in dlist], reverse=True)
    total_pos = sum(p for p in daily_pnls if p>0)
    total_neg = abs(sum(p for p in daily_pnls if p<0))
    top3_contrib = sum(daily_pnls[:3])/max(total_pos+total_neg,1e-6)*100 if daily_pnls else 0

    # ── Year stability ──
    yearly = defaultdict(lambda: {"ret":0,"trades":0,"dd":0,"sharpe":0})
    for d in dlist:
        dt = str(d.get("datetime",""))[:4]
        pnl = float(d.get("net_pnl",0))
        yearly[dt]["ret"] += pnl
        if abs(pnl)>1e-6: yearly[dt]["trades"] += 1
    for yr in yearly:
        yearly[yr]["ret"] = round(yearly[yr]["ret"]/1_000_000*100,1)

    return {"ret":ret,"dd":dd,"sr":sr,"cal":cal,"tc":tc,"wr":wr,"ah":avg_h,
            "ml":max_loss_pct,"ex":expo,"top3":top3_contrib,"yearly":dict(yearly)}

SIGNAL_DIR = Path("backtests/results/v0.22/signals")

for vt,(name,sd) in STOCKS.items():
    code = vt.split(".")[0]
    sp = SIGNAL_DIR / f"{code}_v0_22.json"
    sigs = json.loads(open(sp).read())
    dbp = make_db(sigs)

    print(f"\n{'='*120}")
    print(f"  {name} ({vt}) — B&H={469.2 if '688256' in vt else (-3.2 if '600036' in vt else 46.4)}%")
    print(f"{'='*120}")
    
    for ind in INDS:
        tech = backtest(vt, "tech_only", ind, sd)
        print(f"\n  [{ind.upper()} — all modes]")
        h = f"  {'Mode':<22} {'Ret':>7} {'MaxDD':>7} {'Shp':>6} {'Cal':>6} {'Trd':>5} {'WR%':>5} {'Hld':>5} {'Expo':>5} {'Top3%':>6} | Year stability"
        print(h); print(f"  {'-'*115}")
        
        for mode in MODES:
            if mode == "tech_only":
                r = tech
            else:
                r = backtest(vt, mode, ind, sd, dbp)
            yrs = " ".join(f"{y}:{v['ret']:+.1f}" for y,v in sorted(r["yearly"].items())[1:])  # skip partial first year
            print(f"  {mode:<22} {r['ret']:>6.1f}% {r['dd']:>6.1f}% {r['sr']:>5.2f} {r['cal']:>5.2f} {r['tc']:>5} {r['wr']:>4.0f}% {r['ah']:>4.0f}d {r['ex']:>4.0f}% {r['top3']:>5.0f}% | {yrs}")
    
    os.unlink(dbp)
