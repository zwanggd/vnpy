# Technical × Agent 回测矩阵 — 分阶段执行计划

> **Created**: 2026-05-27 | **Status**: Phase 0 开发中

## Architecture

### Phase 0 — 统一 TechnicalSignal 抽象

将现有 `MacdAgentStrategy`（MACD 硬编码 + Agent）重构为：

```
TechnicalIndicator (base)
├── MacdIndicator
├── MaAdxIndicator
├── DonchianIndicator
├── BollingerIndicator
└── RsiIndicator

TechnicalSignal (dataclass)
├── indicator_name
├── buy_signal: bool
├── sell_signal: bool
├── debug_info: dict
```

`TechAgentStrategy`（原 MacdAgentStrategy 改名）接受任意 `TechnicalIndicator` + agent 信号，保持所有 `signal_mode` 逻辑不变。

新增 `veto_only` 模式：
```python
should_buy  = tech_buy AND NOT agent_sell    # agent 只能阻止，不能助攻
should_sell = tech_sell OR agent_sell          # agent 可单独卖出
```

### Indicator Matrix

| Indicator | params | buy trigger | sell trigger |
|-----------|--------|------------|-------------|
| MACD | 12/26/9 | dif上穿dea | dif下穿dea |
| MA_ADX | ma=20, adx=14 | close>ma AND adx>25 | close<ma |
| Donchian | 20 | close突破上轨 | close跌破下轨 |
| Bollinger | 20/2 | close<下轨(超卖反弹) | close>上轨(超买回落) |
| RSI | 14 | rsi<30超卖反弹 | rsi>70超买回落 |

### Strategy × Agent Matrix

| Family | tech_only | +v0.2 | +v0.22 | +v0.22_veto |
|--------|:---:|:---:|:---:|:---:|
| buy_and_hold | ✅ | - | - | - |
| macd | ✅ | ✅ | ✅ | ✅ |
| ma_adx | ✅ | ✅ | ✅ | ✅ |
| donchian | ✅ | ✅ | ✅ | ✅ |
| bollinger | ✅ | ✅ | ✅ | ✅ |
| rsi | ✅ | ✅ | ✅ | ✅ |

### Combo Matrix (Phase 3)

| Combo | Logic | with v0.22 either_safe | with v0.22 veto_only |
|-------|-------|:---:|:---:|
| macd_adx | MACD金叉 + ADX>25确认 | ✅ | ✅ |
| donchian_atr | 突破 + ATR过滤假突破 | ✅ | ✅ |
| bollinger_ma | Bollinger + EMA趋势过滤 | ✅ | ✅ |

### Stocks

| Code | Name | Type | Start |
|------|------|------|-------|
| 600309.SSE | 万华化学 | 周期股 | 2020-01-01 |
| 600036.SSE | 招商银行 | 银行/低波 | 2020-01-01 |
| 688256.SSE | 寒武纪 | 高弹性概念 | 2020-07-20 |

### Output Files

```
backtests/results/matrix/
├── summary_matrix.csv
├── agent_contribution.csv
├── report.md
└── signals/
```

### Key Principles

1. **delta_vs_own_tech_only** 是核心指标，不和 MACD 比
2. **Buy and Hold** 是唯一被动基准
3. 每只股票独立分析
4. Agent 贡献归因：区分买入端/卖出端/veto端

### Execution Order

- [ ] Phase 0: TechnicalSignal 接口 + 迁移 MACD
- [ ] Phase 1: Buy and Hold + 5 tech_only
- [ ] Phase 2: Single Tech + Agent v0.2/v0.22/veto
- [ ] Phase 3: Technical Combos + Agent
- [ ] Phase 4: Agent 贡献归因
- [ ] Phase 5: 最终报告
