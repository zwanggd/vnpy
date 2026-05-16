# 全量宁德时代新闻分析 — 工作规划 v2

## TL;DR
> **目标**: 用新 prompt + DeepSeek V4 Flash API + Qwen3.6 本地模型，分析全部 1,514 条宁德时代新闻，结果可追溯入库，生成对比报告。
> **交付物**: DB 表 `news_analysis`（含 prompt_version 审计字段）+ 20 条 smoke test + 全量双模型分析 + 合法性检查 + 最终报告
> **预估耗时**: ~95 分钟（Task 0-1: ~5min + DeepSeek ~35min + Qwen ~60min）
> **并行**: Qwen 本地 server 独占；DeepSeek 单线程（保守稳妥）

---

## Context

### 已有资产
- **数据**: `~/.vntrader/agent_news.db` 表 `agent_raw_news`，1,514 条宁德时代东方财富新闻（字段：id, title, content, published_at）
- **模型**: Qwen3.6-35B-A3B Q4_K_M GGUF，路径 `/Users/kai/.lmstudio/models/lmstudio-community/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf`
- **API**: DeepSeek V4 Flash (`deepseek-v4-flash`)，key 已就绪
- **经验**: 前两轮 benchmark 已验证：单 worker 最优 (~2.3s)，新 prompt 输出约 48 tokens
- **Prompt**: 用户已提供最终版（10 条判断规则 + 7 字段 JSON + rationale）

### 用户修改要求（v2 新增）
1. `UNIQUE(news_id, model, prompt_version)` — 防止 prompt 改版时覆盖旧结果
2. 用 `INSERT ... ON CONFLICT DO UPDATE` 代替 `INSERT OR REPLACE` — 保留审计字段
3. 增加审计字段：prompt_version, model_provider, parse_success, error_type, retry_count, request_params_json, server_config_json
4. max_tokens 默认 120，retry 放宽到 160（基于实测 ~48 输出 tokens）
5. 全量前先跑 20 条 smoke test，验证枚举合法性
6. DeepSeek 单线程（保守稳妥方案）
7. non-neutral 占比作为健康指标，不作为硬失败条件
8. 跑前先备份数据库
9. 最终报告增加回测有用字段（score 分位数、共识信号、高置信分歧等）

### Qwen 最优配置（已确定）
```
parallel=1, batch=512, ubatch=512, stream=false
→ 单条 ~2.3s，100% JSON 成功率
```

---

## Work Objectives

### Core Objective
用新 prompt 对全量 1,514 条宁德时代新闻完成 DeepSeek V4 Flash 和 Qwen3.6 双模型分析，结果可追溯入库，生成对比报告。

### Concrete Deliverables
- `agent_news.db` 新增 `news_analysis` 表（含 prompt_version + 审计字段）
- 20 条 smoke test 结果（验证 prompt 不过度保守）
- 1,514 × 2 = 3,028 条分析记录
- 合法性检查报告
- 最终对比报告（方向一致率、score 分位数、共识信号、分歧清单+rationale）

### Must Have
- 每条新闻双方都分析（DeepSeek + Qwen）
- `prompt_version` 区分不同版本结果
- 断点续跑（已成功的不重复，除非 --force）
- 枚举值合法性验证（direction/event_type/impact_channel/signal_strength）
- score ∈ [-1, 1], confidence ∈ [0, 1]
- 备份原始数据库

### Must NOT Have
- 不使用 `INSERT OR REPLACE`（使用 `ON CONFLICT DO UPDATE`）
- 不修改新闻原始表
- 不用 stream（用户指定 stream=false）
- 不并行请求（DeepSeek 保守单线程，Qwen parallel=1）
- non-neutral 占比不作为硬失败条件（仅作为健康度指标）

---

## Verification Strategy

### 健康度指标（非硬失败）
- non-neutral < 10%：强警报，prompt 可能过度保守
- non-neutral 10%~30%：正常，需抽样检查
- non-neutral > 30%：信号密度较高

### 硬验收标准
- 两个模型成功率 ≥ 95%
- JSON parse_success ≥ 95%
- direction 枚举合法率 = 100%（仅 positive/neutral/negative）
- score ∈ [-1, 1]，confidence ∈ [0, 1]，合法率 = 100%
- signal_strength ∈ {strong, medium, weak, none}
- event_type / impact_channel 在枚举值内
- 每个 (news_id, model, prompt_version) 至多一条成功记录

---

## Execution Strategy

### 执行流程
```
Task 0: 备份数据库
  └── cp agent_news.db → agent_news.backup.$(timestamp).db

Task 1: 建表 + 脚本 + 20 条 smoke test
  ├── CREATE TABLE news_analysis (含 prompt_version + 审计字段)
  ├── 编写 analyze_all_news.py（UPSERT, max_tokens=120, retry=160）
  ├── 跑 20 条 smoke test（DeepSeek + Qwen）
  └── 验证枚举合法性 + 方向分布

Task 2: DeepSeek V4 Flash 全量分析 (~35min)
  └── 1,514 items × ~1.5s avg，单线程

Task 3: Qwen3.6 全量分析 (~60min)
  └── 启动 server (parallel=1, b=512, ub=512) → 1,514 items × ~2.5s

Task 4: 合法性检查
  └── 枚举值、score/confidence 范围、唯一约束

Task 5: 生成最终对比报告
  └── 一致率、score 分位数、共识信号、分歧清单 + rationale
```

### 单线程顺序执行
无法并行：Qwen 需独占本地 server；DeepSeek 保守单线程避免 DB 锁。

---

## TODOs

- [ ] 0. 备份数据库

  **What to do**:
  - `cp ~/.vntrader/agent_news.db ~/.vntrader/agent_news.backup.$(date +%Y%m%d_%H%M%S).db`
  - 确认备份文件存在且大小与原文件一致

  **Must NOT do**: 不要省略备份（全量分析会写入 3,000+ 条记录）

  **Recommended Agent Profile**: `quick`
  **Skills**: `[]`

  **QA Scenarios**:
  ```
  Scenario: Backup created
    Tool: Bash
    Steps:
      1. ls -la ~/.vntrader/agent_news.backup.*.db
      2. Compare file size with original: ls -la ~/.vntrader/agent_news.db
    Expected Result: Backup file exists, size matches original (within 1%)
    Evidence: .sisyphus/evidence/task-0-backup.txt
  ```

  **Commit**: NO

- [ ] 1. 建表 + 全量分析脚本 + 20 条 smoke test

  **What to do**:

  **1a. 建表** — 在 `agent_news.db` 中创建 `news_analysis` 表：
  ```sql
  CREATE TABLE IF NOT EXISTS news_analysis (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      news_id INTEGER NOT NULL,
      model TEXT NOT NULL,
      model_provider TEXT,
      prompt_version TEXT NOT NULL DEFAULT 'v1',
      direction TEXT,
      score REAL,
      confidence REAL,
      signal_strength TEXT,
      event_type TEXT,
      impact_channel TEXT,
      rationale TEXT,
      raw_response TEXT,
      parse_success INTEGER NOT NULL DEFAULT 0,
      error TEXT,
      error_type TEXT,
      retry_count INTEGER DEFAULT 0,
      latency_ms REAL,
      input_tokens INTEGER,
      output_tokens INTEGER,
      request_params_json TEXT,
      server_config_json TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(news_id, model, prompt_version)
  );
  ```

  **1b. 脚本核心逻辑**：
  - `UPSERT`: `INSERT INTO ... ON CONFLICT(news_id, model, prompt_version) DO UPDATE SET ...` — 仅当原记录失败或传入 `--force` 时更新
  - 正常请求 `max_tokens=120`，JSON 解析失败后 retry 用 `max_tokens=160`
  - 逐条分析，单线程
  - `already_done()`: 查询 `parse_success=1 AND error IS NULL` 跳过
  - `--limit N` 参数限制分析条数，`--model deepseek|qwen|both`
  - `--force` 强制重新分析已成功的条目
  - `--compare` 生成对比报告

  **1c. Smoke test** — 先跑 20 条：
  ```bash
  python3 scripts/analyze_all_news.py --model both --limit 20 --prompt-version v1
  python3 scripts/analyze_all_news.py --compare --limit 20
  ```
  验证项：
  - JSON parse_success ≥ 95%
  - direction 仅在 {positive, neutral, negative}
  - score ∈ [-1, 1], confidence ∈ [0, 1]
  - signal_strength ∈ {strong, medium, weak, none}
  - event_type, impact_channel 在枚举值内
  - rationale 非空且为中文
  - 方向分布不是极端全 neutral（健康度检查，非硬失败）

  **References**:
  - Prompt 和输出格式：本次对话中用户提供的完整版（10 条规则 + 7 字段 JSON + rationale）
  - 现有脚本 `scripts/bench_new_prompt.py` — server 启停、JSON 解析、结果汇总
  - 现有脚本 `scripts/compare_new_prompt.py` — DeepSeek API 调用模式
  - Qwen server 参数：`parallel=1, batch=512, ubatch=512, stream=false`，其余保持基线
  - DeepSeek 模型名：`deepseek-v4-flash`，base_url: `https://api.deepseek.com`
  - DB 路径：`~/.vntrader/agent_news.db`
  - CATL 新闻 SQL：`SELECT id, title, content FROM agent_raw_news WHERE source='eastmoney' AND title LIKE '%宁德时代%' ORDER BY id LIMIT ?`
  - Prompt 版本标识：`v1`（本次）

  **Must NOT do**:
  - 不使用 `INSERT OR REPLACE`
  - prompt_version 不能为空
  - stream 必须为 False
  - Qwen 不用 parallel>1
  - 不要跳过 prompt_version 字段

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `[]`

  **Acceptance Criteria**:
  - [ ] 表创建成功，UNIQUE(news_id, model, prompt_version) 约束生效
  - [ ] smoke test 20 条双方均完成，parse_success ≥ 19/20
  - [ ] direction 枚举合法率 100%
  - [ ] score/confidence 范围合法率 100%
  - [ ] 断点续跑：重复运行不重复分析已成功条目
  - [ ] `--force` 可强制重新分析

  **QA Scenarios**:

  ```
  Scenario: Schema compliance
    Tool: Bash (sqlite3)
    Steps:
      1. sqlite3 ~/.vntrader/agent_news.db ".schema news_analysis"
      2. Verify: prompt_version, parse_success, error_type, retry_count, request_params_json, server_config_json fields exist
      3. Verify: UNIQUE(news_id, model, prompt_version) constraint present
    Expected Result: All fields present, constraint active
    Evidence: .sisyphus/evidence/task-1-schema.txt

  Scenario: 20-item smoke test — both models
    Tool: Bash (python3)
    Steps:
      1. python3 scripts/analyze_all_news.py --model both --limit 20 --prompt-version v1
      2. Verify: 40 rows in news_analysis (20 DS + 20 QW)
      3. Verify: parse_success >= 38/40
    Expected Result: All or nearly all parse successfully
    Evidence: .sisyphus/evidence/task-1-smoke.jsonl

  Scenario: Enum validation
    Tool: Bash (sqlite3)
    Steps:
      1. SELECT DISTINCT direction FROM news_analysis WHERE prompt_version='v1' AND parse_success=1
      2. Verify: only positive, neutral, negative
      3. SELECT MIN(score), MAX(score) FROM news_analysis WHERE prompt_version='v1'
      4. Verify: score ∈ [-1, 1]
      5. Repeat for confidence ∈ [0, 1]
    Expected Result: All values within valid ranges
    Evidence: .sisyphus/evidence/task-1-enums.txt

  Scenario: Direction distribution (health check)
    Tool: Bash (sqlite3)
    Steps:
      1. SELECT model, direction, COUNT(*) FROM news_analysis WHERE prompt_version='v1' AND parse_success=1 GROUP BY model, direction
      2. Verify: non-neutral > 10% for each model (健康检查，不硬失败)
    Expected Result: Reasonable signal density, not all neutral
    Evidence: .sisyphus/evidence/task-1-distribution.txt

  Scenario: Idempotency
    Tool: Bash (python3)
    Steps:
      1. Re-run: python3 scripts/analyze_all_news.py --model both --limit 20 --prompt-version v1
      2. Verify output: "skipped: 40"
    Expected Result: No duplicate API/server calls
    Evidence: .sisyphus/evidence/task-1-idempotent.txt
  ```

  **Commit**: NO (pending smoke test pass)

- [ ] 2. DeepSeek V4 Flash 全量分析

  **What to do**:
  - `python3 scripts/analyze_all_news.py --model deepseek --prompt-version v1`
  - 1,514 条新闻逐条调用 DeepSeek V4 Flash API
  - max_tokens=120, temperature=0, response_format=json_object
  - JSON 解析失败时 retry 一次（max_tokens=160），retry_count 递增
  - 进度实时输出（含 ETA、当前方向分布）
  - 每条结果即时 UPSERT 入库

  **Must NOT do**:
  - 不使用多线程
  - 不覆盖同 prompt_version 下已成功的记录

  **Recommended Agent Profile**: `unspecified-high`
  **Skills**: `[]`

  **Acceptance Criteria**:
  - [ ] 1,514 条全部完成或跳过（parse_success ≥ 95%）
  - [ ] 平均延迟 < 5s/条
  - [ ] 方向分布非全 neutral（健康度检查）
  - [ ] 每条 request_params_json 记录完整参数

  **QA Scenarios**:
  ```
  Scenario: DeepSeek completion
    Tool: Bash (sqlite3)
    Steps:
      1. SELECT COUNT(*) FROM news_analysis WHERE model='deepseek-v4-flash' AND prompt_version='v1' AND parse_success=1
      2. Verify: count >= 1438 (95% of 1514)
    Expected Result: Over 95% success rate
    Evidence: .sisyphus/evidence/task-2-ds-count.txt

  Scenario: DeepSeek latency
    Tool: Bash (sqlite3)
    Steps:
      1. SELECT AVG(latency_ms), MIN(latency_ms), MAX(latency_ms) FROM news_analysis WHERE model='deepseek-v4-flash' AND prompt_version='v1' AND parse_success=1
    Expected Result: avg < 5000ms
    Evidence: .sisyphus/evidence/task-2-ds-latency.txt
  ```

  **Commit**: NO

- [ ] 3. Qwen3.6 本地全量分析

  **What to do**:
  - 启动 Qwen server：parallel=1, batch=512, ubatch=512, cache q8_0, fa=on, stream=false
  - `python3 scripts/analyze_all_news.py --model qwen --prompt-version v1`
  - 1,514 条逐条本地推理
  - max_tokens=120, temperature=0, top_p=1
  - JSON 解析失败时 retry 一次（max_tokens=160）
  - 记录 server_config_json（本次启动参数）
  - 实时进度输出

  **Must NOT do**:
  - 不使用 stream
  - 不使用 parallel>1

  **Recommended Agent Profile**: `unspecified-high`
  **Skills**: `[]`

  **Acceptance Criteria**:
  - [ ] 1,514 条全部完成（parse_success ≥ 95%）
  - [ ] 平均延迟 < 5s/条
  - [ ] server 全程无崩溃
  - [ ] 结束后 server 正常关闭
  - [ ] server_config_json 已记录

  **QA Scenarios**:
  ```
  Scenario: Qwen completion
    Tool: Bash (sqlite3)
    Steps:
      1. SELECT COUNT(*) FROM news_analysis WHERE model='Qwen3.6-35B-A3B-Q4_K_M.gguf' AND prompt_version='v1' AND parse_success=1
      2. Verify: count >= 1438
    Expected Result: Over 95% success
    Evidence: .sisyphus/evidence/task-3-qw-count.txt

  Scenario: Qwen latency
    Tool: Bash (sqlite3)
    Steps:
      1. SELECT AVG(latency_ms), MIN(latency_ms), MAX(latency_ms) FROM news_analysis WHERE model='Qwen3.6-35B-A3B-Q4_K_M.gguf' AND prompt_version='v1' AND parse_success=1
    Expected Result: avg < 4000ms
    Evidence: .sisyphus/evidence/task-3-qw-latency.txt
  ```

  **Commit**: NO

- [ ] 4. 合法性检查

  **What to do**:
  - 验证所有 direction ∈ {positive, neutral, negative}
  - 验证所有 score ∈ [-1, 1], confidence ∈ [0, 1]
  - 验证 signal_strength ∈ {strong, medium, weak, none}
  - 验证 event_type, impact_channel 在合法枚举内
  - 验证 UNIQUE(news_id, model, prompt_version) 无冲突
  - 验证每个 (news_id, model, prompt_version) 至多一条 parse_success=1 的记录
  - 输出违规清单（如有）

  **Recommended Agent Profile**: `quick`
  **Skills**: `[]`

  **Acceptance Criteria**:
  - [ ] direction 枚举合法率 = 100%
  - [ ] score/confidence 范围合法率 = 100%
  - [ ] 无 UNIQUE 约束冲突

  **QA Scenarios**:
  ```
  Scenario: Full validation pass
    Tool: Bash (python3 scripts/analyze_all_news.py --validate)
    Steps:
      1. Run validation script
      2. Verify output: ALL CHECKS PASSED
    Expected Result: Zero violations
    Evidence: .sisyphus/evidence/task-4-validation.txt
  ```

  **Commit**: NO

- [ ] 5. 生成最终对比报告

  **What to do**:
  - `python3 scripts/analyze_all_news.py --compare --output results_v2/final_report.md`
  - 报告包含：
    - 方向一致率（overall + per-class: positive/neutral/negative）
    - 方向分布对比（DeepSeek vs Qwen）
    - 延迟对比（avg/p50/p90）
    - token 对比（input/output 均值）
    - score 分位数：p10, p25, p50, p75, p90（双方各自）
    - confidence 分布
    - signal_strength 分布（strong/medium/weak/none）
    - abs(score) ≥ 0.25 / 0.4 / 0.6 的信号数量
    - 双模型共识 positive / negative 数量
    - 双模型分歧但 high confidence (≥0.7) 的样本（附 title + 双方 rationale）
    - Qwen-only signal 和 DeepSeek-only signal 样本
    - event_type / impact_channel 分布对比
    - 健康度评估（non-neutral 占比 + 建议）

  **Recommended Agent Profile**: `unspecified-high`
  **Skills**: `[]`

  **Acceptance Criteria**:
  - [ ] 报告包含所有 11 类统计
  - [ ] 分歧样本有 rationale 可审计
  - [ ] 报告可读，含分布表格和关键数字
  - [ ] 健康度评估给出明确建议

  **QA Scenarios**:
  ```
  Scenario: Report generated
    Tool: Bash (ls)
    Steps:
      1. ls -la results_v2/final_report.md
    Expected Result: File exists, > 2KB
    Evidence: final_report.md itself

  Scenario: Report contains actionable data
    Tool: Bash (grep)
    Steps:
      1. grep -c "共识 positive" results_v2/final_report.md
      2. grep -c "分歧" results_v2/final_report.md
      3. grep -c "分位数" results_v2/final_report.md
    Expected Result: All sections present with data
    Evidence: .sisyphus/evidence/task-5-report-sections.txt
  ```

  **Commit**: YES — `feat(benchmark): full CATL news analysis v1 (DeepSeek Flash + Qwen3.6)`
  Files: `scripts/analyze_all_news.py`, `results_v2/final_report.md`

---

## Final Verification Wave

- [ ] F1. **Schema + Constraint Audit** — news_analysis 表结构、UNIQUE 约束、枚举值合法性
- [ ] F2. **Data Completeness** — 双方 1,514 条，parse_success ≥ 95%，score/confidence 范围合法
- [ ] F3. **Health Check** — non-neutral 占比健康度评估，极端全 neutral 则报警
- [ ] F4. **Report Completeness** — 11 类统计全部覆盖，分歧样本有 rationale

---

## Commit Strategy

- 全部完成后统一提交：
  `feat(benchmark): full CATL news analysis v1 — DeepSeek V4 Flash + Qwen3.6-35B-A3B`
- 文件：`scripts/analyze_all_news.py`、`results_v2/final_report.md`

---

## Success Criteria

### 硬验收
- [ ] 双方 parse_success ≥ 95%（≥ 1,438/1,514）
- [ ] direction 枚举合法率 = 100%
- [ ] score ∈ [-1, 1]，confidence ∈ [0, 1]，合法率 = 100%
- [ ] UNIQUE(news_id, model, prompt_version) 无冲突
- [ ] 最终报告生成，所有统计项覆盖

### 健康度（非硬失败）
- [ ] non-neutral < 10%：强警报 → 暂停检查 prompt
- [ ] non-neutral 10%~30%：正常 → 抽样确认
- [ ] non-neutral > 30%：信号密度较高 → 可用于回测

### 可追溯性
- [ ] 每条记录有 prompt_version='v1'
- [ ] DeepSeek 记录有 request_params_json
- [ ] Qwen 记录有 server_config_json
- [ ] 备份文件保留原始数据库状态
