# AGENTS.md — myQuant Agent Quant Pipeline

> `vnpy/` 只读, `myQuant/` 可改. 本文件覆盖 pipeline, data, agent, scoring 等全部子模块.

## OVERVIEW
Custom agent quant pipeline (~7.9K lines) for news-driven trading signals on top of VeighNa v4.4.0. Architecture: 9 sub-packages where 7 are thin alias facades re-exporting from `news_ingestion/`. Only `data/` (Peewee ORM models) and `news_ingestion/` (core logic) have original code.

## STRUCTURE
```
myQuant/
├── run.py                      # 启动入口 (GUI: CTA + Backtester + DataManager + PaperAccount)
├── news_ingestion/             # ★ 核心模块 (~4.5K行, 9子目录)
│   ├── scripts/                # CLI入口: fetch, evaluate, generate, backfill
│   ├── sources/                # 数据源 (EastMoney, Sina, CLS, CNInfo + legacy)
│   ├── storage/                # SQLite仓储 (AgentNewsSqliteRepository, ~490行) + 自动备份
│   ├── llm/                    # LLM评估 (DeepSeekNewsEvaluator, ~450行)
│   ├── scoring/                # 评分/聚合/去重/集成 (5 files)
│   ├── recall/                 # 新闻召回引擎
│   ├── profiles/               # 股票档案管理
│   ├── pipeline.py             # BackfillPipeline 编排
│   ├── contracts.py            # 核心数据类型 (dataclasses/enums)
│   └── tests/                  # 17 test files (~3.4K行, pytest)
├── data/models.py              # Peewee ORM: 10表, agent_前缀, upsert模式
├── agent/                      # → news_ingestion.llm (alias facade)
├── backtest/                   # → news_ingestion.reporting (alias facade)
├── core/                       # → news_ingestion contracts + calendar + scoring.config
├── news/                       # → news_ingestion.sources + recall
├── pipeline/                   # → news_ingestion.pipeline
├── scoring/                    # → news_ingestion.scoring
└── strategies/                 # placeholder (空)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 启动入口 | `run.py` | GUI 启动, 参考 AGENTS.md root |
| 数据管道 | `news_ingestion/scripts/` | fetch → evaluate → generate → backfill |
| 数据抓取 | `news_ingestion/sources/` | BaseNewsSource → EastMoney/Sina/CLS/CNInfo |
| 数据库操作 | `news_ingestion/storage/sqlite.py` | AgentNewsSqliteRepository, 构造时自动备份 |
| ORM模型 | `data/models.py` | 10个Peewee模型, agent_前缀, TextField存JSON |
| LLM评估 | `news_ingestion/llm/evaluator.py` | DeepSeekNewsEvaluator, API key from env |
| 信号生成 | `news_ingestion/scoring/` | row_scorer → daily_aggregator → ensemble |
| Pipeline编排 | `news_ingestion/pipeline.py` | BackfillPipeline, 3阶段: fetch→evaluate→aggregate |
| 核心契约 | `news_ingestion/contracts.py` | BackfillConfig, 数据类型, 枚举 |
| 股票档案 | `news_ingestion/profiles/stock_profiles.py` | 默认股票档案, 代码/名称/交易所映射 |
| 测试 | `news_ingestion/tests/` | pytest, tmp_path, 无conftest.py |

## CONVENTIONS
- **Alias facade**: agent/, backtest/, core/, news/, pipeline/, scoring/ 均为 thin re-export wrappers → 实际逻辑在 `news_ingestion/`
- **Upsert only**: 所有 `save_*` 方法使用 Peewee `insert().on_conflict(...)` — 绝不 DELETE/UPDATE
- **TextField for JSON**: 数据库 JSON 字段用 Peewee `TextField` + `json.dumps/json.loads` 序列化
- **Auto-backup**: `AgentNewsSqliteRepository()` 构造时自动备份 (10分钟限流), 备份到 `~/.vntrader/backups/`
- **argparse CLI**: 管道脚本使用 argparse (非 click/typer)
- **loguru logging**: 非 stdlib logging; `from vnpy.trader.logger import logger`
- **Dataclass contracts**: contracts.py 使用 @dataclass + `__post_init__` 定义全部数据类型
- **Env vars only for keys**: DEEPSEEK_API_KEY, OPENCODE_GO_API_KEY, AGENT_NEWS_LIVE_TEST

## ANTI-PATTERNS
- **禁止**: `myQuant/__init__.py` 导入子模块 — 循环导入风险, 始终从具体子模块导入
- **禁止**: 无备份执行 DELETE/DROP — 必须 backup → SELECT COUNT → 用户确认
- **禁止**: API密钥写入日志/代码/数据库 — 仅从环境变量读取
- **禁止**: 在测试中调用实时API — 使用 `AGENT_NEWS_LIVE_TEST=1` 门控
- **禁止**: 静默跳过失败源 — 失败源必须记录到日志
- **避免**: 在回调函数中下单 (on_init/on_load)
- **避免**: 修改 `vnpy/` 上游代码 — 所有改动限 `myQuant/`

## NOTES
- 数据库路径: `~/.vntrader/agent_news*.db` (默认 `agent_news.db`), 支持 `:memory:` 测试
- 双DB系统: 上游 `database.db` (行情K线) + myQuant `agent_news.db` (新闻管道)
- DeepSeekNewsEvaluator 支持多provider (deepseek, llama_cpp, opencode-go)
- Pipeline 3阶段: fetch_news → evaluate_news → generate_daily_signals
- 策略信号从 `daily_agent_signal` 表读取, 经 JSON 导出到回测引擎
- 回测引擎 (`BacktestingEngine`) 来自 `vnpy.alpha`, 非 `vnpy.trader`
