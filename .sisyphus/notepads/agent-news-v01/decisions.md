# Decisions - agent-news-v01

## 2026-05-10 Session start
- Use package root `myQuant/news_ingestion/`.
- Use scripts under `backtests/scripts/` and reports under `backtests/results/`.
- Implement strict TDD only at key risk points (contracts, SQLite/idempotency, recall/lookahead, DeepSeek validation, pipeline CLI safety); use automated verification for routine implementation tasks.
- Store raw news, fetch attempts, raw LLM output, validation errors, prompt/schema/model versions, and final signals.
- Keep `available_at` for lookahead-safe future strategy reads.
