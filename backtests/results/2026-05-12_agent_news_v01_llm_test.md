# Agent News v0.1 Backfill Report — 2026-05-12

## Run Metadata

- **Run ID**: `backfill-c781e01024ce`
- **Command**: `run_agent_news_backfill.py`
- **Date Range**: 2026-05-01 to 2026-05-07
- **Sources**: eastmoney
- **Recall Strength**: medium

## Stock List

- `300750.SZSE`

## Source Coverage

| Source | Items Fetched | Errors |
|--------|--------------|--------|
| eastmoney (partial) | 500 | 0 |

## Counts

- **Raw Items**: 500
- **Filtered Candidates (after recall/dedupe)**: 410
- **LLM Runs**: 3
- **Valid Signals**: 3
- **Invalid Signals**: 0

## Top Sample Signals

- **300750.SZSE** | 控股股东无偿捐赠部分公司股份 | neutral | strength=0.3 | confidence=0.7
- **300750.SZSE** | 宁德时代发布H股证券变动月报表 | neutral | strength=0.1 | confidence=0.9
- **300750.SZSE** | 宁德时代完成配售H股 | positive | strength=0.7 | confidence=0.8

## Failures / Gaps

_No errors._

## Short Conclusion

Backfill run `backfill-c781e01024ce` completed: 500 raw items → 410 candidates → 3 signals. No errors.