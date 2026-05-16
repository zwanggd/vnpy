#!/usr/bin/env python3
"""
Daily-frequency event study pipeline.

Workflow:
  1. Drop old daily_agent_signal table
  2. Read news_signal_wide, compute per-news signals (score * confidence per agent, averaged)
  3. Aggregate by entry_date: daily_agent_signal = clip(SUM(news_signal) / SQRT(n), -1, 1)
  4. Compute T+1/T+3/T+5/T+10 forward returns from dbbardata (trading-day offsets)
  5. Export daily_agent_signal to CSV
  6. Event study: test 6 signal thresholds against forward returns
  7. Bucket analysis (negative / neutral / positive)
  8. Save results_v2/daily_event_study.csv and .md
"""
import sqlite3
import csv
import math
import os
from statistics import mean, median, stdev
from pathlib import Path

AGENT_NEWS_DB = os.path.expanduser("~/.vntrader/agent_news.db")
PRICE_DB = os.path.expanduser("~/.vntrader/database.db")
RESULTS_DIR = Path("results_v2")
RESULTS_DIR.mkdir(exist_ok=True)

print("Step 1: Dropping old daily_agent_signal table...")
conn = sqlite3.connect(AGENT_NEWS_DB)
conn.execute("DROP TABLE IF EXISTS daily_agent_signal;")
conn.commit()

print("Step 2: Reading news_signal_wide...")
rows = conn.execute("""
    SELECT news_id, title, entry_date,
           ds_score, ds_confidence, qw_score, qw_confidence,
           consensus_direction
    FROM news_signal_wide
    ORDER BY entry_date, news_id
""").fetchall()
print(f"  Loaded {len(rows)} rows")

daily_data = {}
for row in rows:
    news_id, title, entry_date, ds_score, ds_confidence, qw_score, qw_confidence, cons_dir = row

    deepseek_signal = ds_score * ds_confidence
    qwen_signal = qw_score * qw_confidence
    news_agent_signal = (deepseek_signal + qwen_signal) / 2.0
    abs_signal = abs(news_agent_signal)

    if entry_date not in daily_data:
        daily_data[entry_date] = {
            'news_count': 0,
            'pos': 0, 'neg': 0, 'neutral': 0,
            'sum_deepseek': 0.0, 'sum_qwen': 0.0,
            'sum_news_signal': 0.0,
            'max_abs': 0.0, 'top_id': None, 'top_title': None
        }

    dd = daily_data[entry_date]
    dd['news_count'] += 1
    dd['sum_deepseek'] += deepseek_signal
    dd['sum_qwen'] += qwen_signal
    dd['sum_news_signal'] += news_agent_signal

    if cons_dir == 'positive':
        dd['pos'] += 1
    elif cons_dir == 'negative':
        dd['neg'] += 1
    else:
        dd['neutral'] += 1

    if abs_signal > dd['max_abs']:
        dd['max_abs'] = abs_signal
        dd['top_id'] = news_id
        dd['top_title'] = title

print("Step 3: Computing daily aggregates...")
daily_rows = []
for entry_date in sorted(daily_data.keys()):
    dd = daily_data[entry_date]
    date_clean = entry_date[:10] if ' ' in str(entry_date) else str(entry_date)
    n = dd['news_count']

    deepseek_daily = dd['sum_deepseek'] / n
    qwen_daily = dd['sum_qwen'] / n

    raw_daily = dd['sum_news_signal'] / math.sqrt(n)
    daily_signal = max(-1.0, min(1.0, raw_daily))

    if daily_signal >= 0.25:
        direction = 'positive'
    elif daily_signal <= -0.25:
        direction = 'negative'
    else:
        direction = 'neutral'

    daily_rows.append((date_clean, n,
        dd['pos'], dd['neg'], dd['neutral'],
        deepseek_daily, qwen_daily, daily_signal,
        dd['max_abs'], dd['top_id'], dd['top_title'],
        direction, raw_daily))

print("  Creating daily_agent_signal table...")
conn.execute("""
    CREATE TABLE daily_agent_signal (
        entry_date TEXT PRIMARY KEY,
        news_count INTEGER,
        positive_news_count INTEGER,
        negative_news_count INTEGER,
        neutral_news_count INTEGER,
        deepseek_daily_signal REAL,
        qwen_daily_signal REAL,
        daily_agent_signal REAL,
        max_abs_news_signal REAL,
        top_news_id INTEGER,
        top_news_title TEXT,
        daily_direction TEXT,
        raw_daily_signal REAL,
        t1_return REAL,
        t3_return REAL,
        t5_return REAL,
        t10_return REAL
    )
""")
conn.commit()

print("  Inserting daily_agent_signal rows...")
for row in daily_rows:
    conn.execute("""
        INSERT INTO daily_agent_signal
        (entry_date, news_count, positive_news_count, negative_news_count,
         neutral_news_count, deepseek_daily_signal, qwen_daily_signal,
         daily_agent_signal, max_abs_news_signal, top_news_id, top_news_title,
         daily_direction, raw_daily_signal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, row)
conn.commit()
print(f"  Inserted {len(daily_rows)} daily rows")

print("Step 4: Computing daily forward returns...")
price_conn = sqlite3.connect(PRICE_DB)
price_rows = price_conn.execute("""
    SELECT datetime, close_price
    FROM dbbardata
    WHERE symbol='300750' AND exchange='SZSE' AND interval='d'
    ORDER BY datetime
""").fetchall()
price_conn.close()

price_dict = {}
for dt_str, close in price_rows:
    date_str = dt_str[:10]
    price_dict[date_str] = close

trading_dates = sorted(price_dict.keys())
date_to_idx = {d: i for i, d in enumerate(trading_dates)}
total_trading_days = len(trading_dates)

print(f"  Trading dates range: {trading_dates[0]} to {trading_dates[-1]} ({total_trading_days} days)")

returns_to_update = []
for dr in daily_rows:
    entry_date = dr[0]
    entry_str = entry_date[:10] if ' ' in str(entry_date) else str(entry_date)

    if entry_str not in date_to_idx:
        returns_to_update.append((None, None, None, None, entry_str))
        continue

    idx = date_to_idx[entry_str]
    entry_close = price_dict[entry_str]

    forward_returns = []
    for offset in (1, 3, 5, 10):
        future_idx = idx + offset
        if future_idx < total_trading_days:
            future_close = price_dict[trading_dates[future_idx]]
            ret = (future_close - entry_close) / entry_close
        else:
            ret = None
        forward_returns.append(ret)

    returns_to_update.append(tuple(forward_returns) + (entry_str,))

update_count = 0
for t1, t3, t5, t10, entry_str in returns_to_update:
    conn.execute("""
        UPDATE daily_agent_signal
        SET t1_return=?, t3_return=?, t5_return=?, t10_return=?
        WHERE entry_date=?
    """, (t1, t3, t5, t10, entry_str))
    if t1 is not None:
        update_count += 1
conn.commit()
print(f"  Updated forward returns for {update_count}/{len(daily_rows)} rows")

print("Step 5: Exporting daily_agent_signal to CSV...")
csv_path = RESULTS_DIR / "daily_agent_signal.csv"
cursor = conn.execute("SELECT * FROM daily_agent_signal ORDER BY entry_date")
columns = [desc[0] for desc in cursor.description]
rows_data = cursor.fetchall()
with open(csv_path, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(columns)
    writer.writerows(rows_data)
print(f"  Exported {len(rows_data)} rows to {csv_path}")

print("Step 6: Daily event study...")
all_daily = conn.execute("""
    SELECT entry_date, daily_agent_signal, t1_return, t3_return, t5_return, t10_return
    FROM daily_agent_signal
    ORDER BY entry_date
""").fetchall()

signals = [
    ("D1: signal >= 0.25",  lambda s: s["daily_agent_signal"] is not None and s["daily_agent_signal"] >= 0.25),
    ("D2: signal >= 0.40",  lambda s: s["daily_agent_signal"] is not None and s["daily_agent_signal"] >= 0.40),
    ("D3: signal <= -0.25", lambda s: s["daily_agent_signal"] is not None and s["daily_agent_signal"] <= -0.25),
    ("D4: signal <= -0.40", lambda s: s["daily_agent_signal"] is not None and s["daily_agent_signal"] <= -0.40),
    ("D5: |signal| >= 0.25",lambda s: s["daily_agent_signal"] is not None and abs(s["daily_agent_signal"]) >= 0.25),
    ("D6: |signal| >= 0.40",lambda s: s["daily_agent_signal"] is not None and abs(s["daily_agent_signal"]) >= 0.40),
]

def compute_stats(rows_list, return_key):
    valid = [r[return_key] for r in rows_list if r[return_key] is not None]
    if len(valid) == 0:
        return None, 0
    return mean(valid), len(valid)

signal_results = []
for sig_name, condition in signals:
    matching = []
    for d in all_daily:
        sd = {"entry_date": d[0], "daily_agent_signal": d[1],
              "t1_return": d[2], "t3_return": d[3],
              "t5_return": d[4], "t10_return": d[5]}
        if condition(sd):
            matching.append(sd)

    t1_mean, t1_n = compute_stats(matching, "t1_return")
    t3_mean, t3_n = compute_stats(matching, "t3_return")
    t5_mean, t5_n = compute_stats(matching, "t5_return")
    t10_mean, t10_n = compute_stats(matching, "t10_return")

    valid_t5 = [r["t5_return"] for r in matching if r["t5_return"] is not None]
    if len(valid_t5) >= 2:
        t5_med = median(valid_t5)
        t5_win_rate = sum(1 for v in valid_t5 if v > 0) / len(valid_t5)
        sd_val = stdev(valid_t5)
        t5_t_stat = mean(valid_t5) / (sd_val / math.sqrt(len(valid_t5))) if sd_val > 0 else None
    else:
        t5_med = None
        t5_win_rate = None
        t5_t_stat = None

    signal_results.append({
        "signal": sig_name, "sample_count": t5_n if t5_n else 0,
        "t1_mean": t1_mean, "t3_mean": t3_mean,
        "t5_mean": t5_mean, "t10_mean": t10_mean,
        "t5_med": t5_med, "t5_win_pct": t5_win_rate, "t5_t": t5_t_stat,
    })

    parts = [f"  {sig_name}: n={t5_n}"]
    for label, val in [("T+1", t1_mean), ("T+3", t3_mean), ("T+5", t5_mean), ("T+10", t10_mean)]:
        parts.append(f"{label}={val:.4f}" if val is not None else f"{label}=None")
    print(", ".join(parts))

print("Step 7: Bucket analysis...")
buckets = {"negative": [], "neutral": [], "positive": []}
for d in all_daily:
    sd = {"entry_date": d[0], "daily_agent_signal": d[1],
          "t1_return": d[2], "t3_return": d[3],
          "t5_return": d[4], "t10_return": d[5]}
    sig = sd["daily_agent_signal"]
    if sig is None:
        continue
    if sig <= -0.25:
        buckets["negative"].append(sd)
    elif sig >= 0.25:
        buckets["positive"].append(sd)
    else:
        buckets["neutral"].append(sd)

bucket_results = []
for bucket_name, bucket_data in buckets.items():
    valid_t5 = [r["t5_return"] for r in bucket_data if r["t5_return"] is not None]
    valid_t10 = [r["t10_return"] for r in bucket_data if r["t10_return"] is not None]

    br = {
        "bucket": bucket_name,
        "sample_count": len(valid_t5) if valid_t5 else (len(valid_t10) if valid_t10 else 0),
        "t5_mean": mean(valid_t5) if valid_t5 else None,
        "t10_mean": mean(valid_t10) if valid_t10 else None,
    }
    bucket_results.append(br)

    t5_s = f"{br['t5_mean']:.4f}" if br['t5_mean'] is not None else "N/A"
    t10_s = f"{br['t10_mean']:.4f}" if br['t10_mean'] is not None else "N/A"
    print(f"  {bucket_name}: n={br['sample_count']}, T+5={t5_s}, T+10={t10_s}")

print("Step 8: Saving results...")

study_csv_path = RESULTS_DIR / "daily_event_study.csv"
with open(study_csv_path, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["signal", "sample_count", "T+1", "T+3", "T+5", "T+10",
                      "T+5_med", "T+5_win_pct", "T+5_t"])
    for r in signal_results:
        writer.writerow([
            r["signal"], r["sample_count"],
            f"{r['t1_mean']:.4f}" if r['t1_mean'] is not None else "",
            f"{r['t3_mean']:.4f}" if r['t3_mean'] is not None else "",
            f"{r['t5_mean']:.4f}" if r['t5_mean'] is not None else "",
            f"{r['t10_mean']:.4f}" if r['t10_mean'] is not None else "",
            f"{r['t5_med']:.4f}" if r['t5_med'] is not None else "",
            f"{r['t5_win_pct']:.4f}" if r['t5_win_pct'] is not None else "",
            f"{r['t5_t']:.3f}" if r['t5_t'] is not None else "",
        ])
print(f"  Saved {study_csv_path}")

md_path = RESULTS_DIR / "daily_event_study.md"
with open(md_path, 'w') as f:
    f.write("# Daily Event Study: Aggregated Agent Signals\n\n")
    f.write(f"**Data**: {len(all_daily)} trading days with news, "
            f"{len(daily_data)} unique entry dates\n")
    f.write("**Symbol**: 300750.SZSE\n")
    f.write("**Method**: Daily agent signal = clip(SUM(news_agent_signal) / SQRT(news_count), -1, 1)\n\n")

    f.write("## Signal Test Results\n\n")
    f.write("| Signal | N | T+1 | T+3 | T+5 | T+10 | T+5 Med | T+5 Win% | T+5 t-stat |\n")
    f.write("|--------|---|-----|-----|-----|------|---------|----------|------------|\n")
    for r in signal_results:
        def fmt(v, pct=False):
            if v is None:
                return "N/A"
            if pct:
                return f"{v*100:.2f}%"
            return f"{v:.4f}"
        f.write(f"| {r['signal']} | {r['sample_count']} | {fmt(r['t1_mean'])} | "
                f"{fmt(r['t3_mean'])} | {fmt(r['t5_mean'])} | {fmt(r['t10_mean'])} | "
                f"{fmt(r['t5_med'])} | {fmt(r['t5_win_pct'], pct=True)} | {fmt(r['t5_t'])} |\n")

    f.write("\n## Bucket Analysis\n\n")
    f.write("| Bucket | Sample Count | T+5 Mean | T+10 Mean |\n")
    f.write("|--------|-------------|----------|----------|\n")
    for br in bucket_results:
        t5_s = f"{br['t5_mean']:.4f}" if br['t5_mean'] is not None else "N/A"
        t10_s = f"{br['t10_mean']:.4f}" if br['t10_mean'] is not None else "N/A"
        f.write(f"| {br['bucket']} | {br['sample_count']} | {t5_s} | {t10_s} |\n")

    pos_bucket = bucket_results[2]
    neg_bucket = bucket_results[0]
    best_signal = max(signal_results, key=lambda r: r['t5_mean'] if r['t5_mean'] is not None else float('-inf'))

    f.write("\n## Interpretation\n\n")
    f.write("The daily-frequency event study aggregates per-news agent signals (the product of\n"
            "direction score and confidence, averaged across DeepSeek and Qwen models) into a\n"
            "single daily signal. The aggregation uses a SQRT divisor to penalize clustered news\n"
            "events (e.g., 50 articles about the same H-share placement) and clips the result to [-1, 1].\n\n")

    pos_t5 = pos_bucket.get('t5_mean')
    neg_t5 = neg_bucket.get('t5_mean')

    if pos_t5 is not None and pos_t5 > 0:
        f.write(f"**Positive signal days** (signal >= 0.25) show a mean T+5 return of {pos_t5:.4f},\n"
                "suggesting that aggregated bullish agent consensus has predictive power over the\n"
                "subsequent week.\n\n")
    elif pos_t5 is not None:
        f.write(f"**Positive signal days** (signal >= 0.25) show a mean T+5 return of {pos_t5:.4f},\n"
                "indicating weak or negative predictive power for bullish consensus.\n\n")
    else:
        f.write("**Positive signal days** (signal >= 0.25): insufficient data for T+5 analysis.\n\n")

    if neg_t5 is not None and neg_t5 < 0:
        f.write(f"**Negative signal days** (signal <= -0.25) show a mean T+5 return of {neg_t5:.4f},\n"
                "suggesting that aggregated bearish agent consensus has predictive power over the\n"
                "subsequent week.\n\n")
    elif neg_t5 is not None:
        f.write(f"**Negative signal days** (signal <= -0.25) show a mean T+5 return of {neg_t5:.4f},\n"
                "indicating weak predictive power for bearish consensus.\n\n")
    else:
        f.write("**Negative signal days** (signal <= -0.25): insufficient data for T+5 analysis.\n\n")

    f.write(f"The strongest individual signal is **{best_signal['signal']}** with a T+5 mean return "
            f"of {best_signal['t5_mean']:.4f} (n={best_signal['sample_count']}).\n\n")

    f.write("The SQRT normalization is critical: without it, single-news days and multi-news days\n"
            "would have vastly different signal magnitudes for the same underlying event. The clipping\n"
            "to [-1, 1] prevents extreme outliers from dominating the analysis.\n")

print(f"  Saved {md_path}")

conn.close()
print("\nDone! All steps completed successfully.")
