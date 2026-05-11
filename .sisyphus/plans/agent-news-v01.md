# Agent News v0.1 Work Plan

## TL;DR
> **Summary**: Build a reusable offline news-ingestion and LLM-evaluation pipeline for the local vn.py project: public Chinese news sources → local recall/filtering → DeepSeek structured impact evaluation → independent SQLite storage in `~/.vntrader/agent_news.db`.
> **Deliverables**:
> - `myQuant/news_ingestion/` package with source adapters, storage repositories, recall/filtering, DeepSeek evaluator, pipeline orchestration, and tests.
> - `backtests/scripts/run_agent_news_backfill.py` CLI for offline backfills using `conda run -n vnpy43`.
> - Independent SQLite database `~/.vntrader/agent_news.db` with replayable `agent_*` tables.
> - Markdown pilot report in `backtests/results/` for the 10 existing database stocks over the market-data-aligned five-year range.
> **Effort**: Large
> **Parallel**: YES - 4 implementation waves + final verification
> **Critical Path**: Task 1 domain contracts → Task 2 SQLite schema → Task 8 recall/dedupe → Task 9 DeepSeek evaluator → Task 10 pipeline CLI → Task 12 pilot run

## Context
### Original Request
The user wants to start Agent-enhanced vn.py development v0.1. The first deliverable is a reusable news module: fetch news from public sources, recall by stock/industry/product/supply-chain/macro/risk keywords, store raw/intermediate data locally, evaluate candidate news with DeepSeek V4 flash, write structured agent signals to SQLite, then run the module for the 10 existing DB stocks over five years of news.

### Interview Summary
- Storage choice: independent SQLite file, not the existing market database. Use `~/.vntrader/agent_news.db`.
- Source policy: public/no-login/no-paid sources first. If historical coverage is incomplete, record the gap instead of requiring credentials.
- Runtime mode: offline historical backfill only for v0.1. No scheduler/realtime daemon.
- Execution convention: every vn.py/data/backfill/test command must use the `vnpy43` conda environment.
- Existing project convention: custom scripts under `backtests/scripts/`, result Markdown under `backtests/results/`, local notes in `myREADME.md`.

### Metis Review (gaps addressed)
- Explicitly defines the 10-stock discovery query and records the resulting symbols.
- Converts `recall_strength` into concrete behavior.
- Defines LLM schema enums, validation, retry/failure behavior, and raw output persistence.
- Classifies sources as mandatory/best-effort and makes source failures partial-result safe.
- Adds idempotency, source coverage reporting, lookahead-safe `available_at`, and duplicate handling.
- Adds a `--max-llm-items` safety option while making the final requested run uncapped unless the user changes the command.
- Makes live source tests opt-in and fixture tests deterministic.
- User later clarified that strict TDD should be used only at key risk points, not for every routine implementation task.

## Work Objectives
### Core Objective
Create a test-driven, modular, reusable news-to-agent-signal pipeline that can be rerun idempotently for offline research/backtesting and later consumed by vn.py strategies alongside OHLCV data.

### Deliverables
1. `myQuant/news_ingestion/` Python package.
2. Deterministic pytest suite under `myQuant/news_ingestion/tests/`.
3. SQLite schema/repository for `~/.vntrader/agent_news.db`.
4. Public-source adapters:
   - `cninfo` announcements: mandatory adapter.
   - `cls_telegraph`: best-effort flash/financial-news adapter.
   - `eastmoney`: best-effort stock/industry/news adapter.
5. Local recall/filtering/deduplication engine.
6. DeepSeek evaluator with JSON-mode request, client-side validation, raw output storage, and fake-client tests.
7. Offline CLI script `backtests/scripts/run_agent_news_backfill.py`.
8. Pilot report `backtests/results/YYYY-MM-DD_agent_news_v01_10stocks_5y.md`.

### Definition of Done (verifiable conditions with commands)
- Unit/integration tests pass:
  ```bash
  conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q
  ```
- CLI help is available:
  ```bash
  conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --help
  ```
- Schema exists in independent DB:
  ```bash
  conda run -n vnpy43 python - <<'PY'
  import sqlite3, pathlib
  db = pathlib.Path.home() / '.vntrader' / 'agent_news.db'
  con = sqlite3.connect(db)
  names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
  required = {'agent_backfill_run','agent_stock_profile','agent_raw_news','agent_news_symbol','agent_fetch_attempt','agent_llm_run','agent_llm_output','agent_signal','agent_source_cursor'}
  assert required <= names, sorted(required - names)
  print('OK')
  PY
  ```
- Dry-run count report is generated without DeepSeek API key:
  ```bash
  conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --start 2021-01-01 --end 2021-01-31 --symbols-from-market-db --recall-strength medium --sources cninfo,eastmoney --dry-run --report-path backtests/results/agent_news_v01_dry_run.md
  ```
- Small live pilot can be run when explicitly enabled:
  ```bash
  AGENT_NEWS_LIVE_TEST=1 conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --start 2024-01-02 --end 2024-01-05 --symbols 300750.SZSE --recall-strength low --sources cninfo --max-llm-items 1 --report-path backtests/results/agent_news_v01_live_smoke.md
  ```
- Full requested pilot has a report and database rows/coverage summary:
  ```bash
  conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --start 2021-01-01 --end 2026-05-08 --symbols-from-market-db --recall-strength medium --sources cninfo,cls_telegraph,eastmoney --report-path backtests/results/$(date +%F)_agent_news_v01_10stocks_5y.md
  ```

### Must Have
- Targeted TDD: use strict failing-test-first only for key risk points (contracts, SQLite/idempotency, recall/lookahead, DeepSeek validation, and pipeline CLI safety). Other tasks still need automated verification, but do not require strict red-green TDD.
- All code runnable in `vnpy43`.
- Independent SQLite file at `~/.vntrader/agent_news.db`.
- Separate `symbol`, `exchange`, and convenience `vt_symbol`; enforce consistency in repository layer.
- Raw source data, fetch attempts, LLM raw output, validation errors, prompt/schema/model versions, and final signals stored locally.
- Idempotent reruns: repeated same fixture or backfill window must not duplicate raw news/signals.
- `available_at` must be present on final signals and used in future strategy reads.
- Public-source failures must be persisted and summarized, not hidden.
- DeepSeek API key must only come from `DEEPSEEK_API_KEY` and must never be written to DB, logs, reports, or fixtures.

### Must NOT Have (guardrails, AI slop patterns, scope boundaries)
- MUST NOT modify vn.py core package files unless strictly required for import packaging; prefer `myQuant/news_ingestion/`.
- MUST NOT write agent tables into `~/.vntrader/database.db`.
- MUST NOT implement live trading, order placement, or strategy execution in v0.1.
- MUST NOT implement GUI, scheduler, daemon, vector DB, embeddings, RAG memory, browser automation, or a generic multi-agent framework.
- MUST NOT require paid APIs, login cookies, private credentials, or browser-only data access.
- MUST NOT run unbounded LLM evaluation before local filtering and idempotency are implemented.
- MUST NOT assume DeepSeek JSON mode is schema-safe.
- MUST NOT silently coerce invalid LLM outputs into signals.
- MUST NOT claim full 5-year coverage if public sources only return partial data.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: targeted TDD with `pytest` at key risk points; normal implementation tasks use fixture tests/automated verification without requiring strict red-green sequencing. Live HTTP tests opt-in via `AGENT_NEWS_LIVE_TEST=1`.
- QA policy: Every task has agent-executed happy and failure scenarios.
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}` for test output, schema checks, CLI output, DB assertions, and pilot reports.

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks for max parallelism.

Wave 1: Tasks 1-5 (contracts, schema, profiles, source interface, CNInfo adapter)
Wave 2: Tasks 6-9 (CLS adapter, Eastmoney adapter, recall/dedupe, DeepSeek evaluator)
Wave 3: Tasks 10-12 (pipeline CLI, reporting, live smoke + full pilot)
Wave 4: Task 13 (documentation/conventions update after implementation behavior is known)

### Dependency Matrix (full, all tasks)
| Task | Depends On | Blocks |
|---|---|---|
| 1 Domain contracts | none | 2,3,4,8,9,10 |
| 2 SQLite schema/repository | 1 | 3,8,9,10,12 |
| 3 Stock profiles/universe | 1,2 | 8,10,12 |
| 4 Source interface/HTTP fixtures | 1 | 5,6,7 |
| 5 CNInfo adapter | 2,4 | 8,10,12 |
| 6 CLS adapter | 2,4 | 8,10,12 |
| 7 Eastmoney adapter | 2,4 | 8,10,12 |
| 8 Recall/filter/dedupe | 1,2,3,5,6,7 | 9,10,12 |
| 9 DeepSeek evaluator | 1,2,8 | 10,12 |
| 10 Backfill pipeline/CLI | 1,2,3,8,9 | 11,12 |
| 11 Reporting | 10 | 12 |
| 12 Smoke + 5y pilot | 10,11 | 13 |
| 13 Docs/conventions | 12 | final verification |

### Agent Dispatch Summary (wave → task count → categories)
| Wave | Count | Categories |
|---|---:|---|
| 1 | 5 | deep, unspecified-high |
| 2 | 4 | unspecified-high, deep |
| 3 | 3 | deep, unspecified-high |
| 4 | 1 | writing |

## TODOs
> Implementation + Verification = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Establish package skeleton, domain contracts, and enums

  **What to do**: Create `myQuant/news_ingestion/` as a reusable package. Add dataclass/typed contracts for `NewsQuery`, `RawNewsItem`, `StockProfile`, `MappedNews`, `LLMRunRecord`, `LLMOutputRecord`, `AgentSignal`, and `BackfillConfig`. Define v0.1 enums exactly:
  - `source`: `cninfo`, `cls_telegraph`, `eastmoney`
  - `source_category`: `announcement`, `flash`, `financial_news`, `industry_policy`, `macro_policy`, `unknown`
  - `recall_strength`: `low`, `medium`, `high`
  - `relation_type`: `direct_company`, `supply_chain`, `industry`, `macro_policy`, `market_sentiment`, `risk_event`, `unknown`
  - `impact_direction`: `positive`, `negative`, `neutral`, `mixed`, `unknown`
  - `time_horizon`: `intraday`, `short`, `medium`, `long`, `unknown`
  - `status`: `pending`, `success`, `failed`, `skipped`
  Numeric rules: `impact_strength` and `confidence` are floats in `[0.0, 1.0]`; direction carries sign, strength carries magnitude.
  **Must NOT do**: Do not call live endpoints or DeepSeek. Do not add strategy/backtest consumption logic.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: foundational contracts affect every downstream module.
  - Skills: `test-driven-development` - Required by user and needed for API stability.
  - Omitted: `frontend-design` - No UI work.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 2,3,4,8,9,10 | Blocked By: none

  **References**:
  - Pattern: `vnpy/trader/object.py` - dataclass-style vn.py domain models and `vt_symbol` convention.
  - Pattern: `vnpy/trader/constant.py` - enum patterns for typed trading constants.
  - Pattern: `myREADME.md` - local execution and artifact conventions.
  - Draft: `.sisyphus/drafts/agent-news-v01.md` - confirmed requirements and choices.

  **Acceptance Criteria**:
  - [ ] `conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_contracts.py -q` passes.
  - [ ] Test proves invalid enum values are rejected or validation-fail before persistence.
  - [ ] Test proves `vt_symbol="300750.SZSE"` parses to `symbol="300750"`, `exchange="SZSE"`, and regenerates the same `vt_symbol`.

  **QA Scenarios**:
  ```
  Scenario: Valid AgentSignal contract
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_contracts.py::test_agent_signal_contract_accepts_valid_signal -q
    Expected: Exit 0; signal with impact_strength=0.72 and confidence=0.68 is accepted.
    Evidence: .sisyphus/evidence/task-1-contracts-valid.txt

  Scenario: Invalid confidence rejected
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_contracts.py::test_agent_signal_contract_rejects_confidence_outside_zero_one -q
    Expected: Exit 0; test asserts confidence=1.5 raises validation error or returns invalid status.
    Evidence: .sisyphus/evidence/task-1-contracts-invalid.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add v0.1 domain contracts` | Files: `myQuant/news_ingestion/**`, tests

- [x] 2. Implement independent SQLite schema and repository with idempotency tests

  **What to do**: Implement `myQuant/news_ingestion/storage/sqlite.py` and schema initialization for `~/.vntrader/agent_news.db`. Use peewee ORM models backed by SQLite, matching the style of vnpy_sqlite; repository API must hide storage details. Create these tables exactly:
  - `agent_backfill_run(run_id TEXT PRIMARY KEY, started_at DATETIME, finished_at DATETIME, status TEXT, config_json TEXT, summary_json TEXT, error TEXT)`
  - `agent_stock_profile(vt_symbol TEXT PRIMARY KEY, symbol TEXT, exchange TEXT, name TEXT, aliases_json TEXT, industry_json TEXT, products_json TEXT, upstream_json TEXT, downstream_json TEXT, macro_factors_json TEXT, risk_keywords_json TEXT, profile_version TEXT, updated_at DATETIME)`
  - `agent_raw_news(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, source_category TEXT, source_item_id TEXT, url TEXT, title TEXT NOT NULL, content TEXT, summary TEXT, published_at DATETIME, discovered_at DATETIME, fetched_at DATETIME, available_at DATETIME, raw_payload_json TEXT, content_hash TEXT NOT NULL, body_status TEXT, language TEXT DEFAULT 'zh', created_at DATETIME, UNIQUE(source, source_item_id), UNIQUE(source, content_hash))`
  - `agent_news_symbol(id INTEGER PRIMARY KEY AUTOINCREMENT, raw_news_id INTEGER, vt_symbol TEXT, symbol TEXT, exchange TEXT, relation_hint TEXT, mapping_method TEXT, mapping_confidence REAL, keywords_matched_json TEXT, UNIQUE(raw_news_id, vt_symbol))`
  - `agent_fetch_attempt(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, source TEXT, vt_symbol TEXT, symbol TEXT, exchange TEXT, window_start DATETIME, window_end DATETIME, request_fingerprint TEXT, status TEXT, http_status INTEGER, error TEXT, attempt_no INTEGER, started_at DATETIME, finished_at DATETIME, items_found INTEGER, items_saved INTEGER)`
  - `agent_llm_run(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, raw_news_id INTEGER, provider TEXT, model TEXT, prompt_version TEXT, schema_version TEXT, parameters_json TEXT, input_hash TEXT, started_at DATETIME, finished_at DATETIME, status TEXT, error TEXT, UNIQUE(raw_news_id, model, prompt_version, schema_version, input_hash))`
  - `agent_llm_output(id INTEGER PRIMARY KEY AUTOINCREMENT, llm_run_id INTEGER UNIQUE, raw_response TEXT, parsed_json TEXT, validation_status TEXT, validation_errors_json TEXT, output_hash TEXT, token_usage_json TEXT)`
  - `agent_signal(id INTEGER PRIMARY KEY AUTOINCREMENT, raw_news_id INTEGER, llm_run_id INTEGER, vt_symbol TEXT, symbol TEXT, exchange TEXT, event TEXT, relation_type TEXT, impact_direction TEXT, impact_strength REAL, time_horizon TEXT, confidence REAL, reason TEXT, evidence_json TEXT, published_at DATETIME, available_at DATETIME, trading_date TEXT, source TEXT, source_item_id TEXT, prompt_version TEXT, schema_version TEXT, created_at DATETIME, UNIQUE(raw_news_id, llm_run_id, vt_symbol, event, relation_type))`
  - `agent_source_cursor(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, scope_key TEXT, window_start DATETIME, window_end DATETIME, cursor_state_json TEXT, last_success_at DATETIME, status TEXT, updated_at DATETIME, UNIQUE(source, scope_key, window_start, window_end))`
  Add indexes on `agent_raw_news(published_at)`, `agent_news_symbol(vt_symbol)`, `agent_signal(vt_symbol, available_at)`, `agent_signal(trading_date)`, and `agent_fetch_attempt(run_id, source, status)`.
  **Must NOT do**: Do not create or alter tables in `~/.vntrader/database.db`.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: schema/idempotency mistakes poison all future research.
  - Skills: `test-driven-development` - Storage must be TDD and rerunnable.
  - Omitted: `webapp-testing` - No browser/UI.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 3,8,9,10,12 | Blocked By: 1

  **References**:
  - Pattern: `vnpy/trader/database.py` - timezone and database abstraction concepts.
  - Pattern: `vnpy/trader/utility.py` - `get_file_path()` resolves vn.py local files under `.vntrader`.
  - Existing DB: `~/.vntrader/database.db` - do not mutate; use only to read symbols.

  **Acceptance Criteria**:
  - [ ] `conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_storage_sqlite.py -q` passes.
  - [ ] Schema init creates `~/.vntrader/agent_news.db` when missing.
  - [ ] Re-inserting the same fixture raw news twice leaves `agent_raw_news` row count at 1.
  - [ ] Re-inserting the same valid signal twice leaves `agent_signal` row count at 1.

  **QA Scenarios**:
  ```
  Scenario: Schema init creates all tables
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_storage_sqlite.py::test_schema_init_creates_required_tables -q
    Expected: Exit 0; test asserts all 9 required agent_* tables exist in a temp SQLite DB.
    Evidence: .sisyphus/evidence/task-2-schema-init.txt

  Scenario: Duplicate raw news is idempotent
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_storage_sqlite.py::test_raw_news_upsert_is_idempotent -q
    Expected: Exit 0; row count remains 1 after two saves with same source/source_item_id/content_hash.
    Evidence: .sisyphus/evidence/task-2-idempotency.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add independent sqlite storage` | Files: `myQuant/news_ingestion/storage/**`, tests

- [x] 3. Add stock universe discovery and local keyword profiles for the 10 DB stocks

  **What to do**: Implement deterministic stock discovery from market DB using:
  ```sql
  SELECT symbol, exchange FROM dbbaroverview WHERE interval='d' ORDER BY symbol;
  ```
  Convert to `vt_symbol` and persist profiles into `agent_stock_profile`. Seed exact v0.1 profiles for the current 10 stocks:
  - `000333.SZSE`: name `美的集团`; aliases `美的, Midea, 000333`; industry `家电, 智能制造, 机器人`; products `空调, 家电, 工业机器人`; upstream `铜, 铝, 芯片, 压缩机`; downstream `地产, 消费电子, 家电渠道`; macro `地产政策, 消费刺激, 出口汇率`; risks `原材料涨价, 海外需求下滑, 汇率波动`.
  - `002475.SZSE`: `立讯精密`; aliases `立讯, Luxshare, 002475`; industry `消费电子, 苹果产业链, 连接器`; products `连接器, AirPods, 精密制造`; upstream `铜, 电子元件, 芯片`; downstream `苹果, 消费电子, 汽车电子`; macro `苹果销量, 消费电子周期, 出口管制`; risks `客户集中, 苹果砍单, 毛利率下滑`.
  - `002594.SZSE`: `比亚迪`; aliases `BYD, 比亚迪股份, 002594`; industry `新能源汽车, 动力电池, 汽车`; products `新能源汽车, 刀片电池, 动力电池`; upstream `锂矿, 碳酸锂, 芯片`; downstream `汽车销售, 出口, 储能`; macro `新能源补贴, 双碳, 欧洲电动车政策`; risks `价格战, 产能过剩, 出口关税`.
  - `300750.SZSE`: use the CATL profile from the user request.
  - `600036.SSE`: `招商银行`; aliases `招行, CMB, 600036`; industry `银行, 零售金融`; products `零售贷款, 信用卡, 财富管理`; upstream `资金成本, 存款`; downstream `居民消费, 房地产, 企业信贷`; macro `利率政策, 房地产政策, 存款利率`; risks `不良贷款, 净息差收窄, 地产风险`.
  - `600276.SSE`: `恒瑞医药`; aliases `恒瑞, Hengrui, 600276`; industry `医药, 创新药`; products `抗肿瘤药, 麻醉药, 创新药`; upstream `原料药, 临床试验`; downstream `医院, 医保, 药店`; macro `医保谈判, 集采, 药监审批`; risks `集采降价, 研发失败, 专利到期`.
  - `600309.SSE`: `万华化学`; aliases `万华, Wanhua, 600309`; industry `化工, 聚氨酯, MDI`; products `MDI, TDI, 聚氨酯, 石化材料`; upstream `煤炭, 原油, 天然气`; downstream `建筑, 家电, 汽车, 鞋服`; macro `地产政策, 油价, 环保限产`; risks `化工品价格下跌, 需求下滑, 安全事故`.
  - `600519.SSE`: `贵州茅台`; aliases `茅台, Kweichow Moutai, 600519`; industry `白酒, 高端消费`; products `飞天茅台, 茅台酒`; upstream `高粱, 包材`; downstream `经销商, 消费, 宴席`; macro `消费政策, 反腐, 居民收入`; risks `批价下跌, 渠道库存, 消费降级`.
  - `601318.SSE`: `中国平安`; aliases `平安, Ping An, 601318`; industry `保险, 金融`; products `寿险, 财险, 银行, 资管`; upstream `利率, 资本市场`; downstream `居民保障, 企业保险`; macro `利率政策, 资本市场, 房地产`; risks `投资亏损, 保费下滑, 地产敞口`.
  - `601899.SSE`: `紫金矿业`; aliases `紫金, Zijin, 601899`; industry `有色金属, 黄金, 铜矿`; products `黄金, 铜, 锂, 锌`; upstream `矿山, 能源, 设备`; downstream `铜需求, 新能源, 贵金属投资`; macro `金价, 铜价, 美元, 地缘政治`; risks `矿山安全, 资源国政策, 金属价格下跌`.
  **Must NOT do**: Do not fetch stock profile data from paid APIs. Do not infer more than this seed profile in code.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: profile quality affects recall but implementation is bounded.
  - Skills: `test-driven-development` - Need fixture tests for deterministic universe/profile loading.
  - Omitted: `librarian` - Profile seed is specified here; no further research needed.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 8,10,12 | Blocked By: 1,2

  **References**:
  - Existing DB query source: `~/.vntrader/database.db` table `dbbaroverview`.
  - Pattern: `backtests/scripts/run_doublema_daily_all_db.py` - deterministic symbol discovery from local market DB.
  - User example: `.sisyphus/drafts/agent-news-v01.md` - CATL profile shape.

  **Acceptance Criteria**:
  - [ ] Test discovers exactly the 10 expected `vt_symbol`s from a fixture `dbbaroverview`.
  - [ ] Test stores and retrieves all 10 stock profiles from temp `agent_news.db`.
  - [ ] Test profile for `300750.SZSE` includes `宁德时代`, `CATL`, `碳酸锂`, and `价格战`.

  **QA Scenarios**:
  ```
  Scenario: Discover 10 symbols from market DB fixture
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_stock_profiles.py::test_discover_symbols_from_market_db_overview -q
    Expected: Exit 0; exact sorted symbols match the 10-symbol list in this task.
    Evidence: .sisyphus/evidence/task-3-symbol-discovery.txt

  Scenario: Missing profile fails clearly
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_stock_profiles.py::test_missing_profile_reports_symbol -q
    Expected: Exit 0; missing `300750.SZSE` raises or returns an error containing that vt_symbol.
    Evidence: .sisyphus/evidence/task-3-missing-profile.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add stock profiles and universe discovery` | Files: `myQuant/news_ingestion/profiles/**`, tests

- [x] 4. Build source adapter interface, HTTP client wrapper, fixtures, and live-test switch

  **What to do**: Implement a common source interface: `fetch(query: NewsQuery) -> SourceFetchResult`. Add polite HTTP wrapper with timeout `15s`, retry count `2`, exponential backoff for 429/5xx, default request interval `1.0s`, and user-agent string `Mozilla/5.0 AgentNewsV01Research`. Add fixture-based tests and a live-test marker that only runs when `AGENT_NEWS_LIVE_TEST=1`.
  **Must NOT do**: Do not perform live HTTP in normal pytest. Do not store cookies or credentials.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: adapter boundary controls source replaceability and testability.
  - Skills: `test-driven-development`, `systematic-debugging` - Needed for flaky HTTP failure handling.
  - Omitted: `webapp-testing` - HTTP API tests only.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 5,6,7 | Blocked By: 1

  **References**:
  - Research: `.sisyphus/drafts/agent-news-v01.md` news source findings.
  - Pattern: `tests/test_alpha101.py` - pytest fixture style.

  **Acceptance Criteria**:
  - [ ] Normal tests do not access the network.
  - [ ] HTTP wrapper retries 429 twice and then returns structured failure.
  - [ ] Live marker skips unless `AGENT_NEWS_LIVE_TEST=1`.

  **QA Scenarios**:
  ```
  Scenario: Network disabled unit tests remain deterministic
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_base.py -q
    Expected: Exit 0; tests use fixture transport/mocked session only.
    Evidence: .sisyphus/evidence/task-4-source-base.txt

  Scenario: 429 retry failure is structured
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_base.py::test_http_429_retries_then_structured_failure -q
    Expected: Exit 0; result status is failed, error contains 429, no exception leaks.
    Evidence: .sisyphus/evidence/task-4-429.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add source adapter interface` | Files: `myQuant/news_ingestion/sources/base.py`, tests

- [x] 5. Implement CNInfo announcement adapter with metadata-first and PDF-body best-effort

  **What to do**: Implement `CninfoAnnouncementSource` using public endpoints:
  - Org lookup: `http://www.cninfo.com.cn/new/information/topSearch/query?keyWord={code}`
  - Announcement search: `POST http://www.cninfo.com.cn/new/hisAnnouncement/query`
  Use `seDate=YYYY-MM-DD~YYYY-MM-DD`, `pageNum`, `pageSize=30`, `tabName=fulltext`, and stock/orgId where available. Store announcement metadata always. For candidates that pass rough stock/date query, attempt PDF download from `http://static.cninfo.com.cn/{adjunctUrl}` and text extraction only if an installed PDF extractor is available; otherwise set `body_status='skipped_no_pdf_extractor'`. If extraction fails, set `body_status='failed'` and persist error in `agent_fetch_attempt`.
  **Must NOT do**: Do not block the pipeline on PDF extraction failure. Do not require browser automation.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: public endpoint parsing and PDF best-effort need careful failure modes.
  - Skills: `test-driven-development`, `systematic-debugging` - Fixtures first, robust failure handling.
  - Omitted: `pdf` - Only use if executor chooses to implement PDF text extraction; metadata path must work without it.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 8,10,12 | Blocked By: 2,4

  **References**:
  - External: `http://www.cninfo.com.cn/new/hisAnnouncement/query` - researched public announcement query endpoint.
  - External: `http://static.cninfo.com.cn/{adjunctUrl}` - researched PDF URL pattern.
  - Storage: Task 2 `agent_raw_news` and `agent_fetch_attempt` schema.

  **Acceptance Criteria**:
  - [ ] Fixture metadata response parses title, source_item_id/url, published_at, source `cninfo`, category `announcement`.
  - [ ] Pagination stops when `hasMore=false` or all pages exhausted.
  - [ ] PDF extraction failure stores raw metadata and fetch_attempt failure detail but returns successful metadata records.

  **QA Scenarios**:
  ```
  Scenario: CNInfo fixture parses announcement metadata
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_cninfo.py::test_cninfo_parses_announcement_fixture -q
    Expected: Exit 0; parsed item has title, URL, source_item_id, published_at, and content_hash.
    Evidence: .sisyphus/evidence/task-5-cninfo-fixture.txt

  Scenario: CNInfo PDF extraction failure is non-blocking
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_cninfo.py::test_cninfo_pdf_failure_keeps_metadata -q
    Expected: Exit 0; raw news saved with body_status='failed' or 'skipped_no_pdf_extractor'.
    Evidence: .sisyphus/evidence/task-5-cninfo-pdf-failure.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add cninfo announcement source` | Files: `myQuant/news_ingestion/sources/cninfo.py`, fixtures, tests

- [x] 6. Implement CLS telegraph adapter as best-effort flash/news source

  **What to do**: Implement `ClsTelegraphSource` behind the same adapter interface. Use researched public web endpoint shape `https://www.cls.cn/nodeapi/telegraphList` with signed params. Implement the signature function deterministically from ordered params `app=CailianpressWeb&last_time={ts}&os=web&rn={rn}&sv=7.7.5`, SHA1 hexdigest then MD5 hexdigest. Fetch by backward cursor using `last_time`; normalize returned `id`, `title`, `content`, `ctime`, `shareurl`. Since CLS has no stock filter, the adapter fetches date windows and leaves stock relevance to local recall.
  **Must NOT do**: Do not guarantee full five-year coverage. Do not hard-fail the full run if CLS is blocked; record coverage gaps.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: signed unofficial endpoint is brittle.
  - Skills: `test-driven-development`, `systematic-debugging` - Need deterministic signature tests and structured failure handling.
  - Omitted: `librarian` - Endpoint research already completed.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: 8,10,12 | Blocked By: 2,4

  **References**:
  - External: `https://www.cls.cn/telegraph` - source page.
  - Research: `.sisyphus/drafts/agent-news-v01.md` - signature and cursor findings.

  **Acceptance Criteria**:
  - [ ] Signature unit test matches fixed expected hash for a fixed param string.
  - [ ] Fixture response parses at least `id`, `title/content`, `published_at`, `url`.
  - [ ] Adapter returns structured source coverage failure if response schema changes.

  **QA Scenarios**:
  ```
  Scenario: CLS signature deterministic
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_cls.py::test_cls_signature_is_deterministic -q
    Expected: Exit 0; fixed params produce fixed sign value.
    Evidence: .sisyphus/evidence/task-6-cls-signature.txt

  Scenario: CLS malformed response is captured
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_cls.py::test_cls_malformed_response_records_failure -q
    Expected: Exit 0; fetch result status failed and includes parse error; no crash.
    Evidence: .sisyphus/evidence/task-6-cls-malformed.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add cls telegraph source` | Files: `myQuant/news_ingestion/sources/cls.py`, fixtures, tests

- [x] 7. Implement Eastmoney adapter for stock/industry/news best-effort recall

  **What to do**: Implement `EastmoneyNewsSource`. Support two modes behind one adapter:
  - stock-news mode for stock code/name queries using public Eastmoney search/news endpoints when accessible;
  - keyword-search mode for industry/macro/policy keywords using `https://so.eastmoney.com/news/s?keyword={keyword}` HTML parsing.
  Normalize title, summary/content if present, URL, source, published_at when present. If the source does not expose reliable date-range pagination, fetch available pages and let the report mark coverage as partial/latest-only.
  **Must NOT do**: Do not use paid Choice API. Do not use Selenium/browser automation. Do not claim complete historical coverage from Eastmoney.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: HTML/API parsing is brittle and must be isolated.
  - Skills: `test-driven-development`, `systematic-debugging` - Fixture-based parser and failure tests needed.
  - Omitted: `webapp-testing` - No browser automation allowed.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: 8,10,12 | Blocked By: 2,4

  **References**:
  - External: `https://so.eastmoney.com/news/s` - researched public keyword search page.
  - Research: `.sisyphus/drafts/agent-news-v01.md` - Eastmoney capability/limitations.

  **Acceptance Criteria**:
  - [ ] Fixture parser extracts title, URL, summary/content, and published_at if present.
  - [ ] Missing publish time results in `published_at=None`, but item can still be stored with source coverage warning.
  - [ ] Report metadata marks Eastmoney date-range coverage as `partial` unless live adapter verifies full range support.

  **QA Scenarios**:
  ```
  Scenario: Eastmoney fixture parses stock news
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_eastmoney.py::test_eastmoney_parses_stock_news_fixture -q
    Expected: Exit 0; parsed item has source='eastmoney', title, URL, and content_hash.
    Evidence: .sisyphus/evidence/task-7-eastmoney-fixture.txt

  Scenario: Eastmoney missing date is non-fatal
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_source_eastmoney.py::test_eastmoney_missing_date_records_warning -q
    Expected: Exit 0; item is stored with warning/coverage flag, no unhandled exception.
    Evidence: .sisyphus/evidence/task-7-eastmoney-missing-date.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add eastmoney news source` | Files: `myQuant/news_ingestion/sources/eastmoney.py`, fixtures, tests

- [x] 8. Implement recall-strength filtering, symbol mapping, deduplication, and availability alignment

  **What to do**: Implement local second-stage filtering after source fetch. Concrete `recall_strength` semantics:
  - `low`: match stock `name`, exact `symbol`, or aliases only; require direct match in title or content.
  - `medium`: include `low` plus industry, products, upstream, downstream, and risk keywords; allow title OR content match.
  - `high`: include `medium` plus macro_factors and generic policy/macro/geopolitical keywords; allow broader content match and assign lower mapping confidence for non-direct matches.
  Mapping confidence defaults: direct stock/name `1.0`, alias `0.9`, product/supply-chain `0.7`, industry `0.6`, macro/policy `0.5`. Deduplicate exact duplicates by `(source, source_item_id)` then `(source, content_hash)`, and near-duplicates by normalized title + published date + URL host. Compute `available_at` with this fixed v0.1 policy: for historical backfill, if `published_at` includes time, set `available_at = published_at + 5 minutes`; if only date is known, set `available_at` to `15:00:00 Asia/Shanghai` on that date; if publish date/time is unknown, keep raw news but do not create a signal. Store actual `fetched_at` separately and never use it as backtest availability.
  **Must NOT do**: Do not map macro/industry news to every stock without a keyword/profile relationship. Do not allow signals without `available_at`.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: recall and lookahead logic determine research validity.
  - Skills: `test-driven-development` - Need exact retained/rejected fixture tests.
  - Omitted: `librarian` - No external research needed.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 9,10,12 | Blocked By: 1,2,3,5,6,7

  **References**:
  - Pattern: `vnpy/trader/utility.py` - `extract_vt_symbol` / `generate_vt_symbol` conventions.
  - Storage: Task 2 `agent_news_symbol`, `agent_raw_news`, `agent_signal` timestamp constraints.
  - Oracle: `.sisyphus/drafts/agent-news-v01.md` lookahead/available_at guardrail.

  **Acceptance Criteria**:
  - [ ] `low`, `medium`, and `high` fixture tests retain/reject exact expected news IDs.
  - [ ] Duplicate fixture insertion/evaluation does not double LLM candidates.
  - [ ] News after close has `available_at` later than `published_at` and signal can be filtered by `available_at`.

  **QA Scenarios**:
  ```
  Scenario: Recall levels have deterministic outputs
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_recall.py::test_recall_strength_levels -q
    Expected: Exit 0; low/medium/high candidate ID sets exactly match test expectations.
    Evidence: .sisyphus/evidence/task-8-recall-levels.txt

  Scenario: Duplicate articles are not sent twice to LLM
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_recall.py::test_dedup_prevents_duplicate_llm_candidates -q
    Expected: Exit 0; two duplicate fixture articles produce one candidate.
    Evidence: .sisyphus/evidence/task-8-dedupe.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add recall filtering and availability alignment` | Files: `myQuant/news_ingestion/recall/**`, tests

- [ ] 9. Implement DeepSeek evaluator with fake-client TDD, schema validation, retries, and raw-output persistence

  **What to do**: Implement `DeepSeekNewsEvaluator` behind an evaluator interface. Use `openai.OpenAI(api_key=os.environ['DEEPSEEK_API_KEY'], base_url='https://api.deepseek.com')`, model default `deepseek-v4-flash`, temperature `0.0`, max_tokens default `1024`, `response_format={'type':'json_object'}`, and `extra_body={'thinking': {'type': 'disabled'}}`. Prompt language: Chinese instructions, English field names. Schema version `agent_signal_v1`; prompt version `news_impact_v1`. Required JSON object fields: `event`, `relation_type`, `impact_direction`, `impact_strength`, `time_horizon`, `confidence`, `reason`, `evidence`. Validate enums/ranges. On invalid JSON/schema: store `agent_llm_run` + `agent_llm_output` with validation errors and create no `agent_signal`. Retry policy: retry up to 2 times for HTTP 429/500/503 and once for empty/invalid JSON with a concise repair prompt; persist every failed attempt.
  **Must NOT do**: Do not log or persist `DEEPSEEK_API_KEY`. Do not create signals from invalid outputs. Do not require API key for unit tests.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: LLM reliability, validation, and secrets are high-risk.
  - Skills: `test-driven-development`, `systematic-debugging` - Need fake clients and error-path tests.
  - Omitted: `claude-api` - This is DeepSeek/OpenAI-compatible, not Anthropic SDK.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 10,12 | Blocked By: 1,2,8

  **References**:
  - External: `https://api-docs.deepseek.com/` - DeepSeek OpenAI-compatible API and model docs.
  - External: `https://api-docs.deepseek.com/guides/json_mode` - JSON mode limitations.
  - Storage: Task 2 `agent_llm_run`, `agent_llm_output`, `agent_signal`.

  **Acceptance Criteria**:
  - [ ] Valid fake DeepSeek JSON creates one `agent_signal` with expected fields.
  - [ ] Invalid JSON creates `agent_llm_output.validation_status='invalid'` and zero signals.
  - [ ] Missing `DEEPSEEK_API_KEY` fails only LLM live stage with clear error and does not affect non-LLM tests/dry-runs.
  - [ ] Secret hygiene test confirms env var value is absent from DB/report/log strings.

  **QA Scenarios**:
  ```
  Scenario: Valid DeepSeek JSON becomes signal
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_llm_evaluator.py::test_valid_deepseek_json_creates_signal -q
    Expected: Exit 0; one signal row has impact_direction='positive', impact_strength=0.72, confidence=0.68.
    Evidence: .sisyphus/evidence/task-9-valid-llm.txt

  Scenario: Invalid DeepSeek JSON is stored but not signaled
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_llm_evaluator.py::test_invalid_json_persists_output_without_signal -q
    Expected: Exit 0; llm_output row exists with validation error, agent_signal row count is 0.
    Evidence: .sisyphus/evidence/task-9-invalid-llm.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add deepseek evaluator` | Files: `myQuant/news_ingestion/llm/**`, tests

- [ ] 10. Implement offline backfill pipeline and CLI script

  **What to do**: Implement core pipeline in `myQuant/news_ingestion/pipeline.py` and thin CLI at `backtests/scripts/run_agent_news_backfill.py`. CLI options exactly:
  - `--start YYYY-MM-DD`
  - `--end YYYY-MM-DD`
  - `--symbols 300750.SZSE,600519.SSE`
  - `--symbols-from-market-db`
  - `--market-db-path ~/.vntrader/database.db`
  - `--agent-db-path ~/.vntrader/agent_news.db`
  - `--sources cninfo,cls_telegraph,eastmoney`
  - `--recall-strength low|medium|high`
  - `--dry-run`
  - `--skip-llm`
  - `--max-llm-items N` where `0` or omitted means no cap for final run
  - `--resume`
  - `--report-path PATH`
  Pipeline order: init schema → create `agent_backfill_run` → load/discover symbols → ensure profiles → source fetch → save raw/fetch attempts → local recall/dedupe → optional LLM evaluate → save signals → update cursor/run summary → write report.
  **Must NOT do**: Do not perform live source or LLM calls in `--dry-run`. Do not require `DEEPSEEK_API_KEY` when `--skip-llm` or `--dry-run` is set.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: orchestration must be resumable, idempotent, and safe.
  - Skills: `test-driven-development`, `systematic-debugging` - CLI and pipeline need failure-path tests.
  - Omitted: `frontend-design` - CLI only.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 11,12 | Blocked By: 1,2,3,8,9

  **References**:
  - Pattern: `backtests/scripts/run_doublema_daily_all_db.py` - local script and marker/report conventions.
  - Pattern: `myREADME.md` - must use `conda run -n vnpy43`.
  - Storage: Task 2 all repository methods.

  **Acceptance Criteria**:
  - [ ] CLI `--help` exits 0 and lists all options above.
  - [ ] Dry-run over fixture sources writes run summary with candidate counts and creates no LLM rows/signals.
  - [ ] Rerun with `--resume` skips already saved raw news and does not duplicate signals.

  **QA Scenarios**:
  ```
  Scenario: CLI help works
    Tool: Bash
    Steps: conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --help
    Expected: Exit 0; output includes --start, --end, --recall-strength, --dry-run, --max-llm-items.
    Evidence: .sisyphus/evidence/task-10-cli-help.txt

  Scenario: Dry-run requires no DeepSeek key
    Tool: Bash
    Steps: env -u DEEPSEEK_API_KEY conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --start 2024-01-02 --end 2024-01-05 --symbols 300750.SZSE --sources cninfo --recall-strength low --dry-run --report-path backtests/results/agent_news_v01_dry_run_test.md
    Expected: Exit 0; report exists; DB has zero agent_llm_run rows for that run_id.
    Evidence: .sisyphus/evidence/task-10-dry-run.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add offline backfill cli` | Files: `myQuant/news_ingestion/pipeline.py`, `backtests/scripts/run_agent_news_backfill.py`, tests

- [ ] 11. Implement Markdown/JSON reporting for source coverage, counts, samples, and conclusions

  **What to do**: Generate a Markdown report for every run at `backtests/results/<date>_agent_news_v01_<scope>.md` plus optional JSON summary in the same directory. Required report sections: run metadata, command, env `vnpy43`, date range, sources, recall_strength, stock list, source coverage table by source/month, raw item counts, filtered candidate counts, LLM run counts, valid/invalid signal counts, top sample signals, failures/gaps, short conclusion. Include “coverage is partial” where source adapters expose no reliable date-range history.
  **Must NOT do**: Do not include API keys, raw full article bodies, or full LLM prompts in Markdown report; those belong in SQLite.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: report is documentation/output quality plus deterministic file generation.
  - Skills: `test-driven-development` - Snapshot-style tests for report content.
  - Omitted: `internal-comms` - Not corporate communication.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: 12 | Blocked By: 10

  **References**:
  - Pattern: `backtests/results/2026-05-10_doublema_10_20_daily_all_db.md` - prior result Markdown structure.
  - Pattern: `myREADME.md` - report naming convention and required settings.

  **Acceptance Criteria**:
  - [ ] Report generator fixture test writes Markdown with all required sections.
  - [ ] Secret hygiene test confirms a fake API key string is absent from generated Markdown.
  - [ ] Report includes exact 10 stock symbols when run with `--symbols-from-market-db`.

  **QA Scenarios**:
  ```
  Scenario: Report includes required sections
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_reporting.py::test_report_contains_required_sections -q
    Expected: Exit 0; Markdown contains Run Metadata, Source Coverage, Counts, Sample Signals, Failures/Gaps, Short Conclusion.
    Evidence: .sisyphus/evidence/task-11-report-sections.txt

  Scenario: Report redacts secrets
    Tool: Bash
    Steps: conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_reporting.py::test_report_does_not_include_deepseek_api_key -q
    Expected: Exit 0; fake key value does not appear in report text.
    Evidence: .sisyphus/evidence/task-11-secret-redaction.txt
  ```

  **Commit**: NO | Message: `feat(agent-news): add backfill reporting` | Files: `myQuant/news_ingestion/reporting.py`, tests

- [ ] 12. Run source accessibility smoke tests and the requested 10-stock five-year pilot

  **What to do**: After all deterministic tests pass, run live source smoke tests and the full offline pilot. Use exact 10-stock universe from market DB query, date range `2021-01-01` to `2026-05-08` for “five years” aligned to available market data end. If user later wants exact database full range, CLI can run `2020-01-02` to `2026-05-08`, but v0.1 pilot uses five calendar years ending at current DB end. Commands:
  ```bash
  conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q
  AGENT_NEWS_LIVE_TEST=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_live_sources.py -q
  conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --start 2021-01-01 --end 2026-05-08 --symbols-from-market-db --sources cninfo,cls_telegraph,eastmoney --recall-strength medium --report-path backtests/results/$(date +%F)_agent_news_v01_10stocks_5y.md
  ```
  If `DEEPSEEK_API_KEY` is absent, run the full command with `--skip-llm` and report that signal generation was skipped due to missing key; do not fabricate signals.
  **Must NOT do**: Do not hide failed sources. Do not manually edit DB rows to make counts look better. Do not use paid/logged-in sources.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: execution QA across network/LLM/storage/reporting.
  - Skills: `verification-before-completion`, `systematic-debugging` - Need evidence before success claims and root-cause handling for failures.
  - Omitted: `webapp-testing` - No browser.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 13 | Blocked By: 10,11

  **References**:
  - Existing DB: `~/.vntrader/database.db` table `dbbaroverview` - exact stock universe source.
  - Report output: `backtests/results/` - persistent results convention.
  - Env convention: `myREADME.md` - `vnpy43` required.

  **Acceptance Criteria**:
  - [ ] Full test suite passes before pilot.
  - [ ] Live source smoke records either successful parseable records or structured fetch failures for each source.
  - [ ] Pilot report exists under `backtests/results/` and includes counts for all 10 stocks.
  - [ ] `~/.vntrader/agent_news.db` contains nonzero `agent_backfill_run` and `agent_fetch_attempt` rows for the pilot.
  - [ ] If `DEEPSEEK_API_KEY` is present, pilot creates valid `agent_signal` rows or validation-error `agent_llm_output` rows; if absent, report explicitly says LLM skipped.

  **QA Scenarios**:
  ```
  Scenario: Live smoke source test
    Tool: Bash
    Steps: AGENT_NEWS_LIVE_TEST=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_live_sources.py -q
    Expected: Exit 0; each configured source either parses at least one item or stores/asserts a structured failure record.
    Evidence: .sisyphus/evidence/task-12-live-smoke.txt

  Scenario: Five-year 10-stock pilot report
    Tool: Bash
    Steps: conda run -n vnpy43 python backtests/scripts/run_agent_news_backfill.py --start 2021-01-01 --end 2026-05-08 --symbols-from-market-db --sources cninfo,cls_telegraph,eastmoney --recall-strength medium --report-path backtests/results/$(date +%F)_agent_news_v01_10stocks_5y.md
    Expected: Exit 0 or documented partial-source exit code 2 with report generated; report lists all 10 symbols and source coverage/failures.
    Evidence: .sisyphus/evidence/task-12-pilot-report.md
  ```

  **Commit**: NO | Message: `test(agent-news): run v0.1 pilot backfill` | Files: `backtests/results/*agent_news_v01_10stocks_5y.md`, DB evidence only if explicitly tracked separately

- [ ] 13. Update local project documentation with module usage and conventions

  **What to do**: Update local docs (prefer `myREADME.md`, and optionally `backtests/README.md` if created by executor) with: module location, DB path `~/.vntrader/agent_news.db`, command examples, source policy, `DEEPSEEK_API_KEY` env var, `vnpy43` requirement, report location, and warning that v0.1 is offline research/backfill only.
  **Must NOT do**: Do not document credentials or API keys. Do not claim source completeness.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: persistent instructions help future OpenCode sessions.
  - Skills: none - Straightforward local documentation.
  - Omitted: `doc-coauthoring` - This is a small implementation doc update, not a full proposal.

  **Parallelization**: Can Parallel: YES | Wave 4 | Blocks: final verification | Blocked By: 12

  **References**:
  - Pattern: `myREADME.md` - existing local conventions.
  - Pattern: `backtests/results/2026-05-10_doublema_10_20_daily_all_db.md` - report convention.

  **Acceptance Criteria**:
  - [ ] Documentation includes `conda run -n vnpy43` examples.
  - [ ] Documentation includes `export DEEPSEEK_API_KEY=...` as a placeholder only, not a real key.
  - [ ] Documentation states `agent_news.db` is separate from `database.db`.

  **QA Scenarios**:
  ```
  Scenario: Docs include required commands and paths
    Tool: Bash
    Steps: conda run -n vnpy43 python - <<'PY'
    from pathlib import Path
    text = Path('myREADME.md').read_text(encoding='utf-8')
    assert 'conda run -n vnpy43' in text
    assert 'agent_news.db' in text
    assert 'DEEPSEEK_API_KEY' in text
    print('OK')
    PY
    Expected: Exit 0; prints OK.
    Evidence: .sisyphus/evidence/task-13-docs-check.txt

  Scenario: Docs do not contain real DeepSeek key
    Tool: Bash
    Steps: conda run -n vnpy43 python - <<'PY'
    from pathlib import Path
    text = Path('myREADME.md').read_text(encoding='utf-8')
    assert 'sk-' not in text.lower()
    print('OK')
    PY
    Expected: Exit 0; docs contain only placeholder key instructions.
    Evidence: .sisyphus/evidence/task-13-docs-secret-check.txt
  ```

  **Commit**: NO | Message: `docs(agent-news): document v0.1 workflow` | Files: `myREADME.md`, optional `backtests/README.md`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [ ] F1. Plan Compliance Audit — oracle
  - Verify implemented files match this plan, `vnpy43` commands were used, and v0.1 exclusions were respected.
- [ ] F2. Code Quality Review — unspecified-high
  - Review modularity, test quality, idempotency, storage boundaries, and source adapter isolation.
- [ ] F3. Real Manual QA — unspecified-high
  - Execute deterministic tests, CLI help, schema check, dry-run, and live smoke when `AGENT_NEWS_LIVE_TEST=1` is available.
- [ ] F4. Scope Fidelity Check — deep
  - Confirm no strategy execution, live trading, paid-source dependency, scheduler, GUI, or vector DB slipped into v0.1.

## Commit Strategy
- Do not commit unless the user explicitly requests it.
- Suggested commit grouping if requested later:
  1. `feat(agent-news): add contracts and sqlite storage`
  2. `feat(agent-news): add public source adapters`
  3. `feat(agent-news): add recall and deepseek evaluation pipeline`
  4. `feat(agent-news): add backfill cli and reports`
  5. `docs(agent-news): document v0.1 workflow`
- Never commit secrets, `.env`, or database files containing private API output unless explicitly approved.

## Success Criteria
- The module can be understood and tested independently under `myQuant/news_ingestion/`.
- Source adapters can be replaced without changing storage or LLM code.
- `~/.vntrader/agent_news.db` stores raw news, mapping, fetch attempts, LLM runs/outputs, final signals, cursors, stock profiles, and run summaries.
- Re-running the same backfill is idempotent.
- DeepSeek output is validated before signal creation; invalid outputs are stored for audit.
- Reports clearly separate successful coverage from source gaps/failures.
- Future strategies can query `agent_signal` by `vt_symbol` and `available_at` without parsing raw JSON.
