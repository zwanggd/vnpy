# Agent News v0.1 Backfill Report — 2026-05-12

## Run Metadata

- **Run ID**: `backfill-4315bb636794`
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
- **LLM Runs**: 410
- **Valid Signals**: 410
- **Invalid Signals**: 0

## Top Sample Signals

- **300750.SZSE** | 控股股东无偿捐赠部分公司股份 | neutral | strength=0.3 | confidence=0.7
- **300750.SZSE** | 宁德时代发布H股证券变动月报表 | neutral | strength=0.1 | confidence=0.9
- **300750.SZSE** | 宁德时代完成配售H股 | positive | strength=0.7 | confidence=0.8
- **300750.SZSE** | 宁德时代完成2026年度第二期绿色科技创新债券发行 | positive | strength=0.6 | confidence=0.8
- **300750.SZSE** | 宁德时代发布H股公告(翌日披露报表) | neutral | strength=0.1 | confidence=0.3

## Failures / Gaps

_No errors._

## Short Conclusion

Backfill run `backfill-4315bb636794` completed: 500 raw items → 410 candidates → 410 signals. No errors.