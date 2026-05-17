import sys; sys.path.insert(0, '.')
from datetime import datetime
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.macd_strategy import MacdStrategy

tests = [
    ("30% position", {"pos_ratio": 0.3, "pyramid_mode": False, "init_capital": 1_000_000}),
    ("50% position", {"pos_ratio": 0.5, "pyramid_mode": False, "init_capital": 1_000_000}),
    ("Pyramid 1unit", {"pyramid_mode": True, "pos_ratio": 0.5, "unit_shares": 100, "init_capital": 1_000_000}),
]

base = {"fast": 12, "slow": 26, "signal_period": 9}

print(f"{'Config':<18} {'Return':>8} {'Annual':>8} {'Sharpe':>7} {'MaxDD':>7} {'Trades':>7} {'End Bal':>12}")
print("-" * 70)

for label, overrides in tests:
    setting = {**base, **overrides}
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="300750.SZSE", interval=Interval.DAILY,
        start=datetime(2020, 1, 1), end=datetime(2026, 5, 15),
        rate=0.0003, slippage=0.01, size=100, pricetick=0.01,
        capital=1_000_000,
    )
    engine.add_strategy(MacdStrategy, setting)
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    s = engine.calculate_statistics(daily, output=False)
    print(f"{label:<18} {s['total_return']:>7.1f}% {s['annual_return']:>7.1f}% "
          f"{s['sharpe_ratio']:>6.2f} {s['max_ddpercent']:>6.1f}% "
          f"{s['total_trade_count']:>7} {s['end_balance']:>12.0f}")
