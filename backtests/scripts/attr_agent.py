#!/usr/bin/env python
"""Phase 4: Agent contribution attribution — what does agent actually change?"""
import sys, json, sqlite3, tempfile, os
from datetime import datetime, date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.tech_agent_strategy import TechAgentStrategy

STOCKS = [("600309.SSE","万华化学",date(2020,1,1)),("600036.SSE","招商银行",date(2020,1,1)),("688256.SSE","寒武纪",date(2020,7,20))]
INDS = ["macd","ma_adx","bollinger","rsi"]

def attr(vt_symbol, ind, start_d, sig_path):
    e = BacktestingEngine()
    e.set_parameters(vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start_d.year,start_d.month,start_d.day), end=datetime(2026,5,15),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    s = {"fast":12,"slow":26,"signal_period":9,"pos_ratio":0.5,"agent_threshold":0.05,
         "init_capital":1_000_000,"signal_mode":"tech_only","indicator_name":ind,"agent_db_path":""}
    e.add_strategy(TechAgentStrategy,s); e.load_data(); e.run_backtesting()
    t = e.get_all_trades()
    t_buys = {str(x.datetime)[:10] for x in t if str(x.direction.value)=="Long"}
    t_sells = {str(x.datetime)[:10] for x in t if str(x.direction.value)=="Short"}

    sigs = json.loads(open(sig_path).read())
    fd,dbp = tempfile.mkstemp(suffix=".db"); os.close(fd)
    c = sqlite3.connect(dbp)
    c.execute("CREATE TABLE daily_agent_signal(entry_date TEXT,daily_agent_signal REAL,daily_direction TEXT,signal_version TEXT,agent_label TEXT,raw_daily_signal REAL,news_count INTEGER DEFAULT 0,event_count INTEGER DEFAULT 0,model_count INTEGER DEFAULT 0,mixed_intensity REAL DEFAULT 0.0,risk_penalty REAL DEFAULT 1.0,created_at TEXT)")
    for sg in sigs: c.execute("INSERT INTO daily_agent_signal VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(sg["trading_date"],sg["daily_agent_signal"],sg["daily_direction"],sg.get("signal_version",""),sg.get("agent_label",""),sg.get("raw_daily_signal",0),sg.get("news_count",0),sg.get("event_count",0),sg.get("model_count",0),sg.get("mixed_intensity",0),sg.get("risk_penalty",1.0),sg.get("created_at","")))
    c.commit(); c.close()

    e2 = BacktestingEngine(); e2.set_parameters(vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start_d.year,start_d.month,start_d.day), end=datetime(2026,5,15),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    e2.add_strategy(TechAgentStrategy,{**s,"signal_mode":"either_safe","agent_db_path":dbp})
    e2.load_data(); e2.run_backtesting()
    a = e2.get_all_trades()
    a_buys = {str(x.datetime)[:10] for x in a if str(x.direction.value)=="Long"}
    a_sells = {str(x.datetime)[:10] for x in a if str(x.direction.value)=="Short"}
    os.unlink(dbp)

    # Also run veto_only for comparison
    fd2,dbp2 = tempfile.mkstemp(suffix=".db"); os.close(fd2)
    c2 = sqlite3.connect(dbp2)
    c2.execute("CREATE TABLE daily_agent_signal(entry_date TEXT,daily_agent_signal REAL,daily_direction TEXT,signal_version TEXT,agent_label TEXT,raw_daily_signal REAL,news_count INTEGER DEFAULT 0,event_count INTEGER DEFAULT 0,model_count INTEGER DEFAULT 0,mixed_intensity REAL DEFAULT 0.0,risk_penalty REAL DEFAULT 1.0,created_at TEXT)")
    for sg in sigs: c2.execute("INSERT INTO daily_agent_signal VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(sg["trading_date"],sg["daily_agent_signal"],sg["daily_direction"],sg.get("signal_version",""),sg.get("agent_label",""),sg.get("raw_daily_signal",0),sg.get("news_count",0),sg.get("event_count",0),sg.get("model_count",0),sg.get("mixed_intensity",0),sg.get("risk_penalty",1.0),sg.get("created_at","")))
    c2.commit(); c2.close()
    e3 = BacktestingEngine(); e3.set_parameters(vt_symbol=vt_symbol, interval=Interval.DAILY,
        start=datetime(start_d.year,start_d.month,start_d.day), end=datetime(2026,5,15),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    e3.add_strategy(TechAgentStrategy,{**s,"signal_mode":"veto_only","agent_db_path":dbp2})
    e3.load_data(); e3.run_backtesting()
    v = e3.get_all_trades()
    v_buys = {str(x.datetime)[:10] for x in v if str(x.direction.value)=="Long"}
    os.unlink(dbp2)

    return len(t_buys), len(a_buys), len(v_buys), len(t_buys-a_buys), len(t_sells-a_sells), len(a_buys-t_buys), len(a_sells-t_sells)

print(f"{'Stock':<8} {'Ind':<12} {'Tech':>6} {'+Agent':>7} {'+Veto':>7} {'BlockBuy':>9} {'BlockSell':>10} {'EarlyBuy':>9} {'EarlySell':>10}")
print("-"*80)
for vt,nm,st in STOCKS:
    cd = vt.split(".")[0]
    sp = f"backtests/results/v0.22/signals/{cd}_v0_22.json"
    for ind in INDS:
        tb,ab,vb,bb,bs,eb,es = attr(vt,ind,st,sp)
        print(f"{nm:<8} {ind:<12} {tb:>6} {ab:>7} {vb:>7} {bb:>9} {bs:>10} {eb:>9} {es:>10}")
print("Done.")
