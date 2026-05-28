# vnpy Strategy Matrix Audit — v0.25

**Date**: 2026-05-28
**Scope**: Existing backtest infrastructure audit before v0.25 overhaul.

---

## 1. BacktestingEngine Entry Points

### run_macd_agent_tests.py
- Uses `BacktestingEngine` from `vnpy_ctastrategy.backtesting`
- Iterates all 9 modes of `MacdAgentStrategy`
- Fixed params: `rate=0.0003, slippage=0.01, size=100, pricetick=0.01, capital=1_000_000`
- Interval: DAILY, start 2020-01-01, end 2026-05-15
- Output: console table only (Return, Annual, Sharpe, MaxDD, Trades, End Bal)

### run_matrix.py
- Phases 1-3, multi-stock × indicator × agent_version × signal_mode
- Phase 1: tech_only indicators (macd, ma_adx, donchian, bollinger, rsi) + buy_and_hold
- Phase 2: 4 agent fusion modes × 2 signal versions
- Phase 3: combo indicators + agent fusion
- buy_and_hold: simple price ratio, NOT a CTA strategy (⚠️)
- Output: summary CSV to `backtests/results/matrix/`

---

## 2. Strategy Class Hierarchy

```
CtaTemplate (vnpy_ctastrategy)
├── MacdAgentStrategy (9 modes, MACD-specific, inlined indicator)
└── TechAgentStrategy (14 modes, pluggable indicator via indicator_name param)
```

### MacdAgentStrategy Modes
| Mode | Buy Rule | Sell Rule |
|------|----------|-----------|
| macd_only | MACD golden cross | MACD death cross |
| agent_only | agent direction=positive | agent direction=negative |
| both_consensus | MACD golden AND agent positive | MACD death OR agent sell |
| either_signal | MACD golden OR agent buy | MACD death OR agent sell |
| macd_confirmed | MACD golden + agent buy confirms | MACD death OR agent sell |
| agent_sell_only | MACD golden | MACD death OR agent sell |
| agent_buy_only | MACD golden OR agent buy | MACD death |
| macd_agent_entry_filter | MACD golden AND NOT agent sell | MACD death |
| either_safe | (MACD golden OR agent buy) AND NOT agent sell | MACD death OR agent sell |

### TechAgentStrategy Modes
14 modes, including: tech_only, agent_only, both_consensus, either_signal, tech_confirmed, agent_sell_only, agent_buy_only, tech_agent_entry_filter, either_safe, veto_only, tech_confirm_veto, tech_veto_only, agent_overlay, legacy_either_safe

---

## 3. Backtest Parameters

| Parameter | Value | Source |
|-----------|-------|--------|
| Rate (手续费) | 0.0003 (0.03%) | `set_parameters(rate=0.0003)` |
| Slippage | 0.01 | `set_parameters(slippage=0.01)` |
| Size (合约乘数) | 100 (A股) | `set_parameters(size=100)` |
| Pricetick | 0.01 | `set_parameters(pricetick=0.01)` |
| Initial Capital | 1,000,000 | `set_parameters(capital=1_000_000)` |
| Interval | DAILY | `Interval.DAILY` |
| Data Source | `~/.vntrader/database.db` | vnpy BaseDatabase |

---

## 4. Trades / Daily Results / Statistics Access

- `engine.calculate_result()` → `daily_df` DataFrame with columns: datetime, open, high, low, close, balance, return, net_pnl, drawdown, highlevel
- `engine.calculate_statistics(daily_df, output=False)` → dict with keys: `total_return`, `annual_return`, `sharpe_ratio`, `max_ddpercent`, `end_balance`, `total_trade_count`, `total_commission`, `total_slippage`, `total_turnover`, `return_std`, `daily_return`, `max_drawdown`, `max_drawdown_duration`, `total_days`, `profit_days`, `loss_days`, `total_net_pnl`
- `engine.get_all_trades()` → `list[TradeData]` with fields: datetime, direction, offset, price, volume, tradeid, orderid, etc.

---

## 5. Existing Technical Indicators (8 implemented)

| Indicator | Class | Signals |
|-----------|-------|---------|
| macd | MacdIndicator | Golden cross buy, death cross sell |
| ma_adx | MaAdxIndicator | Close > MA + ADX > threshold buy, close < MA sell |
| donchian | DonchianIndicator | Close > upper buy, close < lower sell |
| bollinger | BollingerIndicator | Close < lower buy, close > upper sell |
| rsi | RsiIndicator | Oversold → buy, overbought → sell |
| macd_adx | MacdAdxIndicator | MACD golden + ADX > min buy, MACD death sell |
| donchian_atr | DonchianAtrIndicator | Breakout > ATR filter buy, close < lower sell |
| bollinger_ma | BollingerMaIndicator | Close < lower + close > MA buy, close > upper sell |

---

## 6. either_signal vs either_safe — WHY IDENTICAL

**Root Cause**: For 601899.SSE (紫金矿业), the `agent_sell` signal fires extremely rarely (only 36 negative days out of 408, or 8.8%).

`either_safe` modifies `either_signal`'s BUY side only:
`should_buy = (macd_golden OR agent_buy) AND NOT agent_sell`

When `agent_sell` doesn't fire, `NOT agent_sell` is always True, making `either_safe` identical to `either_signal`.

This is **correct behavior** — not a bug. The `agent_sell` filter simply doesn't trigger for this stock.

**Recommendation**: Add a WARNING in reports when `either_signal` and `either_safe` produce identical results, indicating the stock may not benefit from the safety filter.

---

## 7. buy_and_hold Status

Current `run_matrix.py::compute_buy_hold` is a **simple price ratio calculation** that:
- Reads `engine.history_data` to get first and last close
- Computes `(last_close - first_close) / first_close * 100`
- Does NOT use vn.py CTA strategy, trading, fees, slippage, or position tracking

**Required**: Proper `BuyAndHoldStrategy(CtaTemplate)` that buys on first bar and holds.

---

## 8. Agent Signal Loader Status

Two nearly identical copies exist in `macd_agent_strategy.py:load_agent_signals()` and `tech_agent_strategy.py:load_agent_signals()`. Both:
- Query `agent_daily_signal` table directly via sqlite3
- Return `dict[date, {"signal": float, "direction": str}]`
- No signal_version filtering
- No JSON fallback
- No validation

**Required**: Centralize into `myQuant/backtest/agent_signal_loader.py`.

---

## 9. Future-Function Risk

Current signal usage in `on_bar`:
- Agent signal for `bar_date = bar.datetime.date()` is queried
- The `daily_agent_signal` trading_date is generated by `generate_daily_signals.py` using the **news available date**, which may or may not be T+1 shifted
- **Risk**: If signal uses same-day information (e.g., same-day close price sentiment), it may have look-ahead bias

**Recommendation**: Keep current behavior (signal-shift=0) as default. Add `--signal-shift-days 1` option for comparison. Document the risk.
