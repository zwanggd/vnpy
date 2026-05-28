# v0.23 重组最终报告

> **Date**: 2026-05-27
> **Status**: 完成

---

## 1. 执行概览

### 三阶段完成情况

| 阶段 | 状态 | 主要成果 |
|------|------|----------|
| v0.23a: 清理与归档 | ✅ | 归档 11 脚本 + 13 结果文件，备份 4.7MB |
| v0.23b: 新目录和兼容层 | ✅ | 7 个新模块目录，所有 import 路径可用 |
| v0.23c: 拆核心大文件 | ✅ | 提取 data/models.py (268 行) |

### 验证结果

| 检查项 | 结果 |
|--------|------|
| pytest | ✅ 52 passed |
| import smoke test (新路径) | ✅ 所有新路径可用 |
| import smoke test (旧路径) | ✅ 所有旧路径可用 |
| smoke test | ✅ 421 daily records |
| 结果等价 | ✅ 421 行完全一致 |

---

## 2. 文件变化汇总

### 2.1 新建文件

| 文件 | 用途 | 行数 |
|------|------|------|
| `myQuant/__init__.py` | 顶层包 | 1 |
| `myQuant/core/__init__.py` | calendar, config, schema wrapper | 70 |
| `myQuant/data/__init__.py` | models wrapper | 25 |
| `myQuant/data/models.py` | 10 个 Peewee ORM 模型 | 268 |
| `myQuant/news/__init__.py` | sources, recall wrapper | 20 |
| `myQuant/agent/__init__.py` | evaluator wrapper | 10 |
| `myQuant/scoring/__init__.py` | daily_aggregator wrapper | 25 |
| `myQuant/backtest/__init__.py` | report wrapper | 10 |
| `myQuant/pipeline/__init__.py` | BackfillPipeline wrapper | 10 |

### 2.2 修改文件

| 文件 | 变化 | 行数变化 |
|------|------|----------|
| `myQuant/news_ingestion/storage/sqlite.py` | 移除模型定义，改为从 data/models.py 导入 | 716 → 490 |
| `.gitignore` | 新增 .opencode/, .sisyphus-debug/, .pytest_cache/ | +3 行 |

### 2.3 归档文件

**archive/legacy_scripts/** (11 个):

| 文件 | 归档原因 |
|------|----------|
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

**archive/old_results/** (13 个):

| 文件/目录 | 归档原因 |
|-----------|----------|
| backtests/results/v0.21/ | v0.21 时代产物 |
| backtests/results/2026-05-12_*.md (×9) | v0.1 报告 |
| backtests/results/agent_news_v01_*.md (×2) | v0.1 报告 |
| backtests/results/audit_agent_exits.* | v0.1 审计 |
| backtests/results/cost_sensitivity.* | v0.1 分析 |
| backtests/results/ma_filter_results.* | v0.1 分析 |

**archive/experiments/** (2 个):

| 目录 | 归档原因 |
|------|----------|
| analysis/ | CATL 新闻分析 |
| qwen-benchmark/ | Qwen 模型基准测试 |

### 2.4 删除文件

| 文件/目录 | 删除原因 |
|-----------|----------|
| exports/ | 空目录 |
| .archive/ | 旧版 planning-with-files 产物 |
| .sisyphus-debug/ | Sisyphus 调试日志 |

---

## 3. 架构变化

### 3.1 新目录结构

```
myQuant/
├── __init__.py          # 顶层包
├── core/                # 基础设施 (calendar, config, schema)
├── data/                # 数据访问 (models, repositories)
├── news/                # 新闻处理 (sources, recall)
├── agent/               # LLM 评估 (evaluator)
├── scoring/               # 信号生成 (daily_aggregator)
├── backtest/            # 回测工具 (report)
├── pipeline/            # 编排 (BackfillPipeline)
└── news_ingestion/      # 原始模块 (v0.22)
```

### 3.2 Import 兼容性

```python
# 旧路径 (继续可用)
from myQuant.news_ingestion.contracts import AgentSignal
from myQuant.news_ingestion.storage import AgentNewsSqliteRepository
from myQuant.news_ingestion.scoring.daily_aggregator import run_v0_22_pipeline

# 新路径 (v0.23+)
from myQuant.core import AgentSignal
from myQuant.data.models import AgentSignalModel
from myQuant.news import RecallEngine
from myQuant.agent import DeepSeekNewsEvaluator
from myQuant.scoring import run_v0_22_pipeline
from myQuant.pipeline import BackfillPipeline
```

### 3.3 数据流

```
news/sources/ → news/recall/ → agent/llm/ → signal/scoring/ → backtest/reporting/
     ↓              ↓              ↓              ↓                ↓
  新闻拉取       清洗去重       LLM评估       信号聚合         回测报告
```

---

## 4. 顶层目录整理

### 4.1 最终结构

```
vnpy/
├── myQuant/              # ✅ Agent Quant Pipeline (已整理)
├── backtests/            # 回测脚本和结果
├── strategies/           # 策略实现
├── scripts/              # 工具脚本
├── archive/              # 归档 (旧脚本 + 实验)
│   ├── legacy_scripts/
│   ├── old_results/
│   └── experiments/
├── vnpy/                 # 上游框架 (不改)
├── docs/                 # 上游文档
├── tests/                # 上游测试
├── examples/             # 上游示例
│
├── .sisyphus/            # Sisyphus 计划
├── .agent-memory/        # Agent 记忆
├── .agents/              # Agent 配置
├── .claude/              # Claude 配置
├── .opencode/            # OpenCode 配置
├── .github/              # GitHub 模板
│
├── AGENTS.md             # Agent 规则
├── CLAUDE.md             # Claude 规则
├── PROJECT.md            # 项目概述
├── pyproject.toml        # 构建配置
└── README.md             # 上游 README
```

### 4.2 目录分类

| 类别 | 目录 | 状态 |
|------|------|------|
| **核心业务** | myQuant/, backtests/, strategies/, scripts/ | ✅ 活跃 |
| **归档** | archive/ | 📦 保留 |
| **上游框架** | vnpy/, docs/, tests/, examples/ | 🔒 只读 |
| **Agent 工具** | .sisyphus/, .agent-memory/, .agents/, .claude/, .opencode/ | ✅ 活跃 |
| **GitHub** | .github/ | 🔒 只读 |

### 4.3 不可合并的目录

| 目录 | 原因 |
|------|------|
| .agent-memory/ | opencode 硬编码 `$PROJECT_ROOT/.agent-memory/` |
| .opencode/ | opencode 项目级配置 |
| .agents/ | opencode 技能目录 |
| .claude/ | Claude 配置 |
| .sisyphus/ | Sisyphus hooks 查找 |
| .github/ | GitHub 模板 |

---

## 5. 关键资产保留

### 5.1 已验证的数据流

```
fetch_news.py → agent_raw_news
evaluate_news.py → agent_signal
generate_daily_signals.py → agent_daily_signal + JSON
run_matrix.py → backtest results
```

### 5.2 已跑通的策略实验结论

- v0.2 / v0.22 agent-enhanced MACD 回测结果
- 3 只股票 × 8 指标 × 7 模式矩阵
- daily_position_attribution 分析
- equity_reconciliation 对账

### 5.3 可复用的业务逻辑

- 新闻清洗 + 去重 (recall/engine.py)
- LLM 评估 (llm/evaluator.py)
- 事件聚合 + 每日信号 (scoring/)
- 回测接口 (run_matrix.py + strategies/)

### 5.4 可追溯的历史产物

- JSON 信号文件 (backtests/results/v0.22/signals/)
- DB 备份 (~/.vntrader/backups/)
- 回测结果 (matrix CSV, daily CSV)
- migration notes (docs/)

---

## 6. Known Issues

1. **v0.23c 跳过了部分拆分**: evaluator.py (450行), pipeline.py (358行), contracts.py (313行) 未拆分，因为行数可接受且拆分收益不大

2. **循环依赖**: myQuant/__init__.py 不能导入子模块，否则会触发循环依赖。需要通过子模块单独导入。

3. **strategies/ 和 backtests/ 未合并**: 这两个目录可以合并到 myQuant/backtest/，但需要更新大量 import 路径，留待后续处理。

---

## 7. 后续建议

### 7.1 短期 (可选)

1. 合并 strategies/ → myQuant/backtest/strategies/
2. 合并 backtests/ → myQuant/backtest/
3. 合并 scripts/ → myQuant/pipeline/

### 7.2 中期

1. 拆分 evaluator.py → agent/prompt_builder.py + agent/json_parser.py
2. 拆分 pipeline.py → pipeline/source_factory.py
3. 拆分 contracts.py → core/enums.py

### 7.3 长期

1. 新增股票池扩展
2. 策略优化
3. 新闻源扩展 (sina 接入)

---

## 8. 验收清单

| 标准 | 状态 |
|------|------|
| pytest 全部通过 | ✅ 52 passed |
| audit 无 CRITICAL 错误 | ✅ 23 passed |
| 600309.SSE smoke test 通过 | ✅ 421 records |
| 结果等价验证通过 | ✅ 421 行一致 |
| 旧 CLI 命令仍可用 | ✅ |
| 旧 JSON 兼容不破坏 | ✅ |
| agent_daily_signal persist 不破坏 | ✅ |
| trading_date 映射不破坏 | ✅ |
| 所有新 import 路径可用 | ✅ |
| 所有旧 import 路径可用 | ✅ |
