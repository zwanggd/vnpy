# Agent Quant Pipeline I/O Audit

> **Status**: ✅ 完成 | **Plan created**: 2026-05-27 | **Completed**: 2026-05-27

## TL;DR

在重构模块化 pipeline 之前，完整梳理当前系统每个阶段的真实输入、输出、字段、文件路径、数据库表、主键、依赖关系和潜在 silent bug。

**本任务不做**：
- 策略优化
- 核心策略逻辑修改
- 目录重构
- 新增技术指标

**本任务只做**：
- Current-state audit
- Schema 文档
- 最小一致性检查

## 需要确认的 4 个阶段

### Phase 1: 新闻拉取 + 清洗入库
- [ ] 当前新闻输入来源
- [ ] 当前 raw news 表/文件格式
- [ ] 当前 clean news 表/文件格式
- [ ] 去重逻辑
- [ ] 时间字段处理

### Phase 2: 事件聚合 + LLM 评估
- [ ] 当前 AgentSignal 的真实 schema
- [ ] 当前 LLM 输入格式
- [ ] 当前 LLM 输出格式
- [ ] 多模型逻辑
- [ ] 异常处理

### Phase 3: 聚合计算 + daily signal 生成
- [ ] 当前输入字段
- [ ] 当前中间计算字段
- [ ] 当前 daily_agent_signal 输出格式
- [ ] 当前 signal version
- [ ] 当前日期逻辑

### Phase 4: 回测 + 输出结果
- [ ] 当前回测输入
- [ ] 当前技术指标输入/输出
- [ ] 当前融合模式
- [ ] 当前回测输出文件
- [ ] 当前执行规则

## 需要生成的审计文件

1. `docs/current_pipeline_io_audit.md` - 人类可读审计文档
2. `docs/current_pipeline_io_audit.json` - 机器可读版本
3. `scripts/audit_current_pipeline.py` - 一致性检查脚本
4. `docs/current_pipeline_audit_result.md` - 检查结果

## 验收标准

完成后应能明确回答：
1. 新增一只股票时，当前需要改哪些配置和脚本？
2. 新闻从哪里来，最后存到哪里？
3. AgentSignal 的真实 schema 是什么？
4. daily_agent_signal 的真实 schema 是什么？
5. 回测到底读取了哪些字段？
6. 当前 v0.2 / v0.22 是否能稳定共存？
7. 当前回测输出是否足够做策略比较？
8. 当前是否存在 silent bug 风险？
9. 哪些地方必须在模块化前修？

## 当前发现（基于代码阅读）

### Phase 1 发现

**数据源**：
- Eastmoney: `search-api-web.eastmoney.com/search/jsonp` - 个股新闻
- CNInfo: 巨潮公告（PDF，当前未启用）
- CLS: 财联社实时快讯
- Sina: 新浪财经

**数据库表**：
- `agent_raw_news`: 原始新闻
- `agent_news_symbol`: 新闻-股票映射
- `agent_stock_profile`: 股票画像
- `agent_fetch_attempt`: 拉取记录
- `agent_source_cursor`: 源游标

**去重键**：
- (source, source_item_id) - 主要去重
- (source, content_hash) - 备用去重

**时间字段**：
- `published_at`: 原始发布时间
- `available_at`: published_at + 5分钟（datetime）或 15:00（date-only）
- `fetched_at`: 拉取时间
- `discovered_at`: 发现时间

### Phase 2 发现

**AgentSignal Schema (contracts.py)**：
```python
raw_news_id: int
llm_run_id: int
vt_symbol: str
event: str
relation_type: RelationType
impact_direction: ImpactDirection
impact_strength: float  # 0.0-1.0
time_horizon: TimeHorizon
confidence: float  # 0.0-1.0
reason: str
evidence: list[str]
published_at: datetime
available_at: datetime
trading_date: str
source: Source
source_item_id: str
prompt_version: str
schema_version: str
```

**DB Model (AgentSignalModel)**：
- 增加了 `id` (主键)
- 增加了 `symbol`, `exchange` (从 vt_symbol 解析)
- 增加了 `created_at`
- `evidence` 存为 `evidence_json`

**LLM 输入**：
- 使用 `RawNewsItem` + `MappedNews`
- 包含 title, content, vt_symbol, symbol, exchange
- 包含 relation_hint（召回关系提示）
- 不包含历史信息

**LLM 输出**：
- JSON: event, relation_type, impact_direction, impact_strength, time_horizon, confidence, reason, evidence
- 枚举值: RelationType, ImpactDirection, TimeHorizon
- 数值范围: impact_strength, confidence ∈ [0.0, 1.0]

### Phase 3 发现

**Scoring Pipeline (v0.22)**：
1. `row_score = direction_sign × strength^1.2 × conf_eff × relation_weight × horizon_weight`
2. `news_score = ensemble_model_scores(row_scores)` - 多模型共识
3. `event_key = normalize_event(event)` - 事件去重
4. `event_score = median(news_scores)` - 事件级聚合
5. `raw_daily = sum(event_scores) / sqrt(m)` - 日级聚合
6. `risk_penalty = 1 / (1 + 0.3 × mixed_intensity)` - 混合风险惩罚
7. `daily_signal = tanh(raw_daily × risk_penalty / 0.8)` - 最终信号

**输出字段**：
- trading_date, vt_symbol
- daily_agent_signal ∈ [-1, 1]
- daily_direction: positive/negative/neutral
- event_count, raw_daily, mixed_intensity, risk_penalty
- version: "v0.22"

**版本追踪**：
- v0.2: 简单公式 `sum(impact_strength × confidence) / sqrt(n)`
- v0.22: 完整 pipeline（row_score → ensemble → event_dedup → daily）
- 版本通过 `CONFIG_VERSION` 常量追踪，不写入 DB

### Phase 4 发现

**当前策略**：
- `CatlMultiSignalStrategy`: RSI + MACD + Volume Breakout
- 使用 `TargetPosTemplate` 模式
- 信号合并: `target = sum(signals)`, clamped to [0, max_pos]

**技术指标**：
- RSI: oversold → long, overbought → exit
- MACD: DIFF crosses DEA → long/exit
- Volume Breakout: volume > N × SMA → momentum

**回测输出**：
- daily_df: DataFrame with daily returns
- stats: dict with metrics
- CSV: `backtests/results/catl_multi_signal_daily.csv`

**待确认**：
- 是否使用 agent_overlay 模式
- 是否有 tech_only vs agent 比较
- 具体的 metrics 列表

## 执行计划

### Step 1: 等待 explore agents 完成
- bg_edbfee61: 新闻源和 profiles 审计
- bg_66f2b27d: 回测基础设施审计
- bg_95ebcdcf: daily signal 和 backtest 连接审计

### Step 2: 综合发现
- 合并所有 explore agents 的发现
- 交叉验证代码阅读结果

### Step 3: 生成审计文档
- `docs/current_pipeline_io_audit.md`
- `docs/current_pipeline_io_audit.json`

### Step 4: 生成检查脚本
- `scripts/audit_current_pipeline.py`

### Step 5: 运行检查并生成报告
- `docs/current_pipeline_audit_result.md`

## 验收答案

### 1. 新增一只股票时，当前需要改哪些配置和脚本？

1. 在 `myQuant/news_ingestion/profiles/stock_profiles.py` 的 `DEFAULT_STOCK_PROFILES` 字典中添加新的 `StockProfile`
2. 运行 `backtests/scripts/fetch_news.py` 拉取新闻
3. 运行 `backtests/scripts/evaluate_news.py` 进行 LLM 评估（需要对每个 provider 分别运行）
4. 运行 `backtests/scripts/generate_daily_signals.py` 生成 daily signal JSON
5. 运行 `backtests/run_matrix.py` 生成回测结果

### 2. 新闻从哪里来，最后存到哪里？

- **来源**: Eastmoney (API), CLS (API), CNInfo (API + PDF)
- **存储**: `~/.vntrader/agent_news_em_{symbol}.db` 的 `agent_raw_news` 表
- **映射**: 通过 `agent_news_symbol` 表关联到 vt_symbol

### 3. AgentSignal 的真实 schema 是什么？

见 `docs/current_pipeline_io_audit.md` Section 3.1 和 3.2。22 个字段，主键 `id`，唯一约束 `(raw_news_id, llm_run_id, vt_symbol, event, relation_type)`。

### 4. daily_agent_signal 的真实 schema 是什么？

**无持久化表**。JSON 文件格式：
- v0.22: `trading_date, vt_symbol, daily_agent_signal, daily_direction, event_count, raw_daily, mixed_intensity, risk_penalty, version`
- v0.2: `trading_date, vt_symbol, daily_agent_signal, daily_direction, news_count, positive/negative/neutral_news_count, version`

### 5. 回测到底读取了哪些字段？

从 temp SQLite 读取: `entry_date`, `daily_agent_signal`, `daily_direction`
- `agent_only` 模式使用 `daily_agent_signal` 数值
- 其他模式使用 `daily_direction` 字符串

### 6. 当前 v0.2 / v0.22 是否能稳定共存？

**是**。两个版本是独立的 Python 函数，输出到不同的 JSON 文件，不会互相覆盖。

### 7. 当前回测输出是否足够做策略比较？

**基本足够**。Matrix CSV 包含: total_return, annual_return, max_drawdown, sharpe, calmar, trade_count, win_rate, avg_holding_days。
**缺失**: 无标准化的 Calmar 计算（脚本中重复计算）。

### 8. 当前是否存在 silent bug 风险？

**是**。主要风险：
1. 周末/节假日信号丢失（trading_date 不匹配回测 bar）
2. v0.22 的 event_count 被插入 v0.2 的 news_count 列
3. Temp DB 丢弃 v0.22 的额外字段
4. LLM prompt 中股票信息硬编码为"未知"

### 9. 哪些地方必须在模块化前修？

1. 添加 `signal_version` 到 `agent_signal` 表
2. 添加交易日历感知（避免周末信号丢失）
3. 持久化 `daily_agent_signal` 表
4. 统一 temp DB schema（包含所有 v0.22 字段）
5. 连接 Sina source 到工厂
6. 将 StockProfile 信息传入 LLM prompt

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| (暂无) | - | - |
