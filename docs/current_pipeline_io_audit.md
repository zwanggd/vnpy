# Agent Quant Pipeline I/O Audit

> **Audit Date**: 2026-05-27
> **Purpose**: 在重构模块化 pipeline 之前，完整梳理当前系统每个阶段的真实输入、输出、字段、文件路径、数据库表、主键、依赖关系和潜在 silent bug。

---

## 1. Current Pipeline Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Phase 1        │    │  Phase 2        │    │  Phase 3        │    │  Phase 4        │
│  News Ingestion │───▶│  LLM Evaluation │───▶│  Daily Signal   │───▶│  Backtest       │
│                 │    │                 │    │  Generation     │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                      │                      │                      │
         ▼                      ▼                      ▼                      ▼
   agent_raw_news         agent_signal          JSON files            Temp SQLite
   agent_news_symbol      agent_llm_run         (v0.2/v0.22)         → Strategy
   agent_stock_profile    agent_llm_output                            → Metrics
```

### 数据库位置

| 数据库 | 路径 | 用途 |
|--------|------|------|
| Market DB | `~/.vntrader/database.db` | 日线行情（只读） |
| Agent News DB | `~/.vntrader/agent_news_em_{symbol}.db` | 新闻 + 信号（per-stock） |

### 当前支持的股票（12只）

| vt_symbol | 名称 | 行业 |
|-----------|------|------|
| 000333.SZSE | 美的集团 | 家电/智能制造 |
| 002475.SZSE | 立讯精密 | 消费电子/苹果产业链 |
| 002594.SZSE | 比亚迪 | 新能源汽车/动力电池 |
| 300750.SZSE | 宁德时代 | 新能源/动力电池/储能 |
| 600036.SSE | 招商银行 | 银行/零售金融 |
| 600276.SSE | 恒瑞医药 | 医药/创新药 |
| 600309.SSE | 万华化学 | 化工/聚氨酯/MDI |
| 600519.SSE | 贵州茅台 | 白酒/高端消费 |
| 601318.SSE | 中国平安 | 保险/金融 |
| 601899.SSE | 紫金矿业 | 有色金属/黄金/铜 |
| 688256.SSE | 寒武纪 | 半导体/AI 芯片 |
| 600900.SSE | 长江电力 | 电力/水力发电 |

---

## 2. Phase 1: News Ingestion I/O

### 2.1 新闻输入来源

| Source | 状态 | API 端点 | source_category |
|--------|------|----------|-----------------|
| Eastmoney | **ACTIVE** | `search-api-web.eastmoney.com/search/jsonp` | FINANCIAL_NEWS |
| CLS | **ACTIVE** | `www.cls.cn/nodeapi/telegraphList` | FLASH |
| CNInfo | **ACTIVE** | `www.cninfo.com.cn/new/hisAnnouncement/query` | ANNOUNCEMENT |
| Sina | **DEFINED** (not in factory) | `vip.stock.finance.sina.com.cn` | FINANCIAL_NEWS |
| Eastmoney Legacy | **DEPRECATED** | announcement endpoint | N/A |

**注意**: `Source.SINA_FINANCE` 在枚举中已定义且有完整适配器，但未在 `pipeline.py` 的 `_default_source_factory` 中映射。

### 2.2 Raw News 表 (`agent_raw_news`)

| 字段 | 类型 | Nullable | 说明 |
|------|------|----------|------|
| id | INTEGER | NO | 主键，AUTOINCREMENT |
| source | TEXT | YES | 枚举值: cninfo, cls_telegraph, eastmoney, sina_finance |
| source_category | TEXT | YES | 枚举值: announcement, flash, financial_news, etc. |
| source_item_id | TEXT | YES | 源端的唯一ID |
| url | TEXT | YES | 新闻URL |
| title | TEXT | NO | 标题 |
| content | TEXT | YES | 正文 |
| summary | TEXT | YES | 摘要 |
| published_at | DATETIME | YES | 原始发布时间 |
| discovered_at | DATETIME | YES | 发现时间 |
| fetched_at | DATETIME | YES | 拉取时间 |
| available_at | DATETIME | YES | 可用时间（由RecallEngine计算） |
| raw_payload_json | TEXT | YES | 原始JSON负载 |
| content_hash | TEXT | NO | SHA256(title + content) |
| body_status | TEXT | YES | text/fetched/extracted/failed |
| language | TEXT | YES | 默认 'zh' |
| created_at | DATETIME | YES | 入库时间 |

**主键**: `id`
**去重键**: `(source, source_item_id)`, `(source, content_hash)`
**索引**: `published_at`

### 2.3 News Symbol 映射表 (`agent_news_symbol`)

| 字段 | 类型 | Nullable | 说明 |
|------|------|----------|------|
| id | INTEGER | NO | 主键，AUTOINCREMENT |
| raw_news_id | INTEGER | YES | 关联 agent_raw_news.id |
| vt_symbol | TEXT | YES | 股票代码 |
| symbol | TEXT | YES | 纯数字代码 |
| exchange | TEXT | YES | 交易所 |
| relation_hint | TEXT | YES | 关系类型枚举 |
| mapping_method | TEXT | YES | direct/alias/keyword/industry/macro_policy |
| mapping_confidence | FLOAT | YES | 映射置信度 |
| keywords_matched_json | TEXT | YES | 匹配的关键词JSON |

**主键**: `id`
**去重键**: `(raw_news_id, vt_symbol)`
**索引**: `vt_symbol`

### 2.4 时间字段处理

```
Source Adapter → published_at = 从源解析
                available_at = None (所有4个适配器均未设置)
                       ↓
RecallEngine._available_at():
  - datetime类型 → published_at + 5分钟
  - date类型 → datetime(date, 15:00:00)  # 收盘时间
  - None → 跳过该新闻
                       ↓
LLM Evaluator:
  available_at = news_item.available_at or mapped_news.available_at
  trading_date = available_at.date().isoformat()
                       ↓
AgentSignal:
  trading_date 存为 TEXT (ISO date string)
```

### 2.5 去重逻辑

1. **主去重**: `(source, source_item_id)` - 源端唯一ID
2. **备用去重**: `(source, content_hash)` - 内容哈希
3. **近似去重**: `RecallEngine._near_deduplicate()`
   - 键: `(normalized_title[:40], published_at.date(), url.hostname)`
   - 防止同一新闻的不同URL重复入库

---

## 3. Phase 2: LLM Evaluation I/O

### 3.1 AgentSignal Schema (contracts.py dataclass)

```python
@dataclass
class AgentSignal:
    raw_news_id: int              # 关联 agent_raw_news.id
    llm_run_id: int               # 关联 agent_llm_run.id
    vt_symbol: str                # 股票代码 (如 "600309.SSE")
    event: str                    # 事件描述
    relation_type: RelationType   # direct_company|supply_chain|industry|macro_policy|market_sentiment|risk_event|unknown
    impact_direction: ImpactDirection  # positive|negative|neutral|mixed|unknown
    impact_strength: float        # 0.0-1.0
    time_horizon: TimeHorizon     # intraday|short|medium|long|unknown
    confidence: float             # 0.0-1.0
    reason: str                   # 推理原因
    evidence: list[str]           # 证据列表
    published_at: datetime        # 原始发布时间
    available_at: datetime        # 可用时间
    trading_date: str             # ISO日期字符串
    source: Source                # 新闻来源
    source_item_id: str           # 源端ID
    prompt_version: str           # prompt版本
    schema_version: str           # schema版本
```

### 3.2 AgentSignal DB Model (`agent_signal` 表)

| 字段 | 类型 | Nullable | 说明 |
|------|------|----------|------|
| id | INTEGER | NO | 主键，AUTOINCREMENT |
| raw_news_id | INTEGER | YES | |
| llm_run_id | INTEGER | YES | |
| vt_symbol | TEXT | YES | |
| symbol | TEXT | YES | 从vt_symbol解析 |
| exchange | TEXT | YES | 从vt_symbol解析 |
| event | TEXT | YES | |
| relation_type | TEXT | YES | 枚举值 |
| impact_direction | TEXT | YES | 枚举值 |
| impact_strength | FLOAT | YES | 0.0-1.0 |
| time_horizon | TEXT | YES | 枚举值 |
| confidence | FLOAT | YES | 0.0-1.0 |
| reason | TEXT | YES | |
| evidence_json | TEXT | YES | JSON序列化的证据 |
| published_at | DATETIME | YES | |
| available_at | DATETIME | YES | |
| trading_date | TEXT | YES | ISO日期，有索引 |
| source | TEXT | YES | |
| source_item_id | TEXT | YES | |
| prompt_version | TEXT | YES | |
| schema_version | TEXT | YES | |
| created_at | DATETIME | YES | |

**主键**: `id`
**唯一约束**: `(raw_news_id, llm_run_id, vt_symbol, event, relation_type)`
**索引**: `(vt_symbol, available_at)`, `trading_date`

### 3.3 LLM 输入格式

发送给LLM的字段:
- `news_item.title` - 新闻标题
- `news_item.content` - 新闻内容
- `mapped_news.vt_symbol` - 股票代码
- `mapped_news.symbol` - 纯数字代码
- `mapped_news.exchange` - 交易所
- `mapped_news.relation_hint` - 召回关系提示

**未发送**: 股票名称、行业、产品、上下游（硬编码为"未知"）

### 3.4 LLM 输出格式 (JSON)

```json
{
    "event": "string - 事件描述",
    "relation_type": "direct_company|supply_chain|industry|macro_policy|market_sentiment|risk_event|unknown",
    "impact_direction": "positive|negative|neutral|mixed|unknown",
    "impact_strength": 0.0-1.0,
    "time_horizon": "intraday|short|medium|long|unknown",
    "confidence": 0.0-1.0,
    "reason": "string - 简短中文解释",
    "evidence": "string - 新闻中的关键句"
}
```

### 3.5 LLM 辅助表

**agent_llm_run**:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| run_id | TEXT | 运行批次ID |
| raw_news_id | INTEGER | |
| provider | TEXT | deepseek/opencode-go/llama_cpp |
| model | TEXT | 模型名称 |
| prompt_version | TEXT | |
| schema_version | TEXT | |
| parameters_json | TEXT | |
| input_hash | TEXT | |
| started_at | DATETIME | |
| finished_at | DATETIME | |
| status | TEXT | pending/success/failed |
| error | TEXT | |

**唯一约束**: `(raw_news_id, model, prompt_version, schema_version, input_hash)`

**agent_llm_output**:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| llm_run_id | INTEGER | 唯一约束 |
| raw_response | TEXT | |
| parsed_json | TEXT | |
| validation_status | TEXT | |
| validation_errors_json | TEXT | |
| output_hash | TEXT | |
| token_usage_json | TEXT | |

### 3.6 异常处理

- **JSON parse 失败**: 发送修复提示，重试一次
- **字段缺失**: 记录错误，返回 None signal
- **越界 confidence/impact_strength**: 在 `_validate_unit_interval` 中验证，失败则返回错误
- **unknown relation_type**: 在 `_validate_enum` 中验证，失败则返回错误
- **HTTP 429/500/502/503**: 自动重试最多3次

---

## 4. Phase 3: Daily Signal I/O

### 4.1 输入

从 `agent_signal` 表读取的字段:
- `raw_news_id`, `llm_run_id`, `vt_symbol`, `trading_date`
- `event`, `impact_direction`, `impact_strength`, `confidence`
- `relation_type`, `time_horizon`

**不按 vt_symbol 过滤** (全量处理)
**不按 date range 过滤** (全量处理)
**使用 `trading_date`** (由 `available_at` 生成)

### 4.2 中间计算字段 (v0.22)

| 字段 | 公式 | 说明 |
|------|------|------|
| direction_sign | +1/0/-1 | 基于 impact_direction |
| strength_eff | strength^1.2 | 非线性变换 |
| confidence_eff | (confidence - 0.45) / 0.55 | 置信度有效值 |
| relation_weight | 从 config 查表 | 关系类型权重 |
| horizon_weight | 从 config 查表 | 时间范围权重 |
| row_score | sign × s_eff × c_eff × r_w × h_w | 单条信号分数 |
| news_score | ensemble_model_scores() | 多模型共识 |
| event_key | normalize_event() | 事件去重键 |
| event_score | median(news_scores) | 事件级聚合 |
| raw_daily | sum(event_scores) / sqrt(m) | 日级聚合 |
| mixed_intensity | sum(mixed rows' scores) | 混合信号强度 |
| risk_penalty | 1 / (1 + 0.3 × mixed_intensity) | 风险惩罚 |
| daily_signal | tanh(raw_daily × risk_penalty / 0.8) | 最终信号 |

### 4.3 v0.22 输出格式

```json
{
    "trading_date": "2020-01-13",
    "vt_symbol": "600309.SSE",
    "daily_agent_signal": 0.797329,
    "daily_direction": "positive",
    "event_count": 3,
    "raw_daily": 0.872989,
    "mixed_intensity": 0.0,
    "risk_penalty": 1.0,
    "version": "v0.22"
}
```

### 4.4 v0.2 输出格式

```json
{
    "trading_date": "2020-01-13",
    "vt_symbol": "600309.SSE",
    "daily_agent_signal": 1.0,
    "daily_direction": "positive",
    "news_count": 3,
    "positive_news_count": 3,
    "negative_news_count": 0,
    "neutral_news_count": 0,
    "version": "v0.2"
}
```

### 4.5 持久化方式

**无持久化 daily_agent_signal 表**。数据通过以下方式流转:

1. **JSON 文件**: `backtests/results/v0.22/signals/{code}_v0_2.json`, `{code}_v0_22.json`
2. **临时 SQLite**: 回测脚本创建，回测结束后删除
3. **内存 dict**: 策略加载后存为 `dict[date, {signal, direction}]`

### 4.6 版本追踪

- `CONFIG_VERSION = "v0.22"` (hardcoded in config.py)
- v0.2 在 `run_v0_2_pipeline()` 中 hardcoded
- **无 signal_version 或 agent_version 列** 在 `agent_signal` DB 中
- 版本在聚合时应用，不在信号插入时

### 4.7 日期逻辑

- `trading_date = available_at.date().isoformat()` (在 evaluator.py 中生成)
- 存为 TEXT 类型
- **周末/节假日信号永远不会匹配回测 bar** (因为 bar 的 datetime.date() 不会是周末)

---

## 5. Phase 4: Backtest I/O

### 5.1 回测输入

| 输入 | 来源 | 说明 |
|------|------|------|
| Price data | `~/.vntrader/database.db` | 日线 OHLCV |
| daily_agent_signal | JSON files → temp SQLite | v0.2 或 v0.22 |
| Technical indicators | `strategies/technical_indicators.py` | 8种指标 |
| Strategy config | 硬编码在策略类中 | 可通过 setting 覆盖 |

### 5.2 技术指标

| 指标 | 类名 | 买入信号 | 卖出信号 |
|------|------|----------|----------|
| MACD | `MacdIndicator` | DIFF 上穿 DEA | DIFF 下穿 DEA |
| MA+ADX | `MaAdxIndicator` | close > MA 且 ADX > 25 | close < MA |
| Donchian | `DonchianIndicator` | close > 上轨 | close < 下轨 |
| Bollinger | `BollingerIndicator` | close < 下轨 | close > 上轨 |
| RSI | `RsiIndicator` | RSI < 30 | RSI > 70 |
| MACD+ADX | `MacdAdxIndicator` | MACD 金叉且 ADX > 20 | MACD 死叉 |
| Donchian+ATR | `DonchianAtrIndicator` | 突破 + ATR 过滤 | close < 下轨 |
| Bollinger+MA | `BollingerMaIndicator` | close < 下轨 且 > MA | close > 上轨 |

### 5.3 融合模式

| 模式 | 买入逻辑 | 卖出逻辑 |
|------|----------|----------|
| `tech_only` | tech_buy | tech_sell |
| `agent_only` | signal >= threshold | signal <= -threshold |
| `either_safe` | (tech OR agent) AND NOT agent_sell | tech OR agent |
| `veto_only` | tech AND NOT agent_sell | tech OR agent |
| `tech_confirm_veto` | tech AND NOT agent_sell | tech OR agent |
| `agent_overlay` | agent_buy | agent_sell |
| `legacy_either_safe` | (tech OR agent) AND NOT agent_sell | tech OR agent |

### 5.4 回测输出文件

| 文件 | 路径 | 说明 |
|------|------|------|
| Matrix CSV | `backtests/results/matrix/summary_matrix_phase{1,2,3}.csv` | 汇总矩阵 |
| Signal JSON | `backtests/results/v0.22/signals/{code}_v0_{2,22}.json` | 预生成信号 |
| Daily CSV | `backtests/results/catl_multi_signal_daily.csv` | 每日收益 |
| Audit CSV | `backtests/results/audit_agent_exits.csv` | Agent退出审计 |
| Attribution CSV | `backtests/results/daily_position_attribution.csv` | 每日归因 |
| Markdown Reports | `backtests/results/*.md` | 各类分析报告 |

### 5.5 Summary 输出列

标准引擎指标:
- `start_date`, `end_date`, `total_days`
- `capital`, `end_balance`, `total_net_pnl`
- `max_drawdown`, `max_ddpercent`, `max_drawdown_duration`
- `total_return`, `annual_return`, `daily_return`
- `sharpe_ratio`, `return_drawdown_ratio`
- `total_trade_count`, `total_turnover`, `total_commission`

脚本额外计算:
- **Calmar ratio** = `abs(annual_return) / max(|max_ddpercent|, 1e-6)`
- **Win rate** = 盈利天数 / 有交易天数
- **Avg holding days** = 配对买卖日期计算
- **Exposure** = 持仓天数 / 总天数
- **Top-3 concentration** = 前3大日收益 / 总绝对收益

### 5.6 Trade Detail 字段

标准 TradeData:
- `symbol`, `exchange`, `orderid`, `tradeid`
- `direction`, `offset`, `price`, `volume`, `datetime`

脚本额外计算:
- `entry_date`, `exit_date`, `holding_days`
- `gross_pnl`, `commission`, `net_pnl`
- `entry_src` (MACD/Agent/Both), `exit_src`

### 5.7 执行规则

- **T日信号 T+1 执行**: 是，信号在 `trading_date` 匹配 bar，次日执行
- **使用 next open**: 是，使用次日开盘价
- **涨跌停处理**: 未明确处理
- **停牌处理**: 未明确处理
- **T+1 交易限制**: 通过 `TargetPosTemplate` 模式处理

---

## 6. Current Database Tables

| 表名 | 主键 | 去重键 | 索引 |
|------|------|--------|------|
| agent_raw_news | id | (source, source_item_id), (source, content_hash) | published_at |
| agent_news_symbol | id | (raw_news_id, vt_symbol) | vt_symbol |
| agent_stock_profile | vt_symbol | - | - |
| agent_fetch_attempt | id | - | (run_id, source, status) |
| agent_source_cursor | id | (source, scope_key, window_start, window_end) | - |
| agent_llm_run | id | (raw_news_id, model, prompt_version, schema_version, input_hash) | - |
| agent_llm_output | id | llm_run_id (unique) | - |
| agent_signal | id | (raw_news_id, llm_run_id, vt_symbol, event, relation_type) | (vt_symbol, available_at), trading_date |
| agent_backfill_run | run_id | - | - |

---

## 7. Current CSV / Markdown Outputs

### CSV Files

| 文件 | 行数 | 关键列 |
|------|------|--------|
| summary_matrix_phase1.csv | 19 | indicator, total_return, sharpe, max_dd, win_rate |
| summary_matrix_phase2.csv | 121 | + agent_version, signal_mode |
| summary_matrix_phase3.csv | 19 | combo indicators |
| audit_agent_exits.csv | - | entry_date, exit_date, entry_src, exit_src |
| daily_position_attribution.csv | 1537 | date, position, bucket, pnl |
| cost_sensitivity.csv | - | rate, mode, total_return, sharpe |
| catl_multi_signal_daily.csv | - | date, daily_pnl, net_pnl |

### Markdown Reports

| 文件 | 内容 |
|------|------|
| 2026-05-12_agent_news_v01_final.md | v0.1 回填运行报告 |
| equity_reconciliation_report.md | 权益对账报告 |
| audit_agent_exits.md | Agent退出审计 |
| cost_sensitivity.md | 成本敏感性分析 |
| v0.21/summary.md | v0.21 汇总报告 |

---

## 8. Current Version Fields

| 字段 | 位置 | 说明 |
|------|------|------|
| CONFIG_VERSION | config.py | "v0.22" |
| prompt_version | agent_signal, agent_llm_run | LLM prompt版本 |
| schema_version | agent_signal, agent_llm_run | schema版本 |
| version | daily signal JSON | "v0.2" 或 "v0.22" |
| agent_version | matrix CSV | 在回测脚本中添加 |

**缺失**: `signal_version` 不在 `agent_signal` DB 中

---

## 9. Current Known Risks

### Silent Bug 风险

1. **Weekend/holiday signals lost**: `trading_date = available_at.date()` 生成的日期如果是周末/节假日，信号永远不会匹配任何回测 bar

2. **Schema mismatch**: v0.22 的 `event_count` 被插入 v0.2 的 `news_count` 列

3. **Temp DB discards fields**: `raw_daily`, `mixed_intensity`, `risk_penalty`, `version` 在写入临时 SQLite 时丢失

4. **v0.22 often produces 0.0**: 事件净结果为 0 时传播为 `tanh(0) = 0.0`

5. **No persistent daily signal**: 每次回测都需要重新生成信号

6. **Stock profile hardcoded as "未知"**: LLM prompt 中股票名称/行业/产品硬编码为"未知"

7. **Sina source not connected**: 适配器存在但未在工厂中映射

### 数据质量风险

1. **available_at 偏移量固定**: +5分钟对所有源可能不是最优
2. **无交易日历感知**: 信号日期不考虑A股交易日历
3. **无涨跌停处理**: 回测未处理涨跌停限制
4. **无停牌处理**: 回测未处理停牌情况

---

## 10. Recommended Normalized Schema

### 建议改进

1. **添加 `signal_version` 到 `agent_signal` 表**: 允许追溯信号版本
2. **添加 `trading_calendar` 感知**: 使用A股交易日历映射 available_at
3. **持久化 `daily_agent_signal` 表**: 避免每次回测重新生成
4. **统一 temp DB schema**: 包含所有 v0.22 字段
5. **连接 Sina source**: 适配器已存在
6. **填充 StockProfile**: 将名称/行业/产品传入 LLM prompt

### 建议 daily_agent_signal 表

```sql
CREATE TABLE daily_agent_signal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date TEXT NOT NULL,
    vt_symbol TEXT NOT NULL,
    daily_agent_signal REAL NOT NULL,
    daily_direction TEXT NOT NULL,
    event_count INTEGER DEFAULT 0,
    raw_daily REAL DEFAULT 0.0,
    mixed_intensity REAL DEFAULT 0.0,
    risk_penalty REAL DEFAULT 1.0,
    signal_version TEXT NOT NULL,  -- "v0.2" or "v0.22"
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trading_date, vt_symbol, signal_version)
);
```

---

## Appendix: File Paths

### Source Code
- `myQuant/news_ingestion/contracts.py` - 数据合约/枚举
- `myQuant/news_ingestion/storage/sqlite.py` - SQLite ORM
- `myQuant/news_ingestion/sources/*.py` - 新闻源适配器
- `myQuant/news_ingestion/recall/engine.py` - 召回引擎
- `myQuant/news_ingestion/llm/evaluator.py` - LLM评估器
- `myQuant/news_ingestion/scoring/*.py` - 评分pipeline
- `myQuant/news_ingestion/pipeline.py` - 管道编排
- `strategies/tech_agent_strategy.py` - Agent感知策略
- `strategies/technical_indicators.py` - 技术指标

### Scripts
- `backtests/scripts/fetch_news.py` - 新闻拉取
- `backtests/scripts/evaluate_news.py` - LLM评估
- `backtests/scripts/generate_daily_signals.py` - 信号生成
- `backtests/run_matrix.py` - 矩阵回测
- `backtests/scripts/full_metrics.py` - 完整指标
- `backtests/scripts/attr_agent.py` - Agent归因

### Results
- `backtests/results/matrix/` - 矩阵CSV
- `backtests/results/v0.22/signals/` - 信号JSON
- `backtests/results/*.md` - 分析报告
