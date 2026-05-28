# AGENTS.md — vnpy/myQuant Agent Trading

**Generated:** 2026-05-28T03:08:48Z
**Commit:** 48d51bde
**Branch:** master

> 所有任务默认遵守。非关键工作可自行判断，关键工作和破坏性操作必须走完流程。

## OVERVIEW
VeighNa (vnpy) v4.4.0 — Python 量化交易系统开发框架，with custom myQuant agent pipeline for news-driven trading signals. Core stack: Python 3.12, PySide6, numpy/pandas, PyTorch/LightGBM (alpha), SQLite (Peewee ORM).

## STRUCTURE
```
vnpy/               # 上游框架，不改 (published wheel, hatchling)
├── trader/         # 核心交易引擎 (MainEngine, BaseGateway, BaseApp, OMS)
├── event/          # 事件驱动引擎 (EventEngine, 145行)
├── alpha/          # AI/ML 量化投研 (dataset → model → strategy → lab)
├── chart/          # K线图表 (PyQt6)
└── rpc/            # 跨进程通讯 (ZMQ)
myQuant/            # 我们的代码 (source-only, ~7.9K行)
├── news_ingestion/ # ★ 核心模块 (~4.5K行): sources, storage, llm, scoring, recall
├── data/           # ORM models (Peewee, 10 tables, agent_ prefix)
├── agent/          # → news_ingestion.llm (alias)
├── backtest/       # → news_ingestion.reporting (alias)
├── core/           # → news_ingestion contracts + calendar (alias)
├── news/           # → news_ingestion.sources + recall (alias)
├── pipeline/       # → news_ingestion.pipeline (alias)
├── scoring/        # → news_ingestion.scoring (alias)
└── strategies/     # placeholder (空)
strategies/         # standalone 策略包 (source-only): MacdAgentStrategy, TechAgentStrategy
backtests/          # 回测脚本 + 结果 (no __init__.py)
scripts/            # 运维脚本 (audit_current_pipeline.py)
examples/           # vnpy示例 + alpha_research notebooks
docs/pipeline/      # 内部文档: pipeline contracts, audits, migration
archive/            # git-ignored, 历史参考, 勿用
.sisyphus/          # Agent planning & execution (plans/, drafts/, evidence/)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 启动 myQuant | `myQuant/run.py` | `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python myQuant/run.py` |
| 启动 vnpy GUI | `examples/veighna_trader/run.py` | CTP + CTAStrategy + CtaBacktester + DataManager |
| 无界面运行 | `examples/no_ui/run.py` | Headless CTA daemon, multi-process |
| 新闻数据管道 | `myQuant/news_ingestion/scripts/{fetch,evaluate,generate}*.py` | 3-stage: fetch → LLM → daily signals |
| 回测矩阵 | `backtests/run_matrix.py` | `--phase {1,2,3}` 技术×代理矩阵 |
| Pipeline审计 | `scripts/audit_current_pipeline.py` | 17项检查, DB+signal文件 |
| 策略开发 | `strategies/` | CtaTemplate基类, MacdAgentStrategy参考 |
| LLM评估 | `myQuant/news_ingestion/llm/evaluator.py` | DeepSeekNewsEvaluator |
| 数据模型 | `myQuant/data/models.py` | Peewee ORM, 10表, agent_前缀 |
| 数据库仓储 | `myQuant/news_ingestion/storage/sqlite.py` | AgentNewsSqliteRepository |
| Pipeline契约 | `docs/pipeline/pipeline_contract_v0_22.md` | I/O schema, dedup, 版本追踪 |
| 回测真实度 | `docs/backtest/realism_audit.md` | 手续费/滑点/涨跌停/流动性/成交价/市场冲击 |
| 策略审计 | `docs/backtest/strategy_matrix_audit_v0_25.md` | 策略类、指标、mode 完整清单 |
| AI投研 | `examples/alpha_research/research_workflow_lgb.ipynb` | LightGBM研究流程 |
| CI/CD | `.github/workflows/pythonapp.yml` | ruff → mypy → uv build (windows-latest) |

## COMMANDS

```bash
# 启动
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python myQuant/run.py

# 回测
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/run_matrix.py --phase 1
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/run_macd_agent_tests.py --symbol 300750.SZSE

# 数据管道
python myQuant/news_ingestion/scripts/fetch_news.py --start 2026-01-01 --end 2026-05-01 --symbols XXX --agent-db-path ~/.vntrader/agent_news.db
python myQuant/news_ingestion/scripts/evaluate_news.py --db-path ~/.vntrader/agent_news.db --provider deepseek
python myQuant/news_ingestion/scripts/generate_daily_signals.py --db-path ~/.vntrader/agent_news.db --vt-symbol 300750.SZSE

# 审计
python scripts/audit_current_pipeline.py

# Lint & Type Check
ruff check .
mypy vnpy

# 安装
pip install -e .[alpha,dev]               # 可编辑安装(含ML依赖)
bash install_osx.sh                        # macOS

# 测试
pytest                                     # 全部测试
pytest myQuant/                            # myQuant only
AGENT_NEWS_LIVE_TEST=1 pytest myQuant/news_ingestion/tests/test_live_sources.py -v
```

## CONVENTIONS
- **Lint**: ruff (B, E, F, UP, W), E501 ignored (行长度不限制)
- **Type check**: mypy strict — `disallow_untyped_defs=true`, `disallow_incomplete_defs=true`
- **Types**: Python 3.10+ union syntax (`str | None`, not `Optional[str]`)
- **Imports**: stdlib → third-party → local; `collections.abc` > `typing`; relative within package
- **Docs**: """""" constructor docstrings (vnpy convention); English docstrings, short sentences
- **Names**: PascalCase classes, snake_case functions, SCREAMING_SNAKE constants, `_private` attrs
- **Data**: @dataclass + __post_init__ for computed fields (e.g. vt_symbol)
- **ABC**: ABC/ABCMeta for base classes (BaseGateway, BaseEngine, AlphaModel)
- **i18n**: `from .locale import _`; `_("Chinese text")` pattern
- **Logging**: loguru (not stdlib), format: `{time} | {level} | {gateway} | {message}`
- **ORM**: Peewee (myQuant), upsert for all save operations, `TextField` for JSON blobs
- **DB**: Two systems — upstream `BaseDatabase` (raw SQL) + myQuant `AgentNewsSqliteRepository` (Peewee)
- **Backup**: Auto-backup on `AgentNewsSqliteRepository` construction, 10min rate-limit, SQLite native API
- **Config**: `~/.vntrader/vt_setting.json` (JSON), no .env/.ini/.yaml
- **Env vars**: API keys only (DEEPSEEK_API_KEY, OPENCODE_GO_API_KEY), test flag (AGENT_NEWS_LIVE_TEST)
- **Build**: hatchling, only `vnpy/` packaged; `myQuant/` and `strategies/` source-only

## UNIQUE STYLES
- `vt_` prefix computed IDs: `vt_symbol = f"{symbol}.{exchange.value}"`
- Event strings: `"eTick."`, `"eTrade."` (e + PascalCase + .)
- Empty `""""""` constructor docstrings — project-wide convention
- `# noqa` for side-effect imports (ruff false positives)
- `TYPE_CHECKING` guard for circular import avoidance
- Alias facade pattern in myQuant: 7 sub-packages re-export from `news_ingestion/`

## NOTES
- `vnpy/` 只读, `myQuant/` 可改 — AGENTS.md 明确边界
- `archive/` git-ignored, 历史参考, 不要搜索或修改
- `strategies/` 和 `backtests/` 不在 pyproject.toml build 中 — 仅源码存在
- 双数据库系统: 行情库 (`database.db`, `BaseDatabase`) + 代理库 (`agent_news*.db`, Peewee)
- `AgentNewsSqliteRepository` 构造时自动备份到 `~/.vntrader/backups/`
- llama.cpp 模型路径: `/Users/kai/.lmstudio/models/lmstudio-community/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf`
- `myQuant/__init__.py` 不可导入子模块 — 循环导入风险
- 回测引擎 (`BacktestingEngine`) 来自 vnpy_ctastrategy (CTA), 非 vnpy.alpha
- 策略信号从 `~/.vntrader/agent_news.db` 读取 `agent_daily_signal` 表
- 回测真实度审计: [docs/backtest/realism_audit.md](docs/backtest/realism_audit.md)

## NEWS SOURCES

| Source | Endpoint | Content | Speed | Status |
|--------|----------|---------|-------|--------|
| Eastmoney | `search-api-web.eastmoney.com` | 财经新闻摘要, 120-140字 | ~70s/股全量 | ✅ 主力 |
| Sina | `vip.stock.finance.sina.com.cn` | 个股新闻全文, 需逐篇爬取 | 慢 | ✅ 已接入 |
| CNInfo | 巨潮资讯网 | 官方公告 (PDF) | — | ⚠️ 含pdfplumber依赖, 未启用 |
| CLS | 财联社 | 实时电报, API时间倒排 | — | ⚠️ 不适合历史回填 |

## LLM PROVIDERS

| Provider | Endpoint | Key Env | Default Model | json_object |
|----------|----------|---------|---------------|:---:|
| deepseek | `api.deepseek.com/v1` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` | ✅ |
| opencode-go | `opencode.ai/zen/go/v1` | `OPENCODE_GO_API_KEY` | `qwen3.5-plus` | ✅ |
| llama_cpp | localhost:8080 | — | Qwen3.6-35B-A3B | ⚠️ |

## KNOWN TODOS
- [x] Prompt 接入 StockProfile + company_archetype
- [x] v0.25 strategy matrix + buy_and_hold + reporting
- [ ] CNInfo PDF 提取方案评估
- [ ] `both_consensus` 和 `macd_confirmed` 策略结果完全相同 — 审计参数差异

## Rule 1 — Think Before Coding
- 明确假设，不确定就问，别猜。
- 歧义时列出多种解读，让用户选。
- 有更简单的方案就提出来，不要默默实现复杂的。
- 卡住就说卡住了。讲清楚到底哪里不懂。

## Rule 2 — Simplicity First
- 最少代码解决问题，不加推测性功能。
- 不实现用户没要的东西。单次使用的代码不抽象。
- 自测：一个资深工程师看了会说「搞复杂了」？是就简化。

## Rule 3 — Surgical Changes
- 只碰你要改的。清理也只清你自己造成的。
- 不"顺手优化"相邻代码、注释、格式。
- 不重构没坏的东西。风格对齐现有代码。

## Rule 4 — Goal-Driven Execution
- 先定成功标准，再循环直到达标。
- 不是按步骤机械执行，而是盯着目标迭代。
- 强成功标准 = 能独立判断是否完成，不需要用户来验。

## Rule 5 — Agent for Judgment, Code for Determinism
- 用 AI 做：分类、起草、总结、提取、架构决策。
- 用代码/工具做：路由、重试、确定性变换、批量操作。
- 能用 `grep`/`python` 一行解决的事，不要上 agent。

## Rule 6 — Context Budget Awareness
- 主会话上下文有限。并行工作用 `task(run_in_background=true)`。
- 探索类工作优先丢给 `explore`/`librarian` agent。

## Rule 7 — Surface Conflicts, Don't Average
- 两个模式矛盾时，选一个（偏更新的/更经过验证的）。
- 解释为什么选它，标记另一个待清理。
- 不糅合矛盾的方案。

## Rule 8 — Read Before You Write
- 加代码前，先读：exports、直接调用方、共享工具函数。
- "看起来应该不相关"很危险。不确定为什么代码是当前结构，就问。

## Rule 9 — Tests Verify Intent
- 测试要编码 WHY（业务逻辑为什么这样），不只是 WHAT（代码做了什么）。
- 业务逻辑变了但测试不挂 → 测试写错了。

## Rule 10 — Checkpoint After Every Significant Step
- 每完成一个逻辑单元：总结做了什么、验证了什么、还剩什么。
- 用 todowrite 跟踪进度，不要让用户猜你在干嘛。
- 如果你自己都说不清当前状态 → 停下来理清楚。

## Rule 11 — Match the Codebase, Even If You Disagree
- 内部代码：一致性 > 个人品味。
- 如果你真心认为某条约定有害，提出来讨论。不要默默另搞一套。

## Rule 12 — Fail Loud
- "完成"但悄悄跳过了什么 → 不算完成。
- "测试通过"但跳过了一些 → 不算通过。
- 默认暴露不确定性，不要藏。

---

## Project-Specific Constraints

### Database Safety
- **Iron Law**: 任何 DELETE/DROP/TRUNCATE 必须先 (1) 备份 → (2) SELECT COUNT 预览 → (3) 用户确认。
- 生产库路径: `~/.vntrader/agent_news*.db`。参考 `safe-db-operations` skill。
- 备份机制: `AgentNewsSqliteRepository` 构造时自动备份（10 分钟限流），备份存 `~/.vntrader/backups/`。

### Environment
- Conda env: `vnpy43`, Python 3.12
- 命令前缀: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43`
- pandas 固定 2.2.3

### Codebase Boundaries
- `vnpy/` — 上游框架，不改。
- `myQuant/` — 我们的代码。
- `.sisyphus/plans/` — 实施计划，实施前先看。

### Directory Discipline
- **禁止**在项目根目录下未经允许创建新目录。所有新文件放入已有目录结构（`myQuant/`、`strategies/`、`backtests/`、`scripts/`、`docs/`、`examples/`、`.sisyphus/`），或事先征得用户同意。

### Agent Delegation
- 多步骤任务 → 先写计划（`.sisyphus/plans/`），再委托。
- 探索类 → `explore`/`librarian` agent，后台并行。
- 实现类 → `unspecified-high` category + 相关 skills。
- 架构决策 → `oracle` agent。
