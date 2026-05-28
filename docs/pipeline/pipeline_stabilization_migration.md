# Pipeline Stabilization Migration Notes

**Date**: 2026-05-27

## Summary

5 个模块化前必须修的问题已修复。所有改动向后兼容。

## Schema 变化

### 1. `agent_signal` 表 — 新增 `signal_version` 列

| 变化 | 详情 |
|------|------|
| 新列 | `signal_version TEXT NULL` |
| 默认值 | NULL（旧数据） |
| 唯一约束 | 不变（未加入 unique constraint） |

**兼容性**: 旧 DB 无需迁移。新列 nullable，旧数据自动为 NULL。

### 2. `agent_daily_signal` 表 — 新建

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| trading_date | TEXT | ISO 日期 |
| vt_symbol | TEXT | 股票代码 |
| signal_version | TEXT | v0.2 / v0.22 |
| daily_agent_signal | REAL | [-1, 1] |
| daily_direction | TEXT | positive/negative/neutral |
| agent_label | TEXT | 版本标签 |
| raw_daily_signal | REAL | 中间值 |
| news_count | INTEGER | v0.2 新闻数 |
| event_count | INTEGER | v0.22 事件数 |
| model_count | INTEGER | 模型数 |
| mixed_intensity | REAL | 混合强度 |
| risk_penalty | REAL | 风险惩罚 |
| created_at | DATETIME | 创建时间 |

**唯一约束**: `(trading_date, vt_symbol, signal_version)`

**兼容性**: 新表，不影响现有数据。运行 `generate_daily_signals.py --persist` 后自动创建。

### 3. `daily_agent_signal` JSON — 字段统一

**旧 v0.22 schema**:
```json
["trading_date", "vt_symbol", "daily_agent_signal", "daily_direction", "event_count", "raw_daily", "mixed_intensity", "risk_penalty", "version"]
```

**新 v0.22 schema**:
```json
["trading_date", "vt_symbol", "signal_version", "daily_agent_signal", "daily_direction", "agent_label", "raw_daily_signal", "news_count", "event_count", "model_count", "mixed_intensity", "risk_penalty", "created_at"]
```

**兼容性**: 旧 JSON 文件仍可被回测脚本读取（`.get()` 有默认值）。新 JSON 包含所有字段。

### 4. `make_signal_db()` — schema 扩展

**旧 schema (7 列)**:
```sql
(entry_date, daily_agent_signal, daily_direction, news_count, pos/neg/neutral_news_count)
```

**新 schema (12 列)**:
```sql
(entry_date, daily_agent_signal, daily_direction, signal_version, agent_label,
 raw_daily_signal, news_count, event_count, model_count, mixed_intensity, risk_penalty, created_at)
```

**兼容性**: 回测脚本全部已更新。旧 JSON 文件通过 `.get()` 默认值兼容。

## 代码变化

### `evaluator.py`

- `_build_prompt()` 新增 `profile: StockProfile | None = None` 参数
- `evaluate()` 新增 `profile: StockProfile | None = None` 参数
- `trading_date` 使用 `available_at_to_trading_date()` 替代 `available_at.date().isoformat()`

**兼容性**: `profile` 默认 None，旧调用方式不受影响。

### `daily_aggregator.py`

- `run_v0_22_pipeline()` 输出新增 `signal_version`, `agent_label`, `raw_daily_signal`, `news_count`, `model_count`, `created_at`
- `run_v0_2_pipeline()` 输出统一为相同字段集

**兼容性**: 旧代码读取 `.get("event_count", 0)` 仍有效。

### `config.py`

新增版本常量:
- `AGGREGATION_VERSION = "v0.22"`
- `RELATION_WEIGHT_VERSION = "v0.22"`
- `HORIZON_WEIGHT_VERSION = "v0.22"`
- `EVENT_DEDUP_VERSION = "v0.22"`

## 新文件

| 文件 | 用途 |
|------|------|
| `myQuant/news_ingestion/calendar.py` | A 股交易日历 |
| `myQuant/news_ingestion/tests/test_calendar.py` | 日历测试 (9 tests) |
| `docs/pipeline_stabilization_migration.md` | 本文档 |

## 运行迁移

```bash
# 1. 重新生成 daily signal JSON（新 schema）
conda run -n vnpy43 python myQuant/news_ingestion/scripts/generate_daily_signals.py \
    --db-path ~/.vntrader/agent_news_em_600309.db \
    --vt-symbol 600309.SSE \
    --output backtests/results/v0.22/signals/600309_v0_22.json

# 2. 持久化到 DB（新建 agent_daily_signal 表）
conda run -n vnpy43 python myQuant/news_ingestion/scripts/generate_daily_signals.py \
    --db-path ~/.vntrader/agent_news_em_600309.db \
    --vt-symbol 600309.SSE \
    --persist

# 3. 运行审计验证
conda run -n vnpy43 python scripts/audit_current_pipeline.py
```
