from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy_ctastrategy.strategies.double_ma_strategy import DoubleMaStrategy


DB_PATH = Path.home() / ".vntrader" / "database.db"
FAST_WINDOW = 10
SLOW_WINDOW = 20
RATE = 0.0003
SLIPPAGE = 0.01
SIZE = 100
PRICETICK = 0.01
CAPITAL = 1_000_000


def clean(value: Any) -> Any:
    """Convert vn.py/numpy statistic values into JSON-serializable values."""
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
    except Exception:
        pass

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None

    return value


def get_symbols() -> list[tuple[str, str, str, str, int]]:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(
            """
            SELECT symbol, exchange, start, end, count
            FROM dbbaroverview
            WHERE interval = 'd'
            ORDER BY symbol
            """
        ).fetchall()
    finally:
        conn.close()


def run_symbol(symbol: str, exchange: str, start: str, end: str, count: int) -> dict[str, Any]:
    vt_symbol = f"{symbol}.{exchange}"
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.DAILY,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        rate=RATE,
        slippage=SLIPPAGE,
        size=SIZE,
        pricetick=PRICETICK,
        capital=CAPITAL,
    )
    engine.add_strategy(DoubleMaStrategy, {"fast_window": FAST_WINDOW, "slow_window": SLOW_WINDOW})
    engine.load_data()
    engine.run_backtesting()
    daily = engine.calculate_result()
    stats = engine.calculate_statistics(daily, output=False)

    return {
        "vt_symbol": vt_symbol,
        "db_bars": count,
        "loaded_bars": len(engine.history_data),
        "start": start[:10],
        "end": end[:10],
        "total_days": clean(stats.get("total_days")),
        "profit_days": clean(stats.get("profit_days")),
        "loss_days": clean(stats.get("loss_days")),
        "end_balance": clean(stats.get("end_balance")),
        "total_net_pnl": clean(stats.get("total_net_pnl")),
        "total_commission": clean(stats.get("total_commission")),
        "total_slippage": clean(stats.get("total_slippage")),
        "total_trade_count": clean(stats.get("total_trade_count")),
        "total_return": clean(stats.get("total_return")),
        "annual_return": clean(stats.get("annual_return")),
        "max_drawdown": clean(stats.get("max_drawdown")),
        "max_ddpercent": clean(stats.get("max_ddpercent")),
        "sharpe_ratio": clean(stats.get("sharpe_ratio")),
        "return_drawdown_ratio": clean(stats.get("return_drawdown_ratio")),
    }


def main() -> None:
    results = [run_symbol(*row) for row in get_symbols()]
    payload = {
        "config": {
            "database": str(DB_PATH),
            "strategy": "vnpy_ctastrategy.strategies.double_ma_strategy.DoubleMaStrategy",
            "setting": {"fast_window": FAST_WINDOW, "slow_window": SLOW_WINDOW},
            "interval": "DAILY",
            "rate": RATE,
            "slippage": SLIPPAGE,
            "size": SIZE,
            "pricetick": PRICETICK,
            "capital_per_symbol": CAPITAL,
        },
        "results": results,
    }
    print("OMO_DOUBLEMA_JSON_START")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("OMO_DOUBLEMA_JSON_END")


if __name__ == "__main__":
    main()
