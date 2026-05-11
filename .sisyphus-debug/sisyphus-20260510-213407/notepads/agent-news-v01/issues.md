# Issues - agent-news-v01

## 2026-05-10 Session start
- Public sources may be incomplete or blocked; failures must be structured and summarized.
- DeepSeek JSON mode is not strict schema; validate locally.
- API key must never be persisted or logged.

## 2026-05-10 Task 1 contracts
- `pytest` was missing from the `vnpy43` environment; installed it with `conda run -n vnpy43 python -m pip install pytest` before running required test commands.
- Broader suite issue is pre-existing/outside Task 1 scope: `conda run -n vnpy43 python -m pytest tests/test_alpha101.py -q` fails during collection with `ModuleNotFoundError: No module named 'polars'` at `tests/test_alpha101.py:2`; Task 1 targeted tests pass.

## 2026-05-10 Task 2 SQLite storage
- No new blocker. Note: broad `git status` still shows `.sisyphus/`, `backtests/`, `myQuant/`, and `myREADME.md` as untracked in this working tree; do not treat those as solely Task 2 changes without checking orchestrator context.

## 2026-05-10 Task 3 stock profiles/universe
- No new blocker. Market DB discovery is read-only (`mode=ro`) and Task 3 tests use fixture/temp DBs only; profile persistence is isolated to explicit `agent_news.db` temp paths.

## 2026-05-10 Task 4 source adapter interface
- No new blocker. The first red test failed at collection because `myQuant.news_ingestion.sources` did not exist yet, then passed after adding the source package and HTTP wrapper.
