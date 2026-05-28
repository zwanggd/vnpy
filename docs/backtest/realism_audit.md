# vn.py CTA BacktestingEngine 真实度审计

**Date**: 2026-05-28
**Engine**: `vnpy_ctastrategy.backtesting.BacktestingEngine` (CTA, 1267 lines)
**Source**: `/opt/anaconda3/envs/vnpy43/lib/python3.12/site-packages/vnpy_ctastrategy/backtesting.py`

> 当前项目策略使用 CTA 引擎（非 Alpha 引擎）。Alpha 引擎位于 `vnpy/alpha/strategy/backtesting.py`，有部分涨跌停检查但无滑点建模。

---

## 维度 1：手续费（Commission）

**状态**: ✅ 已模拟

**公式**:
```
turnover = volume × size × trade_price       # 成交额
commission = turnover × rate                  # 手续费（双向）
```

**代码位置**: `DailyResult.calculate_pnl()` L1089, L1123

**当前参数**:
| 参数 | 值 | 含义 |
|------|-----|------|
| `rate` | 0.0003 | 万三（0.03%），买入卖出各收一次 |
| `size` | 100 | A股每手 100 股 |

**举例**: 买入 100手 (10000股) × ¥20 = ¥200,000 成交额 → 手续费 ¥60。一买一卖共 ¥120。

**局限性**: 固定比例费率，不模拟最低佣金、过户费、印花税等细分费用。A股卖出有 0.05% 印花税未单独建模。

**对 601899 紫金矿业影响**: macd_only 策略 6 年累计手续费 ¥15,786，占总收益约 2.2%。合理。

---

## 维度 2：滑点（Slippage）

**状态**: ✅ 已模拟（固定每股金额）

**公式**:
```
slippage_cost = volume × size × slippage_per_unit
```

**代码位置**: `DailyResult.calculate_pnl()` L1120

**当前参数**:
| 参数 | 值 | 含义 |
|------|-----|------|
| `slippage` | 0.01 | 每股 1 分钱（固定金额，非百分比） |

**关键特性**: 滑点以**纯成本扣减**形式在 PnL 中扣除，不改变实际成交价：
```python
self.net_pnl = self.total_pnl - self.commission - self.slippage  # L1127
```

**举例**: 买入 10000 股 → 滑点成本 ¥100。无论股价 ¥5 还是 ¥50。¥20 股价时对应约 0.05%。

**局限性**:
- 固定每股金额，不随股价波动变化
- 不随交易量增大（大单冲击）
- 不随市场波动率变化
- 是事后成本扣减，不是成交价调整

**对 601899 影响**: ¥20 股价下每股 0.01 滑点 ≈ 0.05%，合理偏乐观。

---

## 维度 3：涨跌停 / 封板（Limit-up / Limit-down）

**状态**: ❌ CTA 引擎完全不检查

**代码位置**: `cross_limit_order()` L671-742 — 无任何 `limit_up`/`limit_down` 变量或检查。

**对比 Alpha 引擎** (`vnpy/alpha/strategy/backtesting.py` L638-654):
```python
limit_up = round_to(pre_close * 1.1, pricetick)       # 硬编码 A股 ±10%
limit_down = round_to(pre_close * 0.9, pricetick)

# 买入单：只有 bar.low_price < limit_up 时才允许成交
# （即：全天封板时才拒绝。打开过涨停板 → 允许成交）
long_cross = (order.direction == Direction.LONG
              and order.price >= long_cross_price
              and bar.low_price < limit_up)

# 卖出单：只有 bar.high_price > limit_down 时才允许成交
short_cross = (order.direction == Direction.SHORT
               and order.price <= short_cross_price
               and bar.high_price > limit_down)
```

**含义**: 即使切换到 Alpha 引擎，也只拒绝**开盘即封板、全天未打开**的情况。盘中打开涨停板过的 bar 仍会成交。实盘中涨停板上排队成交需要时间和运气。

**对 601899 影响**: **低**。紫金矿业是沪市主板大盘股（600 开头），6 年涨停不超过 10 次，且市值大、换手充分，涨停板即使出现也很少全天封死。

**⚠️ 小盘股风险（如 688256 寒武纪）**: 科创板 ±20%，封板更频繁，CTA 引擎完全不检查 → 回测收益**显著高估**。

---

## 维度 4：成交量 / 流动性约束（Volume / Liquidity）

**状态**: ❌ 完全不检查

**代码位置**: `cross_limit_order()` L709 — 始终全额成交：
```python
order.traded = order.volume   # 全量成交，无部分成交逻辑
```

**缺失的检查**:
- 不检查 bar 的实际成交量是否足够支撑下单量
- 不检查 market depth（没有订单簿）
- 没有 partial fill（部分成交）逻辑
- 没有 queue position（排队位置）概念

**对 601899 影响**: **低**。100 万初始资金最多买约 1000 手（10 万股），601899 日均成交量几千万至几亿元量级。但如果资金量级扩大到 5000 万以上，流动性约束会显著影响。

**⚠️ 大规模策略风险**: capital > 5000 万时需要警惕——回测会明显高估收益。

---

## 维度 5：成交价格（Fill Price）

**状态**: ⚠️ 简化但基本合理

**BAR 模式成交逻辑** (`cross_limit_order` L676-724):

| 订单方向 | 判断条件 | 成交价 |
|---------|---------|--------|
| 买入 | `order.price >= bar.low_price` | `min(order.price, bar.open_price)` |
| 卖出 | `order.price <= bar.high_price` | `max(order.price, bar.open_price)` |

**关键**: 成交价始终是 `bar.open_price`（优化价），而不是 `bar.close_price`。

**当前策略行为**:
```python
# strategies/macd_agent_strategy.py L158
self.buy(bar.close_price, lots)    # 用当日收盘价下单
self.sell(bar.close_price, lots)
```

策略用**当日收盘价**下的单，但引擎用**下一 bar 的开盘价**成交 → 含有一个 bar 的延迟（≈ T+1 效果）。

**局限性**:
- 不模拟 intra-bar timing（日内择时）
- 假定在 bar 的最佳时刻（开盘）成交
- TICK 模式下更真实（用 real ask/bid 价），但当前项目未使用

**对 601899 影响**: **中等**。Bar 延迟天然提供了 T+1 效果（今日收盘信号 → 明日开盘执行），这是合理且保守的。但用开盘价成交偏乐观——真实交易中成交价通常劣于开盘价。

---

## 维度 6：市场冲击（Market Impact）

**状态**: ❌ 完全不建模

**缺失**:
- 无价格冲击函数（order size 不影响 fill price）
- 无 order book depletion（订单簿消耗）
- 无 spread widening under stress（压力下点差扩大）
- 无 volume-weighted fill pricing（成交量加权成交价）

**代码证据**: `cross_limit_order()` 的成交价计算与 `trade.volume` 无关——买 1 手和买 1000 手以完全相同的价格成交。

**对 601899 影响**: **低**。100 万资金在紫金矿业上的冲击可忽略。但对 688256 寒武纪（日均成交额小得多）会有影响。

---

## 总结矩阵

| 维度 | 状态 | 公式 | 对 601899 影响 | 对小盘股影响 |
|------|------|------|:---:|:---:|
| 手续费 | ✅ | `volume × size × price × rate` | 🟢 低 | 🟢 低 |
| 滑点 | ✅ | `volume × size × 0.01` | 🟢 低 | 🟡 中 |
| 涨跌停 | ❌ | 完全不检查 | 🟢 低 | 🔴 高 |
| 成交量 | ❌ | 全额成交，无部分成交 | 🟢 低 | 🔴 高 |
| 成交价 | ⚠️ | `min/max(order, bar.open)` | 🟡 中 | 🟡 中 |
| 市场冲击 | ❌ | 无 | 🟢 低 | 🔴 高 |

**🟢 低** = 对回测结果几乎无影响
**🟡 中** = 有一定影响，需注意
**🔴 高** = 显著高估收益，不可忽视

---

## 适用性边界

当前回测设置在以下条件下**基本可靠**:

| 条件 | 限制 |
|------|------|
| 资金规模 | ≤ 500 万 |
| 股票类型 | 主板大盘股（600/000 开头，市值 > 1000 亿）|
| K 线周期 | 日线（含 bar 延迟 ≈ T+1） |
| 策略频率 | 低频（日频信号） |

以下条件下回测结果**显著偏高**:

| 条件 | 原因 |
|------|------|
| 资金规模 > 5000 万 | 流动性约束 |
| 小盘股 / 科创板（688） | 涨跌停频繁、流动性差 |
| 分钟级策略 | 无 intra-bar timing |
| 高频策略 | 无订单簿、无市场冲击 |

---

## Alpha 引擎补充（参考）

项目 AGENTS.md 提到回测引擎来自 `vnpy.alpha`，但当前策略实际用的 CTA 引擎。
两者差异：

| 特性 | CTA 引擎 | Alpha 引擎 |
|------|---------|-----------|
| 手续费 | 单一 rate | long_rate / short_rate 分别配置 |
| 滑点 | ✅ 固定每股 | ❌ 无 |
| 涨跌停 | ❌ 不检查 | ⚠️ 仅拒绝全天封板 |
| 止盈止损单 | ✅ cross_stop_order | ❌ 无 |
| TICK 模式 | ✅ | ❌ 仅 BAR |
