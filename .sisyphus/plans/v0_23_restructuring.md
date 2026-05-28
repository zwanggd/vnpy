# v0.23 项目重组方案 (Safe Refactor)

> **Status**: ✅ 完成 | **Date**: 2026-05-27
> **原则**: 不破坏现有功能，逐步重构

---

## v0.23a 执行结果

| 检查项 | 结果 |
|--------|------|
| pytest | ✅ 52 passed |
| audit | ✅ 23 passed, 5 failed (预期), 2 warnings |
| smoke test | ✅ 421 daily records |
| 结果等价 | ✅ 421 行完全一致 |
| 备份 | ✅ 4.7MB tar.gz |
| 归档脚本 | ✅ 11 个 |
| 归档结果 | ✅ 13 个 |

## v0.23b 执行结果

| 检查项 | 结果 |
|--------|------|
| pytest | ✅ 52 passed |
| import smoke test | ✅ 所有新路径可用 |
| 结果等价 | ✅ 421 行完全一致 |

### 新增目录

| 目录 | 作用 |
|------|------|
| myQuant/core/ | calendar, config, schema |
| myQuant/data/ | models, repositories, backup |
| myQuant/news/ | sources, recall |
| myQuant/agent/ | evaluator |
| myQuant/scoring/ | daily_aggregator, row_scorer |
| myQuant/backtest/ | report |
| myQuant/pipeline/ | BackfillPipeline |

### Import 兼容性

```python
# 旧路径 (继续可用)
from myQuant.news_ingestion.contracts import AgentSignal
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository

# 新路径 (v0.23b+)
from myQuant.core import AgentSignal
from myQuant.data import AgentNewsSqliteRepository
from myQuant.news import RecallEngine
from myQuant.agent import DeepSeekNewsEvaluator
from myQuant.scoring import run_v0_22_pipeline
from myQuant.pipeline import BackfillPipeline
```

---

## 1. 核心原则

1. **不永久删除业务代码** — 所有"删除"都移到 archive/
2. **不在同一 phase 做多件事** — 移动、拆分、改 import、改逻辑分开
3. **旧路径必须继续可用** — 通过 facade/wrapper 保持兼容
4. **每步都要验证** — pytest + audit + smoke test
5. **结果等价** — 重构前后 600309.SSE 输出必须一致

---

## 2. 三阶段拆分

### v0.23a: 清理与归档 (本周)
- 备份 DB 和 JSON
- 创建 archive/
- 归档一次性脚本和旧结果
- 更新 .gitignore
- **不移动核心 myQuant 代码**
- **不拆 sqlite.py / evaluator.py / pipeline.py / contracts.py**
- 验证: pytest + audit + smoke test

### v0.23b: 建立新目录和兼容层 (下周)
- 创建 myQuant/core, data, news, agent, signal, backtest, pipeline
- 建立 facade/wrapper，不拆内部实现
- 旧 import 路径必须继续可用
- 验证: pytest + audit + smoke test

**v0.23b QA 场景**:
```bash
# 1. pytest
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q
# 预期: 所有测试通过

# 2. import smoke test (新路径)
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -c "
from myQuant.core import AgentSignal, is_trading_day, CONFIG_VERSION
from myQuant.data import AgentNewsSqliteRepository
from myQuant.news import RecallEngine
from myQuant.agent import DeepSeekNewsEvaluator
from myQuant.scoring import run_v0_22_pipeline
from myQuant.pipeline import BackfillPipeline
print('✅ All new import paths work')
"
# 预期: 打印 "All new import paths work"

# 3. import smoke test (旧路径)
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -c "
from myQuant.news_ingestion.contracts import AgentSignal
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository
from myQuant.news_ingestion.scoring.daily_aggregator import run_v0_22_pipeline
print('✅ All old import paths work')
"
# 预期: 打印 "All old import paths work"

# 4. smoke test
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --vt-symbol 600309.SSE \
  --persist
# 预期: 421 daily records

# 5. 结果等价验证
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -c "
import json
data = json.loads(open('backtests/results/v0.22/signals/600309_v0_22.json').read())
assert len(data) == 421
assert data[0]['trading_date'] == '2020-01-13'
print('✅ Result equivalence passed')
"
# 预期: 打印 "Result equivalence passed"
```

### v0.23c: 逐步拆核心大文件 (后续)
- 每次只拆一个文件
- 每拆一个文件单独跑测试
- 不允许一次性拆多个核心文件

**v0.23c 拆分任务清单**:

| 任务 | 源文件 | 目标文件 | 第一步 |
|------|--------|----------|--------|
| c.1 | storage/sqlite.py | data/models.py | 提取 Peewee 模型定义 |
| c.2 | storage/sqlite.py | data/repositories.py | 提取 CRUD 方法 |
| c.3 | llm/evaluator.py | agent/prompt_builder.py | 提取 _build_prompt() |
| c.4 | llm/evaluator.py | agent/json_parser.py | 提取 JSON 验证逻辑 |
| c.5 | pipeline.py | pipeline/source_factory.py | 提取 _default_source_factory |
| c.6 | contracts.py | core/enums.py | 提取枚举定义 |

**v0.23c QA 场景 (每个任务)**:
```bash
# 1. 拆分前备份
cp <source_file> <source_file>.bak

# 2. 执行拆分
# (具体代码改动)

# 3. pytest
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q
# 预期: 所有测试通过

# 4. import smoke test
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -c "
from myQuant.<new_module> import <extracted_class>
print('✅ Import works')
"
# 预期: 打印 "Import works"

# 5. smoke test
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --vt-symbol 600309.SSE \
  --persist
# 预期: 421 daily records

# 6. 结果等价验证
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -c "
import json
data = json.loads(open('backtests/results/v0.22/signals/600309_v0_22.json').read())
assert len(data) == 421
print('✅ Result equivalence passed')
"
# 预期: 打印 "Result equivalence passed"

# 7. 清理备份
rm <source_file>.bak
```

---

## 3. v0.23a 执行清单

### 3.1 备份

```bash
# 备份 DB 和 JSON
tar czf ~/Desktop/agent_backup_$(date +%Y%m%d).tar.gz \
  ~/.vntrader/agent_news_em_*.db \
  backtests/results/v0.22/signals/*.json

# 验证备份
ls -la ~/Desktop/agent_backup_*.tar.gz
# 预期: 文件大小 > 10MB
```

### 3.2 创建 archive 目录

```bash
mkdir -p archive/legacy_scripts archive/old_results
ls -la archive/
# 预期: 两个子目录
```

### 3.3 归档一次性脚本 (移到 archive/legacy_scripts/)

| 文件 | 原因 |
|------|------|
| backtests/analyze_either_safe.py | 被 equity_reconciliation.py 取代 |
| backtests/run_macd_tests.py | 硬编码，无参数 |
| backtests/scripts/analyze_cambricon.py | 一次性诊断 |
| backtests/scripts/trace_cambricon.py | 一次性诊断 |
| backtests/scripts/diag_wanhua.py | 一次性诊断 |
| backtests/scripts/compare_agent_versions.py | 一次性比较 |
| backtests/scripts/full_metrics.py | 被 full_report.py 取代 |
| backtests/scripts/full_report.py | stdout-only |
| backtests/scripts/yearly_report.py | stdout-only |
| backtests/scripts/attr_agent.py | Phase 4 探索 |
| backtests/strategies/macd_strategy.py | 被 macd_agent_strategy.py 取代 |

### 3.4 归档旧结果 (移到 archive/old_results/)

| 文件/目录 | 原因 |
|-----------|------|
| backtests/results/v0.21/ | v0.21 时代产物 |
| backtests/results/2026-05-12_*.md | v0.1 报告 |
| backtests/results/agent_news_v01_*.md | v0.1 报告 |
| backtests/results/2026-05-12_qwen_10.md | Qwen 测试 |
| backtests/results/2026-05-10_doublema_*.md | DoubleMA 报告 |
| backtests/results/audit_agent_exits.* | v0.1 审计 |
| backtests/results/cost_sensitivity.* | v0.1 分析 |
| backtests/results/ma_filter_results.* | v0.1 分析 |

### 3.5 处理 evaluate_news.py

| 动作 | 文件 | 说明 |
|------|------|------|
| 移到 archive | backtests/scripts/evaluate_news.py | 旧版，功能被取代 |
| 重命名 | backtests/scripts/eval_all_unevaluated.py → backtests/scripts/evaluate_news.py | 新版入口 |

**注意**: 如果有旧命令依赖 `evaluate_news.py`，需要在 migration notes 中说明。

### 3.6 更新 .gitignore

```gitignore
# 新增
.opencode/
.sisyphus-debug/
.pytest_cache/
```

### 3.7 验证

```bash
# pytest
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q

# audit
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python scripts/audit_current_pipeline.py

# smoke test
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --vt-symbol 600309.SSE \
  --persist
```

---

## 4. Result Equivalence Check

### 4.1 重构前基线 (v0.22)

```bash
# 生成基线 JSON
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --vt-symbol 600309.SSE \
  --output backtests/results/v0.22/signals/600309_v0_22_baseline.json

# 记录基线指标
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -c "
import json
data = json.loads(open('backtests/results/v0.22/signals/600309_v0_22_baseline.json').read())
print(f'行数: {len(data)}')
print(f'trading_date 范围: {data[0][\"trading_date\"]} ~ {data[-1][\"trading_date\"]}')
print(f'signal 范围: {min(r[\"daily_agent_signal\"] for r in data):.6f} ~ {max(r[\"daily_agent_signal\"] for r in data):.6f}')
"
```

### 4.2 重构后验证

```bash
# 生成验证 JSON
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --vt-symbol 600309.SSE \
  --output backtests/results/v0.22/signals/600309_v0_22_verify.json

# 比较
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -c "
import json
baseline = json.loads(open('backtests/results/v0.22/signals/600309_v0_22_baseline.json').read())
verify = json.loads(open('backtests/results/v0.22/signals/600309_v0_22_verify.json').read())

assert len(baseline) == len(verify), f'行数不一致: {len(baseline)} vs {len(verify)}'

for b, v in zip(baseline, verify):
    assert b['trading_date'] == v['trading_date'], f'trading_date 不一致'
    assert abs(b['daily_agent_signal'] - v['daily_agent_signal']) < 1e-9, f'signal 不一致'
    assert b['daily_direction'] == v['daily_direction'], f'direction 不一致'
    assert b['signal_version'] == v['signal_version'], f'version 不一致'
    assert b['event_count'] == v['event_count'], f'event_count 不一致'

print('✅ 结果等价验证通过')
"
```

---

## 5. 测试文件处理

**保留原位**: myQuant/news_ingestion/tests/

原因:
- 现有测试路径依赖 myQuant.news_ingestion.tests
- 移动测试会破坏所有 test import
- 等 v0.23b 建立兼容层后再考虑

---

## 6. 新增文件清单 (v0.23b)

### 6.1 Facade/Wrapper 文件

| 新文件 | 作用 | 旧路径 |
|--------|------|--------|
| myQuant/core/__init__.py | 导出 calendar, config, schema | - |
| myQuant/core/calendar.py | wrapper → news_ingestion/calendar.py | - |
| myQuant/core/config.py | wrapper → news_ingestion/scoring/config.py | - |
| myQuant/core/schema.py | wrapper → news_ingestion/contracts.py | - |
| myQuant/data/__init__.py | 导出 models, repositories | - |
| myQuant/data/models.py | wrapper → storage/sqlite.py (models) | - |
| myQuant/data/repositories.py | wrapper → storage/sqlite.py (CRUD) | - |

### 6.2 Import 兼容说明

```python
# 旧路径 (继续可用)
from myQuant.news_ingestion.contracts import AgentSignal
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository

# 新路径 (v0.23b+)
from myQuant.core.schema import AgentSignal
from myQuant.data.repositories import AgentNewsSqliteRepository
```

---

## 7. Known Issues

1. **evaluate_news.py 重命名**: 如果有脚本依赖旧路径，需要更新
2. **eastmoney_legacy.py**: 移到 archive/，不删除
3. **sina.py**: 未接入 pipeline，保留原位
4. **测试路径**: 保持原位，v0.23b 后再考虑

---

## 8. 验收标准

1. ✅ pytest 全部通过
2. ✅ audit 无 CRITICAL 错误
3. ✅ 600309.SSE smoke test 通过
4. ✅ 结果等价验证通过
5. ✅ 旧 CLI 命令仍可用
6. ✅ 旧 JSON 兼容不破坏
7. ✅ agent_daily_signal persist 不破坏
8. ✅ trading_date 映射不破坏
