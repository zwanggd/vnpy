---
name: safe-db-operations
description: |
  Use when proposing ANY database write, DELETE, UPDATE, DROP, TRUNCATE, or schema migration
  on production SQLite databases (~/.vntrader/agent_news*.db or similar). Enforces mandatory
  guardrails: backup first, SELECT COUNT before any DELETE, never execute destructive SQL
  without user confirmation.
---

## Safe Database Operations

### Iron Law

```
NEVER execute destructive SQL without:
1. A verified backup that completed successfully
2. SELECT COUNT(*) showing EXACTLY what rows will be affected
3. User confirmation of the count and scope
```

Violating any of these three steps = data loss risk. No exceptions for "quick fixes," "one-liner deletes," or "I know what I'm doing."

### When to Use

Trigger: ANY proposed `DELETE`, `DROP`, `UPDATE` (non-upsert), `TRUNCATE`, `ALTER TABLE`, schema change, or bulk data modification on `~/.vntrader/agent_news*.db`.

Proactively invoke when the agent or user mentions "clean up," "remove empties," "delete," "drop," or "reset" in context of databases.

### Three-Step Guardrail

**Step 1 — Backup (non-negotiable)**

```python
# BEFORE any write or delete operation
from myQuant.news_ingestion.storage.backup import backup_agent_db
backup_path = backup_agent_db(db_path)
print(f"Backup created: {backup_path}")
```

If backup fails → **stop immediately**. Do not proceed without a valid backup file that is at least as large as the source DB.

**Step 2 — Preview scope**

```sql
-- Show exactly what will be affected
SELECT COUNT(*) FROM target_table WHERE <your_condition>;
SELECT * FROM target_table WHERE <your_condition> LIMIT 5;  -- sample
```

Report the count to the user. Use a dry-run first.

**Step 3 — User confirmation**

```
"I'm about to DELETE 1,221 rows from agent_raw_news WHERE content IS NULL OR content=''.
These rows have title='XXX', 'YYY', ... (showing sample).
Continue?"
```

Only execute after explicit "yes" or "proceed."

### Unsafe → Safe Patterns

| Unsafe | Safe |
|--------|------|
| `DELETE FROM agent_raw_news WHERE content IS NULL` | Run backup → `SELECT COUNT(*)` → user confirms → execute |
| `DROP TABLE IF EXISTS daily_agent_signal` | Backup → export table to CSV → user confirms → drop |
| `sqlite3 db ".recover"` on production DB | Copy DB to temp location → recover copy → never operate on live file |
| `DELETE FROM t WHERE ...` without scope check | Always `SELECT COUNT(*) FROM t WHERE ...` first |

### Red Flags — STOP Immediately

If you catch yourself or the agent:
- "Quick delete, no need to backup"
- "I'll just run .recover after if needed" (recover doesn't recover data deleted via DELETE — `.recover` reads freelist pages, but `PRAGMA secure_delete=1` zeros them)
- "It's just empty rows, nothing valuable"
- Proposing DELETE without showing a SELECT COUNT first
- Using `sqlite3` command-line directly on production DBs

**All of these mean: STOP. Follow the three-step guardrail.**

### Agent News DB Architecture

Production databases live at `~/.vntrader/agent_news_{symbol}.db` (e.g., `agent_news_600309.db`).

**Managed by `AgentNewsSqliteRepository`** (`myQuant/news_ingestion/storage/sqlite.py`):
- All writes are UPSERTs (INSERT ... ON CONFLICT ... UPDATE) — safe by design
- No DELETE or DROP operations in the repository
- `initialize_schema()` uses `CREATE TABLE IF NOT EXISTS` — idempotent

**Raw SQL scripts (HIGHEST RISK)** — bypass the repository:
- `qwen-benchmark/scripts/archive/daily_event_study_pipeline.py` — contains `DROP TABLE IF EXISTS daily_agent_signal`
- `qwen-benchmark/scripts/analyze_all_news.py` — raw INSERT into `news_analysis` table
- `backtests/scripts/eval_all_unevaluated.py` — opens per-symbol DBs via repository

**Read-only consumers** (safe):
- `strategies/macd_agent_strategy.py`
- `backtests/scripts/audit_either_safe.py`
- `backtests/scripts/daily_attribution.py`
- `backtests/scripts/equity_reconciliation.py`

### Backup Chain

Call `backup_agent_db(db_path)` from `myQuant.news_ingestion.storage.backup` — it:
1. Copies the DB file to `~/.vntrader/backups/agent_news_{symbol}_{timestamp}.db`
2. Uses SQLite's native backup API for atomic, consistent snapshots
3. Keeps the last N backups (configurable, default: 3)
4. Returns the backup path on success; raises on failure

### Voice

- Lead with the Iron Law
- Be concrete: name files, functions, exact SQL patterns
- Tie every rule to a specific past failure
- No "best practices" fluff — only "you will lose data if you skip this"
- Sound like an engineer who's been burned, not a textbook
