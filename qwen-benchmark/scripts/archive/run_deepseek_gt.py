#!/usr/bin/env python3
"""DeepSeek v4-pro ground truth labels for accuracy comparison."""
import json, os, re, sqlite3, time
from pathlib import Path
from openai import OpenAI

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com"
DB = Path.home() / ".vntrader" / "agent_news.db"
RESULTS = Path(__file__).parent.parent / "results"

PROMPT_A0 = """你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。
任务：分析新闻对股票300750.SZSE（宁德时代）的影响。

新闻标题：{title}

输出JSON（严格按此格式，8个字段全英文key）：
{{"event":"中文摘要","relation_type":"direct_company","impact_direction":"positive","impact_strength":0.5,"time_horizon":"short","confidence":0.7,"reason":"中文理由","evidence":"新闻关键句"}}"""

if not DEEPSEEK_KEY:
    print("ERROR: DEEPSEEK_API_KEY not set")
    exit(1)

client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE)
db = sqlite3.connect(str(DB))

for n_items, label in [(20, "exploratory"), (50, "validation")]:
    items = [(r[0], r[1]) for r in db.execute(
        "SELECT id, title FROM agent_raw_news WHERE source='eastmoney' AND title LIKE '%宁德时代%' ORDER BY id LIMIT ?",
        (n_items,),
    ).fetchall()]

    out_dir = RESULTS / f"deepseek_{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "results.jsonl"

    # Skip if already done
    if out_file.exists():
        with open(out_file) as f:
            existing = sum(1 for _ in f)
        if existing >= n_items:
            print(f"DeepSeek {label} ({n_items} items): already done ({existing} records), skipping")
            continue
        print(f"DeepSeek {label}: {existing}/{n_items} done, continuing...")

    results = []
    print(f"\nDeepSeek {label} ({n_items} items):")
    for i, (db_id, title) in enumerate(items):
        t0 = time.perf_counter()
        try:
            r = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[{"role": "user", "content": PROMPT_A0.format(title=title)}],
                max_tokens=256, temperature=0,
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            )
            text = r.choices[0].message.content or ""
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```\w*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            valid = bool(parsed and all(k in parsed for k in ("event", "impact_direction", "impact_strength", "confidence")))
            direction = parsed.get("impact_direction") if parsed else None
            elapsed = time.perf_counter() - t0
            record = {
                "idx": i, "db_id": db_id, "title": title[:80],
                "elapsed_s": round(elapsed, 2),
                "direction": direction,
                "confidence": parsed.get("confidence") if parsed else None,
                "valid": valid,
                "prompt_tokens": r.usage.prompt_tokens,
                "completion_tokens": r.usage.completion_tokens,
            }
            results.append(record)
            print(f"  [{i+1:2d}/{n_items}] {elapsed:.1f}s {direction or '?'} {'OK' if valid else 'FAIL'}", flush=True)
        except Exception as e:
            record = {"idx": i, "db_id": db_id, "title": title[:80], "elapsed_s": time.perf_counter()-t0, "error": str(e)[:200], "valid": False}
            results.append(record)
            print(f"  [{i+1:2d}/{n_items}] FAIL: {str(e)[:80]}", flush=True)

    with open(out_file, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Saved {len(results)} records -> {out_file}")

db.close()
print("\nDeepSeek ground truth complete.")
