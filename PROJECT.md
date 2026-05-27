# PROJECT.md — vn.py + myQuant Agent Trading

> 新 session 启动时读取本文件即可了解项目全貌。

## 1. 环境

- **Conda**: `vnpy43`，Python 3.12
- **执行**: 所有命令加 `conda run -n vnpy43` 前缀
- **编码**: 避免 `__pycache__`/`.pyc` 污染，加 `PYTHONDONTWRITEBYTECODE=1`
- **pandas**: 固定 2.2.3

## 2. 目录结构

```
vnpy/                          ← 上游框架，不修改
myQuant/                       ← 我们的代码
  news_ingestion/              ← Agent News v0.1 核心模块
    contracts.py               ← 领域合约/枚举/AgentSignal
    storage/sqlite.py          ← 独立 SQLite（peewee）
    profiles/                  ← 10 只股票发现 & profile
    sources/{cninfo,eastmoney,eastmoney_legacy,cls}.py  ← 新闻源适配器
    recall/engine.py           ← 召回过滤/去重/available_at
    llm/evaluator.py           ← DeepSeek + Qwen 评估器
    pipeline.py                ← 离线回测管道 + tqdm 进度条
    reporting.py               ← Markdown 报告
    tests/                     ← 单元测试（63 passed, 4 skipped）
backtests/
  scripts/fetch_news.py            ← 新闻拉取（纯数据，无 LLM）
  scripts/evaluate_news.py         ← 语义分析（读 DB→评估→写信号）
  scripts/run_agent_news_backfill.py  ← 旧版一体式 CLI（保留）
  scripts/run_doublema_daily_all_db.py ← DoubleMA 回测
  strategies/                  ← 策略文件（开发用）
qwen-benchmark/                ← Qwen 模型基准测试
  scripts/bench_qwen_extraction.py
  scripts/bench_llm_compare.py
.sisyphus/plans/               ← 实施计划（追踪）
.sisyphus/notepads/            ← 学习笔记（追踪）
```

## 3. 数据库

| 用途 | 路径 | 说明 |
|------|------|------|
| 市场数据（日线） | `~/.vntrader/database.db` | 只读，vn.py TuShare 下载 |
| Agent News (旧) | `~/.vntrader/agent_news_{symbol}.db` | 旧版，内容已空，禁止写入 |
| Agent News (新) | `~/.vntrader/agent_news_em_{symbol}.db` | 东财搜索源，文本内容 |

当前数据：万华化学 617 raw (599 mapped)，招商银行 833 raw (820 mapped)，寒武纪 967 raw (961 mapped)。全部 2020-01 ~ 2026-05。

## 4. 测试

```bash
# 全量确定性测试（无网络需求）
PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q

# 实时源冒烟测试（需网络）
AGENT_NEWS_LIVE_TEST=1 PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_live_sources.py -v

# 已知道非阻塞问题：tests/test_alpha101.py 缺 polars 依赖
```

## 5. 新闻源

### Eastmoney 搜索（东财）— 个股新闻

- **端点**: `search-api-web.eastmoney.com/search/jsonp`
- **类型**: `cmsArticleWeb`（财经新闻摘要，非公告 PDF）
- **内容**: 纯文本，平均 120-140 字，记者筛选过的核心信息
- **覆盖**: 2015-2026，每月 3-30 条，近期更密
- **速度**: ~70s/股拉完全量（1000 条 API 上限）
- **适配器**: `myQuant/news_ingestion/sources/eastmoney.py` → `EastmoneyNewsSource`
- **旧版已禁用**: 重命名为 `eastmoney_legacy.py`（公告 PDF 源，正文全空）

### CNInfo（巨潮）— 官方公告

- 仅合规公告（年报、董事会决议），一年 ~200 条
- 正文为 PDF，需 pdfplumber 提取 → **当前未启用**
- **适配器**: `myQuant/news_ingestion/sources/cninfo.py`

### CLS（财联社）— 实时快讯

- 实时电报，API 按时间倒排，不适合历史回填

## 6. 工作流

新闻拉取和语义分析已拆分为两个独立脚本：

### 6.1 拉取新闻 → `fetch_news.py`

```bash
conda run -n vnpy43 python backtests/scripts/fetch_news.py \
  --start 2020-01-14 --end 2026-05-15 \
  --symbols 600309.SSE,600036.SSE,688256.SSE \
  --sources eastmoney \
  --agent-db-path ~/.vntrader/agent_news_em_600309.db
```

### 6.2 语义分析 → `evaluate_news.py`

三模型独立运行，同一批新闻分别评估：

```bash
# DeepSeek V4 Flash（默认，走 api.deepseek.com）
export DEEPSEEK_API_KEY=sk-xxx
conda run -n vnpy43 python backtests/scripts/evaluate_news.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --provider deepseek --workers 3

# Qwen3.5 Plus（走 opencode.ai API）
export OPENCODE_GO_API_KEY=sk-xxx
conda run -n vnpy43 python backtests/scripts/evaluate_news.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --provider opencode-go --model qwen3.5-plus --workers 2

### 6.3 ⚠️ 语义分析 Thinking 规则

**语义分析任务中，所有模型默认关闭 thinking/reasoning。** 原因：我们的 prompt 要求"只输出合法 JSON"，不需要推理链。开启 thinking 会导致输出 token 膨胀 10-26 倍（推理 token 占 93%+），严重拖慢速度。

| 模型 | 关闭方式 | 效果 |
|------|---------|------|
| DeepSeek | `extra_body={"thinking": {"type": "disabled"}}` | 127 tokens/条 |
| Qwen3.5 Plus | `extra_body={"enable_thinking": False}` | 146 tokens/条 |
| MiniMax M2.5 | 无 thinking，不需要关 | 360 tokens/条（tokenizer 不友好中文） |

**新模型接入检查表**：先跑 10 条 → 查 `token_usage` 里有无 `reasoning_tokens` → 有就关。token/char 比率超过 1.0 也要排查。

# MiniMax M2.5（走 opencode.ai API，json_object 模式不可用）
conda run -n vnpy43 python backtests/scripts/evaluate_news.py \
  --db-path ~/.vntrader/agent_news_em_600309.db \
  --provider opencode-go --model minimax-m2.5 --workers 2
```

### 6.4 旧版 CLI（保留）

`run_agent_news_backfill.py` 仍可用于 fetch+LLM 一体式回填，但推荐用上述拆分脚本。

## 7. LLM Provider 配置

| Provider | 端点 | API Key | 模型 |
|----------|------|---------|------|
| `deepseek` | `api.deepseek.com/v1` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| `opencode-go` | `opencode.ai/zen/go/v1` | `OPENCODE_GO_API_KEY` | `qwen3.5-plus`, `minimax-m2.5`, `deepseek-v4-flash` |

模型特性：
- **DeepSeek**: `json_object` ✅, thinking 已关闭 (`extra_body`)
- **Qwen3.5 Plus**: `json_object` ✅, thinking 已关闭 (`enable_thinking=False` via `extra_body`)
- **MiniMax M2.5**: `json_object` ❌ (400), `extra_body` ❌ (400), 无 thinking

## 8. CTA 策略部署

- 策略源文件: `backtests/strategies/`（开发）
- 部署目标: `~/.vntrader/strategies/`（vn.py 引擎扫描此目录）
- 回测: `conda run -n vnpy43 python backtests/run_*.py`
- 策略类继承 `CtaTemplate`，文件命名下划线，类名驼峰

## 9. 回测约定

1. 脚本放 `backtests/scripts/`，不删
2. 结果 Markdown 放 `backtests/results/`，命名 `YYYY-MM-DD_<strategy>_<params>_<scope>.md`
3. 必须写清：策略类、参数、数据源、标的、时间、周期、手续费、滑点、合约乘数、初始资金

## 10. 已知待办

- [ ] 三模型语义分析：对万华化学/招商银行/寒武纪跑 DeepSeek + Qwen3.5 Plus + MiniMax M2.5
- [ ] 补齐万华化学 DeepSeek/Qwen 覆盖面至 599 条 mapped（当前 DeepSeek 565, Qwen 516）
- [ ] Prompt 接入 StockProfile 数据（名称、行业、产品、上下游）— 当前写死"未知"
- [ ] CNInfo PDF 提取方案评估（pdfplumber 已安装，待接入）
