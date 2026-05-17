Mac + vn.py 4.3.0
Python 3.12
pandas 固定 2.2.3
vn.py 数据库先用 SQLite
TuShare datafeed 可下载日线
A股交易所代码：SSE/SZSE/BSE

## OpenCode 回测约定

1. 所有回测、数据检查和 vn.py 相关脚本运行都必须使用 `vnpy43` conda 环境，例如：`conda run -n vnpy43 python <script.py>`。
2. 回测脚本统一保存在 `backtests/scripts/`，不要写临时脚本后删除；后续新策略、新参数、新批量任务都在该目录下新增或复用脚本。
3. 每次回测结果统一保存为 Markdown 到 `backtests/results/`，文件名建议使用 `YYYY-MM-DD_<strategy>_<params>_<scope>.md`，内容至少包含回测设置、结果表格和简短结论。
4. 回测结果中的设置必须写清楚：策略类、参数、数据库/数据源、标的范围、时间范围、周期、手续费、滑点、合约乘数/size、pricetick、初始资金。
5. 当前数据库默认位置为 `~/.vntrader/database.db`，当前本地日线数据来自 SQLite。

## Agent News v0.1 — 新闻驱动 Agent 信号模块

### 模块位置
- 代码: `myQuant/news_ingestion/`
- 数据库: `~/.vntrader/agent_news.db`（独立于市场数据 `database.db`）
- 回测脚本: `backtests/scripts/run_agent_news_backfill.py`
- 回测报告: `backtests/results/<date>_agent_news_v01_*.md`

### 环境要求
- 必须使用 `conda run -n vnpy43` 执行

### 快速开始

1. 运行全量单元测试（无需网络）：
```bash
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q
```

2. Dry-run 验证 pipeline：
```bash
conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py \
  --start 2026-05-01 --end 2026-05-07 \
  --symbols 300750.SZSE,600519.SSE \
  --recall-strength low --dry-run --skip-llm \
  --report-path backtests/results/agent_news_v01_dry_run.md
```

3. 执行离线回测（抓取新闻 + 召回过滤）：
```bash
conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py \
  --start 2021-01-01 --end 2026-05-08 \
  --symbols-from-market-db \
  --recall-strength medium --skip-llm \
  --report-path backtests/results/$(date +%F)_agent_news_v01_10stocks_5y.md
```

4. 启用 LLM 评估（需要 DeepSeek API Key）：
```bash
export DEEPSEEK_API_KEY=your_deepseek_api_key_here
conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py \
  --start 2025-01-01 --end 2026-05-08 \
  --symbols 300750.SZSE \
  --recall-strength medium \
  --report-path backtests/results/$(date +%F)_agent_news_v01_with_llm.md
```

### 新闻源策略
- **CNInfo（巨潮）**：必须源，上市公司公告，metadata优先 + PDF尽力提取
- **CLS（财联社）**：尽力源，电报快讯，注意反爬签名
- **Eastmoney（东方财富）**：尽力源，股票/行业新闻，覆盖不完整不保证

### 架构模块
- `contracts.py` — 领域合约、枚举、AgentSignal
- `storage/sqlite.py` — 独立 SQLite 存储（peewee），幂等 upsert
- `profiles/` — 10 只股票发现 & 关键词 profile
- `sources/` — 新闻源适配器（cninfo/cls/eastmoney）
- `recall/` — 召回过滤、去重、available_at 防回测未来信息
- `llm/` — DeepSeek 评估器（fake-client TDD，schema 校验，重试）
- `pipeline.py` — 离线回测管道
- `reporting.py` — Markdown 报告生成

### 注意事项
- `agent_news.db` 独立于 `~/.vntrader/database.db`，不要混用
- `DEEPSEEK_API_KEY` 不得写入报告或日志，测试用 fake client
- v0.1 仅离线回测，无实时调度/策略执行
- API Key 仅在 LLM 实时阶段需要，dry-run/skip-llm 不强制

## CTA 策略开发与部署

### 策略文件位置

VNPY 的 `MainEngine` 启动时执行 `os.chdir(TRADER_DIR)` 将工作目录切到 `~/.vntrader/`。CTA 引擎从 `{CWD}/strategies/` 扫描策略类。

**自定义策略必须部署到：`~/.vntrader/strategies/`**

不是以下位置（前端不扫或属于框架内置）：
- ~~`vnpy/strategies/`~~ （CWD 已被引擎改为 `~/.vntrader/`）
- ~~`vnpy_ctastrategy/strategies/`~~ （内置策略目录，`pip` 升级会覆盖）
- ~~`myQuant/strategies/`~~ （同上）

### 部署

```bash
cp vnpy/strategies/*.py ~/.vntrader/strategies/
```

开发时在 `vnpy/strategies/` 编辑，部署时复制到 `~/.vntrader/strategies/`，重启前端生效。

### 当前策略

| 策略 | 源文件 | 描述 |
|------|------|------|
| MacdStrategy | strategies/macd_strategy.py | MACD 金叉死叉，支持仓位比例和金字塔加仓 |
| CatlMultiSignalStrategy | strategies/catl_multi_signal.py | RSI + MACD + 成交量多信号组合 |

### 策略开发规范

1. 继承 `CtaTemplate`（或 `TargetPosTemplate`），导入自 `vnpy_ctastrategy`
2. `author`、`parameters`、`variables` 必须声明为类属性
3. `__init__` 签名必须匹配 `(self, cta_engine, strategy_name, vt_symbol, setting)`
4. 文件命名下划线模式（`macd_strategy.py`），类名驼峰模式（`MacdStrategy`）
5. 回测通过 `conda run -n vnpy43 python backtests/run_*.py` 执行
