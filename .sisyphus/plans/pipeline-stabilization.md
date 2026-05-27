# Pipeline Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 pipeline stability issues before modularization — trading calendar, version tracking, schema unification, daily signal persistence, and StockProfile in LLM prompt.

**Architecture:** Surgical changes to existing code. No strategy logic changes. No收益优化. Each phase is independent and can be committed separately.

**Tech Stack:** Python 3.12, SQLite, peewee, pytest

---

## Context: What We're Fixing

From `docs/current_pipeline_io_audit.md`:

| # | Issue | Severity | Root Cause |
|---|-------|----------|------------|
| 1 | Weekend/holiday signals lost | HIGH | `trading_date = available_at.date()` with no calendar |
| 2 | v0.2/v0.22 schema confusion | MEDIUM | `event_count` inserted into `news_count` column |
| 3 | Temp DB discards debug fields | MEDIUM | `make_signal_db()` only creates 7 columns |
| 4 | No signal_version in DB | MEDIUM | `CONFIG_VERSION` not stored in agent_signal |
| 5 | StockProfile "未知" in prompt | LOW | `_build_prompt()` doesn't receive profile |

---

## File Map

### Files to CREATE
| File | Purpose |
|------|---------|
| `myQuant/news_ingestion/calendar.py` | Trading calendar: `next_trading_day()`, `is_trading_day()` |
| `myQuant/news_ingestion/tests/test_calendar.py` | Calendar unit tests |
| `docs/pipeline_stabilization_migration.md` | Migration notes |

### Files to MODIFY
| File | Changes |
|------|---------|
| `myQuant/news_ingestion/llm/evaluator.py` | Add `profile` param to `evaluate()` and `_build_prompt()` |
| `myQuant/news_ingestion/scoring/config.py` | Add `AGGREGATION_VERSION`, `RELATION_WEIGHT_VERSION` |
| `myQuant/news_ingestion/scoring/daily_aggregator.py` | Unified output schema with all debug fields |
| `myQuant/news_ingestion/storage/sqlite.py` | Add `signal_version` to AgentSignalModel |
| `myQuant/news_ingestion/contracts.py` | Add `signal_version` to AgentSignal dataclass |
| `backtests/run_matrix.py` | Use unified schema, persist debug fields |
| `myQuant/news_ingestion/tests/test_llm_evaluator.py` | Add prompt content tests |

---

## Phase 1: Trading Calendar

### Task 1.1: Create trading calendar module

**Files:**
- Create: `myQuant/news_ingestion/calendar.py`
- Create: `myQuant/news_ingestion/tests/test_calendar.py`

- [ ] **Step 1: Write the failing test**

```python
# myQuant/news_ingestion/tests/test_calendar.py
from datetime import date, datetime, time
from myQuant.news_ingestion.calendar import next_trading_day, is_trading_day, available_at_to_trading_date


def test_saturday_maps_to_monday():
    # 2026-05-23 is Saturday
    assert next_trading_day(date(2026, 5, 23)) == date(2026, 5, 25)


def test_sunday_maps_to_monday():
    # 2026-05-24 is Sunday
    assert next_trading_day(date(2026, 5, 24)) == date(2026, 5, 25)


def test_friday_maps_to_friday():
    # 2026-05-22 is Friday (trading day)
    assert next_trading_day(date(2026, 5, 22)) == date(2026, 5, 22)


def test_holiday_maps_to_next_trading_day():
    # 2026-01-01 is New Year's Day (holiday)
    result = next_trading_day(date(2026, 1, 1))
    assert result >= date(2026, 1, 2)
    assert is_trading_day(result)


def test_is_trading_day_weekday():
    assert is_trading_day(date(2026, 5, 22)) is True


def test_is_trading_day_weekend():
    assert is_trading_day(date(2026, 5, 23)) is False


def test_available_at_to_trading_date_intraday():
    # Trading day, before 15:00
    dt = datetime(2026, 5, 22, 10, 30)
    assert available_at_to_trading_date(dt) == "2026-05-22"


def test_available_at_to_trading_date_after_close():
    # Trading day, after 15:00 → next trading day
    dt = datetime(2026, 5, 22, 15, 30)
    assert available_at_to_trading_date(dt) == "2026-05-25"


def test_available_at_to_trading_date_weekend():
    # Saturday → next Monday
    dt = datetime(2026, 5, 23, 10, 0)
    assert available_at_to_trading_date(dt) == "2026-05-25"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_calendar.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'myQuant.news_ingestion.calendar'"

- [ ] **Step 3: Implement trading calendar**

```python
# myQuant/news_ingestion/calendar.py
"""A-share trading calendar — maps dates to trading days."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

# A-share holidays 2020-2026 (fixed-date + computed)
# This is a minimal set. Extend as needed.
_HOLIDAYS: set[date] = set()

def _populate_holidays() -> None:
    """Populate known A-share holidays."""
    # New Year's Day
    for year in range(2020, 2027):
        _HOLIDAYS.add(date(year, 1, 1))
    # Spring Festival (approximate — typically Jan/Feb, 7 days)
    spring_festival_ranges = [
        (2020, 1, 24, 1, 30), (2021, 2, 11, 2, 17), (2022, 1, 31, 2, 6),
        (2023, 1, 21, 1, 27), (2024, 2, 10, 2, 16), (2025, 1, 28, 2, 3),
        (2026, 2, 17, 2, 23),
    ]
    for year, sm, sd, em, ed in spring_festival_ranges:
        d = date(year, sm, sd)
        end = date(year, em, ed)
        while d <= end:
            _HOLIDAYS.add(d)
            d += timedelta(days=1)
    # Qingming Festival (April 4-6)
    for year in range(2020, 2027):
        for day in [4, 5, 6]:
            try:
                _HOLIDAYS.add(date(year, 4, day))
            except ValueError:
                pass
    # Labor Day (May 1-5)
    for year in range(2020, 2027):
        for day in range(1, 6):
            _HOLIDAYS.add(date(year, 5, day))
    # Dragon Boat Festival (approximate June)
    dragon_boat = [
        (2020, 6, 25, 6, 27), (2021, 6, 12, 6, 14), (2022, 6, 3, 6, 5),
        (2023, 6, 22, 6, 24), (2024, 6, 8, 6, 10), (2025, 5, 31, 6, 2),
        (2026, 6, 19, 6, 21),
    ]
    for year, sm, sd, em, ed in dragon_boat:
        d = date(year, sm, sd)
        end = date(year, em, ed)
        while d <= end:
            _HOLIDAYS.add(d)
            d += timedelta(days=1)
    # Mid-Autumn Festival (approximate September)
    mid_autumn = [
        (2020, 10, 1, 10, 8),  # Combined with National Day
        (2021, 9, 19, 9, 21), (2022, 9, 10, 9, 12),
        (2023, 9, 29, 10, 6), (2024, 9, 15, 9, 17),
        (2025, 10, 6, 10, 8), (2026, 9, 25, 9, 27),
    ]
    for year, sm, sd, em, ed in mid_autumn:
        d = date(year, sm, sd)
        end = date(year, em, ed)
        while d <= end:
            _HOLIDAYS.add(d)
            d += timedelta(days=1)
    # National Day (October 1-7)
    for year in range(2020, 2027):
        for day in range(1, 8):
            _HOLIDAYS.add(date(year, 10, day))

_populate_holidays()

CLOSE_TIME = time(15, 0, 0)


def is_trading_day(d: date) -> bool:
    """Check if a date is an A-share trading day (not weekend, not holiday)."""
    if d.weekday() >= 5:
        return False
    return d not in _HOLIDAYS


def next_trading_day(d: date) -> date:
    """Return the next trading day on or after the given date."""
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def available_at_to_trading_date(available_at: datetime) -> str:
    """Map available_at datetime to trading_date string.

    Rules:
    - If available_at is before 15:00 on a trading day → that day
    - If available_at is after 15:00 on a trading day → next trading day
    - If available_at is on a non-trading day → next trading day
    """
    d = available_at.date()
    if is_trading_day(d) and available_at.time() < CLOSE_TIME:
        return d.isoformat()
    return next_trading_day(d + timedelta(days=1)).isoformat()
```

- [ ] **Step 4: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_calendar.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add myQuant/news_ingestion/calendar.py myQuant/news_ingestion/tests/test_calendar.py
git commit -m "feat: add A-share trading calendar with next_trading_day()"
```

### Task 1.2: Integrate calendar into evaluator

**Files:**
- Modify: `myQuant/news_ingestion/llm/evaluator.py:331`

- [ ] **Step 1: Update _make_signal to use trading calendar**

In `evaluator.py`, line 331, change:
```python
# BEFORE:
trading_date=available_at.date().isoformat(),

# AFTER:
trading_date=available_at_to_trading_date(available_at),
```

Add import at top of file:
```python
from myQuant.news_ingestion.calendar import available_at_to_trading_date
```

- [ ] **Step 2: Run existing tests**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_llm_evaluator.py -v`
Expected: All PASS (existing tests use datetime(2026, 5, 8, 10, 0) which is a Friday, so no change)

- [ ] **Step 3: Commit**

```bash
git add myQuant/news_ingestion/llm/evaluator.py
git commit -m "fix: use trading calendar for trading_date mapping"
```

---

## Phase 2: Version Fields

### Task 2.1: Add version fields to config and contracts

**Files:**
- Modify: `myQuant/news_ingestion/scoring/config.py`
- Modify: `myQuant/news_ingestion/contracts.py`
- Modify: `myQuant/news_ingestion/storage/sqlite.py`

- [ ] **Step 1: Add version constants to config.py**

```python
# Add after CONFIG_VERSION in config.py:
AGGREGATION_VERSION = "v0.22"
RELATION_WEIGHT_VERSION = "v0.22"
HORIZON_WEIGHT_VERSION = "v0.22"
EVENT_DEDUP_VERSION = "v0.22"
```

- [ ] **Step 2: Add signal_version to AgentSignal dataclass**

In `contracts.py`, add to AgentSignal:
```python
signal_version: str = ""  # e.g., "v0.22" or "v0.2"
```

- [ ] **Step 3: Add signal_version to AgentSignalModel**

In `sqlite.py`, add to AgentSignalModel:
```python
signal_version = TextField(null=True)
```

Update `save_signal()` to include signal_version.

- [ ] **Step 4: Run existing tests**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add myQuant/news_ingestion/scoring/config.py myQuant/news_ingestion/contracts.py myQuant/news_ingestion/storage/sqlite.py
git commit -m "feat: add signal_version field to AgentSignal and DB schema"
```

---

## Phase 3: Unified daily_agent_signal Schema

### Task 3.1: Define unified output schema

**Files:**
- Modify: `myQuant/news_ingestion/scoring/daily_aggregator.py`

- [ ] **Step 1: Update run_v0_22_pipeline output**

Change output dict in `run_v0_22_pipeline()` (line 143) to include all fields:
```python
results.append({
    "trading_date": dt,
    "vt_symbol": vs,
    "signal_version": CONFIG_VERSION,
    "daily_agent_signal": round(daily_sig, 6),
    "daily_direction": direction,
    "agent_label": "v0.22",
    "raw_daily_signal": round(raw_daily, 6),
    "news_count": 0,  # v0.22 doesn't use this
    "event_count": m,
    "model_count": 0,  # filled by caller if multi-model
    "mixed_intensity": round(mixed_int, 6),
    "risk_penalty": round(risk_pen, 6),
    "created_at": datetime.now().isoformat(),
})
```

- [ ] **Step 2: Update run_v0_2_pipeline output**

Change output dict in `run_v0_2_pipeline()` (line 189) to match unified schema:
```python
results.append({
    "trading_date": dt,
    "vt_symbol": vs,
    "signal_version": "v0.2",
    "daily_agent_signal": round(sig, 6),
    "daily_direction": direction,
    "agent_label": "v0.2",
    "raw_daily_signal": round(sig, 6),  # v0.2 has no intermediate
    "news_count": n,
    "event_count": 0,  # v0.2 doesn't dedup events
    "model_count": 0,
    "mixed_intensity": 0.0,  # v0.2 doesn't compute this
    "risk_penalty": 1.0,  # v0.2 doesn't apply penalty
    "created_at": datetime.now().isoformat(),
})
```

- [ ] **Step 3: Run generate_daily_signals.py**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/scripts/generate_daily_signals.py --db-path ~/.vntrader/agent_news_em_600309.db --vt-symbol 600309.SSE --compare`
Expected: Both v0.2 and v0.22 outputs with unified fields

- [ ] **Step 4: Commit**

```bash
git add myQuant/news_ingestion/scoring/daily_aggregator.py
git commit -m "feat: unify daily_agent_signal schema across v0.2 and v0.22"
```

### Task 3.2: Update make_signal_db to use unified schema

**Files:**
- Modify: `backtests/run_matrix.py`

- [ ] **Step 1: Update make_signal_db schema**

```python
def make_signal_db(signals, version):
    fd, path = tempfile.mkstemp(suffix=".db", prefix=f"sig_{version}_")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE daily_agent_signal(
        entry_date TEXT, daily_agent_signal REAL, daily_direction TEXT,
        signal_version TEXT, agent_label TEXT,
        raw_daily_signal REAL, news_count INTEGER DEFAULT 0,
        event_count INTEGER DEFAULT 0, model_count INTEGER DEFAULT 0,
        mixed_intensity REAL DEFAULT 0.0, risk_penalty REAL DEFAULT 1.0,
        created_at TEXT)""")
    for s in signals:
        conn.execute("INSERT INTO daily_agent_signal VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            s.get("trading_date", ""), s.get("daily_agent_signal", 0),
            s.get("daily_direction", "neutral"),
            s.get("signal_version", version),
            s.get("agent_label", version),
            s.get("raw_daily_signal", 0),
            s.get("news_count", 0), s.get("event_count", 0),
            s.get("model_count", 0),
            s.get("mixed_intensity", 0), s.get("risk_penalty", 1.0),
            s.get("created_at", ""),
        ))
    conn.commit(); conn.close()
    return path
```

- [ ] **Step 2: Run matrix phase 2**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python backtests/run_matrix.py --phase 2`
Expected: CSV with unified fields

- [ ] **Step 3: Commit**

```bash
git add backtests/run_matrix.py
git commit -m "feat: use unified daily_agent_signal schema in backtest temp DB"
```

---

## Phase 4: Persist daily_agent_signal

### Task 4.1: Add daily_agent_signal table to SQLite

**Files:**
- Modify: `myQuant/news_ingestion/storage/sqlite.py`

- [ ] **Step 1: Add AgentDailySignalModel**

```python
class AgentDailySignalModel(Model):
    id = IntegerField(primary_key=True, constraints=[SQL("AUTOINCREMENT")])
    trading_date = TextField(null=True)
    vt_symbol = TextField(null=True)
    signal_version = TextField(null=True)
    daily_agent_signal = FloatField(null=True)
    daily_direction = TextField(null=True)
    agent_label = TextField(null=True)
    raw_daily_signal = FloatField(null=True)
    news_count = IntegerField(null=True)
    event_count = IntegerField(null=True)
    model_count = IntegerField(null=True)
    mixed_intensity = FloatField(null=True)
    risk_penalty = FloatField(null=True)
    created_at = DateTimeField(null=True)

    class Meta:
        table_name = "agent_daily_signal"
        indexes = (
            (("trading_date", "vt_symbol", "signal_version"), True),
        )
```

Add to `AGENT_MODELS` tuple.

- [ ] **Step 2: Add save_daily_signal method to repository**

```python
def save_daily_signal(self, signal: dict) -> int:
    self.initialize_schema()
    data = {
        "trading_date": signal.get("trading_date"),
        "vt_symbol": signal.get("vt_symbol"),
        "signal_version": signal.get("signal_version"),
        "daily_agent_signal": signal.get("daily_agent_signal"),
        "daily_direction": signal.get("daily_direction"),
        "agent_label": signal.get("agent_label"),
        "raw_daily_signal": signal.get("raw_daily_signal"),
        "news_count": signal.get("news_count", 0),
        "event_count": signal.get("event_count", 0),
        "model_count": signal.get("model_count", 0),
        "mixed_intensity": signal.get("mixed_intensity", 0),
        "risk_penalty": signal.get("risk_penalty", 1.0),
        "created_at": datetime.now(),
    }
    AgentDailySignalModel.insert(data).on_conflict(
        conflict_target=(
            AgentDailySignalModel.trading_date,
            AgentDailySignalModel.vt_symbol,
            AgentDailySignalModel.signal_version,
        ),
        update=data,
    ).execute()
    row = AgentDailySignalModel.get(
        (AgentDailySignalModel.trading_date == data["trading_date"])
        & (AgentDailySignalModel.vt_symbol == data["vt_symbol"])
        & (AgentDailySignalModel.signal_version == data["signal_version"])
    )
    return int(row.id)
```

- [ ] **Step 3: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_storage_sqlite.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add myQuant/news_ingestion/storage/sqlite.py
git commit -m "feat: add agent_daily_signal table for persistent daily signals"
```

### Task 4.2: Update generate_daily_signals to persist

**Files:**
- Modify: `backtests/scripts/generate_daily_signals.py`

- [ ] **Step 1: Add --persist flag**

Add `--persist` argument that writes to the agent DB's `agent_daily_signal` table instead of (or in addition to) JSON.

- [ ] **Step 2: Commit**

```bash
git add backtests/scripts/generate_daily_signals.py
git commit -m "feat: add --persist flag to generate_daily_signals.py"
```

---

## Phase 5: StockProfile in LLM Prompt

### Task 5.1: Pass StockProfile to evaluator

**Files:**
- Modify: `myQuant/news_ingestion/llm/evaluator.py`
- Modify: `myQuant/news_ingestion/pipeline.py`

- [ ] **Step 1: Add profile parameter to evaluate()**

```python
def evaluate(
    self,
    mapped_news: MappedNews,
    news_item: RawNewsItem,
    profile: StockProfile | None = None,
) -> tuple[LLMRunRecord, LLMOutputRecord, AgentSignal | None]:
```

- [ ] **Step 2: Update _build_prompt to use profile**

```python
def _build_prompt(self, mapped_news: MappedNews, news_item: RawNewsItem, profile: StockProfile | None = None) -> str:
    name = profile.name if profile else "未知"
    industry = ", ".join(profile.industry) if profile and profile.industry else "未知"
    products = ", ".join(profile.products) if profile and profile.products else "未知"
    supply = ""
    if profile:
        up = ", ".join(profile.upstream) if profile.upstream else ""
        down = ", ".join(profile.downstream) if profile.downstream else ""
        supply = f"{up} | {down}" if up or down else "未知"
    else:
        supply = "未知"

    return "\n".join(
        (
            "你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。",
            "任务：分析新闻对指定股票的影响，字段名必须使用英文。",
            f"新闻标题：{news_item.title}",
            f"新闻内容：{news_item.content}",
            f"股票vt_symbol：{mapped_news.vt_symbol}",
            f"股票代码：{mapped_news.symbol}",
            f"交易所：{mapped_news.exchange}",
            f"股票名称：{name}",
            f"行业：{industry}",
            f"产品：{products}",
            f"上游/下游：{supply}",
            f"召回关系提示：{mapped_news.relation_hint.value}",
            # ... rest unchanged
        )
    )
```

- [ ] **Step 3: Update pipeline.py to pass profile**

In `pipeline.py`, around line 301:
```python
profile = profiles.get(mapping.vt_symbol)
llm_run, llm_output, signal = self._evaluator.evaluate(mapping, news_item, profile=profile)
```

- [ ] **Step 4: Add prompt content test**

```python
def test_prompt_contains_stock_profile(mapped_news, news_item):
    from myQuant.news_ingestion.contracts import StockProfile
    profile = StockProfile(
        vt_symbol="300750.SZSE",
        name="宁德时代",
        industry=("新能源", "动力电池"),
        products=("动力电池", "储能电池"),
        upstream=("碳酸锂",),
        downstream=("新能源汽车",),
    )
    client = FakeClient([valid_payload()])
    evaluator = DeepSeekNewsEvaluator(client=client)
    prompt = evaluator._build_prompt(mapped_news, news_item, profile=profile)
    assert "宁德时代" in prompt
    assert "新能源" in prompt
    assert "动力电池" in prompt
    assert "未知" not in prompt
```

- [ ] **Step 5: Run all tests**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests/test_llm_evaluator.py -v`
Expected: All PASS including new test

- [ ] **Step 6: Commit**

```bash
git add myQuant/news_ingestion/llm/evaluator.py myQuant/news_ingestion/pipeline.py myQuant/news_ingestion/tests/test_llm_evaluator.py
git commit -m "feat: pass StockProfile to LLM prompt (fix 未知 hardcoding)"
```

---

## Phase 6: Audit Regression Tests

### Task 6.1: Update audit script

**Files:**
- Modify: `scripts/audit_current_pipeline.py`

- [ ] **Step 1: Add new checks**

Add checks for:
- trading_date is all valid trading days (using calendar module)
- daily_agent_signal has signal_version
- news_count vs event_count semantic correctness
- v0.22 debug fields are non-null
- prompt contains StockProfile (check DB for 未知 patterns)

- [ ] **Step 2: Run audit**

Run: `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python scripts/audit_current_pipeline.py`
Expected: All HIGH risks resolved

- [ ] **Step 3: Commit**

```bash
git add scripts/audit_current_pipeline.py
git commit -m "feat: add regression checks for pipeline stabilization"
```

---

## Phase 7: Migration Notes

### Task 7.1: Write migration documentation

**Files:**
- Create: `docs/pipeline_stabilization_migration.md`

- [ ] **Step 1: Document schema changes**

Document:
- `agent_signal` table: new `signal_version` column
- `agent_daily_signal` table: new table
- `daily_agent_signal` JSON: new fields added
- `make_signal_db()`: expanded schema
- `_build_prompt()`: new `profile` parameter
- `evaluate()`: new `profile` parameter

- [ ] **Step 2: Document compatibility rules**

- Old JSON files without new fields → backward compatible (defaults applied)
- Old DB without signal_version → nullable, no migration needed
- New code reads old data → works (defaults)
- Old code reads new data → ignores extra fields

- [ ] **Step 3: Commit**

```bash
git add docs/pipeline_stabilization_migration.md
git commit -m "docs: add pipeline stabilization migration notes"
```

---

## Verification Checklist

After all phases complete:

- [ ] `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python -m pytest myQuant/news_ingestion/tests -q` — all pass
- [ ] `PYTHONDONTWRITEBYTECODE=1 conda run -n vnpy43 python scripts/audit_current_pipeline.py` — no HIGH risks
- [ ] Weekend news maps to Monday trading_date
- [ ] v0.2 and v0.22 JSON files have unified schema
- [ ] signal_version present in agent_signal DB
- [ ] StockProfile data appears in LLM prompt (no 未知)
- [ ] daily_agent_signal persisted in DB
- [ ] Backtest reads from persisted daily_agent_signal
