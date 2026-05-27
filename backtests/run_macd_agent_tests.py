import sys; sys.path.insert(0, '..'); sys.path.insert(0, '.')
import argparse
from datetime import datetime
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from strategies.macd_agent_strategy import MacdAgentStrategy, MODES


def main():
    parser = argparse.ArgumentParser(description="Run MACD Agent strategy backtests across all signal modes")
    parser.add_argument("--symbol", default="300750.SZSE", help="Trading symbol (default: 300750.SZSE)")
    parser.add_argument("--db-path", default="~/.vntrader/agent_news.db", help="Agent news database path")
    args = parser.parse_args()

    vt_symbol = args.symbol
    from pathlib import Path
    db_path = str(Path(args.db_path).expanduser())

    base = {"fast": 12, "slow": 26, "signal_period": 9, "pos_ratio": 0.5, "agent_threshold": 0.05, "init_capital": 1_000_000, "agent_db_path": db_path}

    print(f"{'Mode':<20} {'Return':>8} {'Annual':>8} {'Sharpe':>7} {'MaxDD':>7} {'Trades':>7} {'End Bal':>12}")
    print("-" * 75)

    for mode in MODES:
        setting = {**base, "signal_mode": mode}
        engine = BacktestingEngine()
        engine.set_parameters(
            vt_symbol=vt_symbol, interval=Interval.DAILY,
            start=datetime(2020, 1, 1), end=datetime(2026, 5, 15),
            rate=0.0003, slippage=0.01, size=100, pricetick=0.01,
            capital=1_000_000,
        )
        engine.add_strategy(MacdAgentStrategy, setting)
        engine.load_data()
        engine.run_backtesting()
        daily = engine.calculate_result()
        s = engine.calculate_statistics(daily, output=False)
        print(f"{mode:<20} {s['total_return']:>7.1f}% {s['annual_return']:>7.1f}% "
              f"{s['sharpe_ratio']:>6.2f} {s['max_ddpercent']:>6.1f}% "
              f"{s['total_trade_count']:>7} {s['end_balance']:>12.0f}")


if __name__ == "__main__":
    main()
