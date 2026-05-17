"""
Backtest CATL Multi-Signal Strategy on 300750.SZSE.

Uses the vnpy_ctastrategy BacktestingEngine with daily bar data
from the SQLite database at ~/.vntrader/database.db.
"""
import sys
from datetime import datetime
from pathlib import Path

# Add strategy path
sys.path.insert(0, str(Path(__file__).parent))
from strategies.catl_multi_signal import CatlMultiSignalStrategy

from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine


def run():
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="300750.SZSE",
        interval=Interval.DAILY,
        start=datetime(2020, 1, 1),
        end=datetime(2026, 5, 15),
        rate=0.0003,
        slippage=0.01,
        size=100,
        pricetick=0.01,
        capital=1_000_000,
    )

    setting = {
        "rsi_window": 14,
        "rsi_oversold": 35,
        "rsi_overbought": 70,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "vol_window": 20,
        "vol_mult": 2.0,
        "max_pos": 1,
    }
    engine.add_strategy(CatlMultiSignalStrategy, setting)

    engine.load_data()
    engine.run_backtesting()

    daily_df = engine.calculate_result()
    stats = engine.calculate_statistics(daily_df, output=True)

    # Print key metrics
    print("\n" + "=" * 60)
    print("CATL Multi-Signal Strategy — Key Metrics")
    print("=" * 60)
    if isinstance(stats, dict):
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}")
            else:
                print(f"  {k}: {v}")
    elif hasattr(stats, 'items'):
        for k, v in stats.items():
            print(f"  {k}: {v}")

    # Export daily returns
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    daily_df.to_csv(out_dir / "catl_multi_signal_daily.csv")
    print(f"\nDaily results → {out_dir / 'catl_multi_signal_daily.csv'}")

    # Chart if possible
    try:
        from vnpy_ctastrategy.backtesting import OptimizationSetting
        engine.show_chart()
    except Exception:
        pass


if __name__ == "__main__":
    run()
