# Pipeline Contract v0.22

> **Date**: 2026-05-27
> **Purpose**: Define input/output contracts for each pipeline stage

---

## Module 1: News Ingestion + Cleaning

### Entry Point

| Item | Value |
|------|-------|
| Script | `backtests/scripts/fetch_news.py` |
| Function | `myQuant.news_ingestion.pipeline.BackfillPipeline.run()` |
| Sources | `myQuant/news_ingestion/sources/{eastmoney,cls,cninfo}.py` |

### Input Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| db_path | str | YES | Agent news SQLite path |
| vt_symbol | str | YES | Stock code (e.g., "600309.SSE") |
| start_date | date | YES | Fetch window start |
| end_date | date | YES | Fetch window end |
| source | str | NO | Source filter (default: all) |

### Output Tables

| Table | Description |
|-------|-------------|
| `agent_raw_news` | Raw news from sources |
| `agent_news_symbol` | News-to-stock mapping |
| `agent_stock_profile` | Stock profile data |

### agent_raw_news Schema

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| id | INTEGER | NO | PK, AUTOINCREMENT |
| source | TEXT | YES | eastmoney/cls/cninfo |
| source_category | TEXT | YES | announcement/flash/financial_news |
| source_item_id | TEXT | YES | Source-side unique ID |
| url | TEXT | YES | News URL |
| title | TEXT | NO | News title |
| content | TEXT | YES | Full text |
| summary | TEXT | YES | Summary |
| published_at | DATETIME | YES | Original publish time |
| discovered_at | DATETIME | YES | Discovery time |
| fetched_at | DATETIME | YES | Fetch time |
| available_at | DATETIME | YES | Computed by RecallEngine |
| raw_payload_json | TEXT | YES | Raw API response |
| content_hash | TEXT | NO | SHA256(title+content) |
| body_status | TEXT | YES | text/fetched/extracted/failed |
| language | TEXT | YES | Default "zh" |
| created_at | DATETIME | YES | Insertion time |

### Dedup Logic

| Dedup Key | Type | Description |
|-----------|------|-------------|
| (source, source_item_id) | UNIQUE | Primary dedup |
| (source, content_hash) | UNIQUE | Fallback dedup |
| (title[:40], date, url.hostname) | NEAR | Near-dedup in RecallEngine |

**Idempotent**: YES — `INSERT ... ON CONFLICT DO UPDATE`

### available_at Computation

```
RecallEngine._available_at(published_at):
  if published_at is datetime:
    return published_at + 5 minutes
  if published_at is date:
    return datetime(date, 15:00:00)
  if published_at is None:
    return None (skip item)
```

### Downstream Consumers

- Module 2 (LLM Evaluation) reads `agent_raw_news` + `agent_news_symbol`

---

## Module 2: LLM Evaluation

### Entry Point

| Item | Value |
|------|-------|
| Script | `backtests/scripts/evaluate_news.py` |
| Function | `DeepSeekNewsEvaluator.evaluate(mapped_news, news_item, profile)` |

### Input

| Input | Source | Required |
|-------|--------|----------|
| mapped_news | agent_news_symbol | YES |
| news_item | agent_raw_news | YES |
| profile | agent_stock_profile | NO (default None) |
| model | config | YES |
| prompt_version | config | YES |

### Output Table: agent_signal

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| id | INTEGER | NO | PK, AUTOINCREMENT |
| raw_news_id | INTEGER | YES | FK to agent_raw_news |
| llm_run_id | INTEGER | YES | FK to agent_llm_run |
| vt_symbol | TEXT | YES | Stock code |
| symbol | TEXT | YES | Numeric code |
| exchange | TEXT | YES | Exchange |
| event | TEXT | YES | Event description |
| relation_type | TEXT | YES | Enum value |
| impact_direction | TEXT | YES | Enum value |
| impact_strength | FLOAT | YES | [0.0, 1.0] |
| time_horizon | TEXT | YES | Enum value |
| confidence | FLOAT | YES | [0.0, 1.0] |
| reason | TEXT | YES | Explanation |
| evidence_json | TEXT | YES | JSON array |
| published_at | DATETIME | YES | Original time |
| available_at | DATETIME | YES | Computed time |
| trading_date | TEXT | YES | ISO date, indexed |
| source | TEXT | YES | Source enum |
| source_item_id | TEXT | YES | Source-side ID |
| prompt_version | TEXT | YES | e.g., "news_impact_v1" |
| schema_version | TEXT | YES | e.g., "agent_signal_v1" |
| signal_version | TEXT | YES | e.g., "v0.22" |
| created_at | DATETIME | YES | Insertion time |

### Unique Constraint

(raw_news_id, llm_run_id, vt_symbol, event, relation_type)

### trading_date Generation

```python
# evaluator.py line 331
trading_date = available_at_to_trading_date(available_at)

# calendar.py
def available_at_to_trading_date(available_at: datetime) -> str:
    d = available_at.date()
    if is_trading_day(d) and available_at.time() < CLOSE_TIME:
        return d.isoformat()
    return next_trading_day(d + timedelta(days=1)).isoformat()
```

**No residual `available_at.date().isoformat()` logic exists.**

### Prompt Construction

```python
# evaluator.py _build_prompt()
profile.name if profile else "未知"
profile.industry if profile else "未知"
profile.products if profile else "未知"
profile.upstream | profile.downstream if profile else "未知"
```

### Downstream Consumers

- Module 3 (Daily Signal) reads `agent_signal`

---

## Module 3: Daily Signal Generation

### Entry Point

| Item | Value |
|------|-------|
| Script | `backtests/scripts/generate_daily_signals.py` |
| Function | `run_v0_22_pipeline(rows)` / `run_v0_2_pipeline(rows)` |

### Input

| Input | Source | Required |
|-------|--------|----------|
| agent_signal rows | DB query | YES |
| vt_symbol filter | CLI arg | NO |
| --persist flag | CLI arg | NO |
| --output path | CLI arg | NO |

### Output: JSON File

Standard 13 fields:

```json
{
  "trading_date": "2020-01-13",
  "vt_symbol": "600309.SSE",
  "signal_version": "v0.22",
  "daily_agent_signal": 0.797329,
  "daily_direction": "positive",
  "agent_label": "v0.22",
  "raw_daily_signal": 0.872989,
  "news_count": 0,
  "event_count": 3,
  "model_count": 0,
  "mixed_intensity": 0.0,
  "risk_penalty": 1.0,
  "created_at": "2026-05-27T10:00:00"
}
```

### Output: agent_daily_signal Table

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| id | INTEGER | NO | PK, AUTOINCREMENT |
| trading_date | TEXT | YES | ISO date |
| vt_symbol | TEXT | YES | Stock code |
| signal_version | TEXT | YES | v0.2/v0.22 |
| daily_agent_signal | REAL | YES | [-1, 1] |
| daily_direction | TEXT | YES | positive/negative/neutral |
| agent_label | TEXT | YES | Version label |
| raw_daily_signal | REAL | YES | Pre-tanh value |
| news_count | INTEGER | YES | v0.2 count |
| event_count | INTEGER | YES | v0.22 count |
| model_count | INTEGER | YES | Multi-model count |
| mixed_intensity | REAL | YES | Conflict metric |
| risk_penalty | REAL | YES | Risk penalty |
| created_at | DATETIME | YES | Creation time |

### Unique Constraint

(trading_date, vt_symbol, signal_version)

### Validation Rules

| Rule | Check |
|------|-------|
| daily_agent_signal ∈ [-1, 1] | `max(-1, min(1, value))` via tanh |
| daily_direction ∈ {positive, negative, neutral} | `compute_daily_direction()` |
| trading_date is A-share trading day | `available_at_to_trading_date()` |
| No duplicate (trading_date, vt_symbol, signal_version) | UNIQUE constraint |

### Persist Idempotency

```python
AgentDailySignalModel.insert(data).on_conflict(
    conflict_target=(trading_date, vt_symbol, signal_version),
    update=data,
)
```

**Idempotent**: YES — upsert on unique constraint

### Backward Compatibility

Old JSON files (without `signal_version`, `agent_label`, etc.) are read via `.get()` with defaults:
```python
s.get("signal_version", version)
s.get("agent_label", version)
s.get("raw_daily_signal", 0)
```

---

## Module 4: Backtest

### Entry Point

| Item | Value |
|------|-------|
| Script | `backtests/run_matrix.py` |
| Function | `make_signal_db(signals, version)` |

### Input

| Input | Source | Required |
|-------|--------|----------|
| daily signal JSON | file | YES |
| market bar data | ~/.vntrader/database.db | YES |
| strategy config | hardcoded | YES |
| transaction cost | hardcoded | YES |

### make_signal_db Schema (12 columns)

```sql
CREATE TABLE daily_agent_signal(
    entry_date TEXT,
    daily_agent_signal REAL,
    daily_direction TEXT,
    signal_version TEXT,
    agent_label TEXT,
    raw_daily_signal REAL,
    news_count INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,
    model_count INTEGER DEFAULT 0,
    mixed_intensity REAL DEFAULT 0.0,
    risk_penalty REAL DEFAULT 1.0,
    created_at TEXT
)
```

### Strategy Consumption

```python
# tech_agent_strategy.py load_agent_signals()
rows = db.execute(
    "SELECT entry_date, daily_agent_signal, daily_direction FROM daily_agent_signal"
).fetchall()
result[d] = {"signal": sig, "direction": direction}
```

**Fields actually read**: entry_date, daily_agent_signal, daily_direction

### Backtest Output: Standard Columns

#### backtest_daily_result

| Column | Type | Description |
|--------|------|-------------|
| trading_date | TEXT | ISO date |
| vt_symbol | TEXT | Stock code |
| close | REAL | Close price |
| daily_agent_signal | REAL | Agent signal |
| daily_direction | TEXT | Agent direction |
| signal_version | TEXT | Version |
| technical_signal | TEXT | Tech indicator signal |
| final_signal | TEXT | Combined signal |
| target_position | INT | Target position |
| actual_position | INT | Actual position |
| daily_pnl | REAL | Daily P&L |
| daily_return | REAL | Daily return |
| cumulative_return | REAL | Cumulative return |
| drawdown | REAL | Drawdown |

#### backtest_trade_record

| Column | Type | Description |
|--------|------|-------------|
| trade_id | TEXT | Unique ID |
| vt_symbol | TEXT | Stock code |
| entry_date | TEXT | Entry date |
| exit_date | TEXT | Exit date |
| side | TEXT | Long/Short |
| entry_price | REAL | Entry price |
| exit_price | REAL | Exit price |
| volume | INT | Volume |
| entry_signal | TEXT | Entry reason |
| exit_signal | TEXT | Exit reason |
| holding_days | INT | Days held |
| net_pnl | REAL | Net P&L |
| return | REAL | Return % |
| signal_version | TEXT | Version |

#### backtest_summary

| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT | Unique run ID |
| vt_symbol | TEXT | Stock code |
| strategy_version | TEXT | Strategy version |
| signal_version | TEXT | Signal version |
| start_date | TEXT | Start date |
| end_date | TEXT | End date |
| total_return | REAL | Total return % |
| annual_return | REAL | Annual return % |
| max_drawdown | REAL | Max drawdown % |
| sharpe_ratio | REAL | Sharpe ratio |
| calmar_ratio | REAL | Calmar ratio |
| win_rate | REAL | Win rate |
| trade_count | INT | Number of trades |
| avg_holding_days | REAL | Avg holding days |
| created_at | TEXT | Creation time |

---

## Version Tracking Summary

| Layer | Field | Location | Example |
|-------|-------|----------|---------|
| LLM Eval | prompt_version | agent_signal | "news_impact_v1" |
| LLM Eval | schema_version | agent_signal | "agent_signal_v1" |
| LLM Eval | signal_version | agent_signal | "v0.22" |
| Daily Signal | signal_version | agent_daily_signal / JSON | "v0.22" |
| Daily Signal | agent_label | agent_daily_signal / JSON | "v0.22" |
| Backtest | signal_version | temp DB / CSV | "v0.22" |
| Backtest | strategy_version | summary CSV | "tech_agent_v1" |

---

## Known Constraints

1. **No residual `available_at.date().isoformat()`** — all trading_date generation uses `available_at_to_trading_date()`
2. **v0.2/v0.22 coexist** — different signal_version, same unique constraint
3. **Old JSON backward compatible** — `.get()` with defaults
4. **Temp DB is ephemeral** — created per backtest run, deleted after
5. **agent_daily_signal is persistent** — survives across runs
