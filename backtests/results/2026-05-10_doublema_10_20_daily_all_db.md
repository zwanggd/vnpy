# DoubleMA(10, 20) Daily Backtest - All Database Stocks

## Run Metadata

- Date: 2026-05-10
- Conda environment: `vnpy43`
- Command: `conda run -n vnpy43 python backtests/scripts/run_doublema_daily_all_db.py`
- Database: `~/.vntrader/database.db`
- Strategy: `vnpy_ctastrategy.strategies.double_ma_strategy.DoubleMaStrategy`
- Parameters: `fast_window=10`, `slow_window=20`
- Interval: daily bars, `Interval.DAILY`
- Time range: full available database range, `2020-01-02` to `2026-05-08`
- Symbols: all 10 daily-bar stocks in `dbbaroverview`

## Backtest Settings

| Setting | Value |
|---|---:|
| Initial capital per symbol | 1,000,000 |
| Rate | 0.0003 |
| Slippage | 0.01 |
| Size | 100 |
| Price tick | 0.01 |
| Bars loaded per symbol | 1,535 |

## Results

| Symbol | Net PnL | Total Return | Annual Return | Max Drawdown | Max DD% | Trades | Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| 000333.SZSE | 923.53 | 0.09% | 0.01% | -6,196.52 | -0.62% | 111 | 0.07 |
| 002475.SZSE | 5,777.46 | 0.58% | 0.09% | -2,489.05 | -0.25% | 125 | 0.49 |
| 002594.SZSE | -28,750.30 | -2.88% | -0.45% | -59,296.98 | -5.76% | 135 | -0.35 |
| 300750.SZSE | -50,498.17 | -5.05% | -0.79% | -69,313.05 | -6.82% | 129 | -0.47 |
| 600036.SSE | -4,455.69 | -0.45% | -0.07% | -5,140.69 | -0.51% | 117 | -0.64 |
| 600276.SSE | 8,472.25 | 0.85% | 0.13% | -2,149.30 | -0.21% | 119 | 0.70 |
| 600309.SSE | -861.44 | -0.09% | -0.01% | -12,375.01 | -1.23% | 125 | -0.05 |
| 600519.SSE | -147,530.54 | -14.75% | -2.31% | -227,408.48 | -21.26% | 133 | -0.56 |
| 601318.SSE | -7,494.50 | -0.75% | -0.12% | -8,671.63 | -0.87% | 113 | -0.79 |
| 601899.SSE | 1,598.30 | 0.16% | 0.02% | -1,222.12 | -0.12% | 127 | 0.39 |

## Short Conclusion

DoubleMA(10, 20) performed weakly on this 10-stock daily dataset under the above assumptions. The better performers were `600276.SSE`, `002475.SZSE`, `601899.SSE`, and `000333.SZSE`. The largest drag came from `600519.SSE`, followed by `300750.SZSE` and `002594.SZSE`.

The result suggests this simple moving-average crossover setup is not robust across the current A-share sample without further filtering, parameter search, market-regime logic, or risk controls.
