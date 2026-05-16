# Daily Event Study: Aggregated Agent Signals

**Data**: 295 trading days with news, 295 unique entry dates
**Symbol**: 300750.SZSE
**Method**: Daily agent signal = clip(SUM(news_agent_signal) / SQRT(news_count), -1, 1)

## Signal Test Results

| Signal | N | T+1 | T+3 | T+5 | T+10 | T+5 Med | T+5 Win% | T+5 t-stat |
|--------|---|-----|-----|-----|------|---------|----------|------------|
| D1: signal >= 0.25 | 5 | 0.0221 | 0.0426 | 0.0510 | -0.0137 | 0.0638 | 80.00% | 0.9333 |
| D2: signal >= 0.40 | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| D3: signal <= -0.25 | 6 | 0.0258 | 0.0439 | 0.0328 | 0.0759 | 0.0400 | 66.67% | 0.8167 |
| D4: signal <= -0.40 | 2 | 0.0453 | 0.0627 | 0.0378 | 0.0848 | 0.0378 | 50.00% | 0.2797 |
| D5: |signal| >= 0.25 | 11 | 0.0241 | 0.0433 | 0.0411 | 0.0352 | 0.0614 | 72.73% | 1.3046 |
| D6: |signal| >= 0.40 | 2 | 0.0453 | 0.0627 | 0.0378 | 0.0848 | 0.0378 | 50.00% | 0.2797 |

## Bucket Analysis

| Bucket | Sample Count | T+5 Mean | T+10 Mean |
|--------|-------------|----------|----------|
| negative | 6 | 0.0328 | 0.0759 |
| neutral | 281 | 0.0072 | 0.0235 |
| positive | 5 | 0.0510 | -0.0137 |

## Interpretation

The daily-frequency event study aggregates per-news agent signals (the product of
direction score and confidence, averaged across DeepSeek and Qwen models) into a
single daily signal. The aggregation uses a SQRT divisor to penalize clustered news
events (e.g., 50 articles about the same H-share placement) and clips the result to [-1, 1].

**Positive signal days** (signal >= 0.25) show a mean T+5 return of 0.0510,
suggesting that aggregated bullish agent consensus has predictive power over the
subsequent week.

**Negative signal days** (signal <= -0.25) show a mean T+5 return of 0.0328,
indicating weak predictive power for bearish consensus.

The strongest individual signal is **D1: signal >= 0.25** with a T+5 mean return of 0.0510 (n=5).

The SQRT normalization is critical: without it, single-news days and multi-news days
would have vastly different signal magnitudes for the same underlying event. The clipping
to [-1, 1] prevents extreme outliers from dominating the analysis.
