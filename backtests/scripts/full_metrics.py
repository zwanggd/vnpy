#!/usr/bin/env python
"""Quick full-metrics run of Phase 2 clean modes — focused on 招商银行 agent_overlay."""
import sys, json, sqlite3, tempfile, os
from datetime import datetime, date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.tech_agent_strategy import TechAgentStrategy

STOCKS = {
    "600309.SSE": ("万华化学", date(2020, 1, 1)),
    "600036.SSE": ("招商银行", date(2020, 1, 1)),
    "688256.SSE": ("寒武纪", date(2020, 7, 20)),
}
INDICATORS = ["macd", "ma_adx", "bollinger", "rsi"]
MODES = ["tech_only", "tech_confirm_veto", "tech_veto_only", "agent_overlay", "legacy_either_safe"]
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
        start=datetime(start_d.year,start_d.month,start_d.day),
        end=datetime(2026,5,15), rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000)
    setting = {**BASE, "signal_mode": mode, "indicator_name": ind, "agent_db_path": dbp}
    e.add_strategy(TechAgentStrategy, setting)
    e.load_data()
    e.run_backtesting()
    daily = e.calculate_result()
    stats = e.calculate_statistics(daily, output=False)
    trades = e.get_all_trades()

    ret = stats.get("total_return",0)
    ann = stats.get("annual_return",0)
    dd = abs(stats.get("max_ddpercent",0))
    sr = stats.get("sharpe_ratio",0)
    cal = abs(ann)/max(dd,1e-6) if ann and dd else 0

    buys = [t for t in trades if str(t.direction.value)=="Long"]
    sells = [t for t in trades if str(t.direction.value)=="Short"]
    tc = len(buys)

    # Win rate
    daily_list = daily.to_dict("records") if hasattr(daily,"to_dict") else []
    trading_days = [d for d in daily_list if abs(float(d.get("net_pnl",0)))>1e-6]
    wins = sum(1 for d in trading_days if float(d.get("net_pnl",0))>0)
    wr = wins/max(len(trading_days),1)*100

    # Avg hold days
    avg_h = 0
    if buys and sells:
        bds = sorted(set(str(t.datetime)[:10] for t in buys))
        sds = sorted(set(str(t.datetime)[:10] for t in sells))
        holds = []
        for bd in bds:
            later = [sd for sd in sds if sd > bd]
            if later: holds.append((date.fromisoformat(later[0])-date.fromisoformat(bd)).days)
        if holds: avg_h = sum(holds)/len(holds)

    # Max single-day loss (from daily net_pnl)
    max_loss = 0.0
    if daily_list:
        for d in daily_list:
            pnl = float(d.get("net_pnl", 0))
            if pnl < max_loss:
                max_loss = pnl
    max_loss_pct = max_loss / 1_000_000 * 100 if max_loss < 0 else 0

    # Exposure ratio (days with end_pos > 0)
    if daily_list:
        days_with_pos = sum(1 for d in daily_list if float(d.get("end_pos",0)) > 0)
        total_days = len(daily_list)
        expo = days_with_pos/max(total_days,1)*100
    else:
        expo = 0

    return {"return":ret, "maxDD":dd, "sharpe":sr, "calmar":cal, "trades":tc,
            "win_rate":wr, "avg_hold":avg_h, "max_loss":max_loss_pct, "exposure":expo}

SIGNAL_DIR = Path("backtests/results/v0.22/signals")

for vt,(name,sd) in STOCKS.items():
    code = vt.split(".")[0]
    sp = SIGNAL_DIR / f"{code}_v0_22.json"
    sigs = json.loads(open(sp).read())
    dbp = make_db(sigs)
    
    print(f"\n{'='*100}")
    print(f"  {name} ({vt})")
    print(f"{'='*100}")
    hdr = f"  {'Mode':<22} {'Return':>8} {'MaxDD':>8} {'Sharpe':>7} {'Calmar':>7} {'Trades':>7} {'Win%':>6} {'HoldD':>6} {'MaxLoss':>8} {'Expo%':>6}"
    print(hdr)
    print(f"  {'-'*85}")
    
    for ind in INDICATORS:
        tech = backtest(vt, "tech_only", ind, sd)
        print(f"  [{ind}]")
        print(f"  {'tech_only':<22} {tech['return']:>7.1f}% {tech['maxDD']:>7.1f}% {tech['sharpe']:>6.2f} {tech['calmar']:>6.2f} {tech['trades']:>7} {tech['win_rate']:>5.1f}% {tech['avg_hold']:>5.1f}d {tech['max_loss']:>7.1f}% {tech['exposure']:>5.1f}%")
        for mode in MODES[1:]:  # skip tech_only
            r = backtest(vt, mode, ind, sd, dbp)
            print(f"  {mode:<22} {r['return']:>7.1f}% {r['maxDD']:>7.1f}% {r['sharpe']:>6.2f} {r['calmar']:>6.2f} {r['trades']:>7} {r['win_rate']:>5.1f}% {r['avg_hold']:>5.1f}d {r['max_loss']:>7.1f}% {r['exposure']:>5.1f}%")
    
    os.unlink(dbp)
