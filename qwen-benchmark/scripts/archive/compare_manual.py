#!/usr/bin/env python3
"""Compare DeepSeek vs Qwen full JSON on 10 disagreement items."""
import json, os, re, sqlite3, time
from pathlib import Path
from openai import OpenAI

DEEPSEEK_KEY = "sk-f070c281b3624c9fb92043006dbc408a"
QWEN_URL = "http://127.0.0.1:8080/v1"
DB = Path.home() / ".vntrader" / "agent_news.db"

PROMPT_A0 = """你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。
任务：分析新闻对股票300750.SZSE（宁德时代）的影响。

新闻标题：{title}

输出JSON（严格按此格式，8个字段全英文key）：
{{"event":"中文摘要","relation_type":"direct_company","impact_direction":"positive","impact_strength":0.5,"time_horizon":"short","confidence":0.7,"reason":"中文理由","evidence":"新闻关键句"}}"""

SYSTEM = "你是一个JSON输出机器。只输出合法JSON。不要输出任何解释、Markdown或额外文字。"

# 7 disagree + 3 agree indices
indices = [0, 1, 2, 4, 6, 7, 10, 3, 5, 8]

db = sqlite3.connect(str(DB))
all_items = [(r[0], r[1]) for r in db.execute(
    "SELECT id, title FROM agent_raw_news WHERE source='eastmoney' AND title LIKE '%宁德时代%' ORDER BY id LIMIT 50"
).fetchall()]
db.close()

items = [(i, all_items[i][0], all_items[i][1]) for i in indices]

ds_client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
qw_client = OpenAI(base_url=QWEN_URL, api_key="x")

comparisons = []

for idx, db_id, title in items:
    print(f"\n{'='*80}")
    print(f"#{idx}: {title[:80]}")
    print(f"{'='*80}")

    # DeepSeek
    t0 = time.perf_counter()
    try:
        r = ds_client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": PROMPT_A0.format(title=title)}],
            max_tokens=256, temperature=0,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        ds_text = r.choices[0].message.content or ""
        ds_text = ds_text.strip()
        if ds_text.startswith("```"):
            ds_text = re.sub(r"^```\w*\n?", "", ds_text)
            ds_text = re.sub(r"\n?```$", "", ds_text)
        try:
            ds_parsed = json.loads(ds_text)
        except json.JSONDecodeError:
            ds_parsed = {"error": "parse_failed", "raw": ds_text[:200]}
        ds_elapsed = time.perf_counter() - t0
        print(f"  DeepSeek ({ds_elapsed:.1f}s): {ds_parsed.get('impact_direction','?')} conf={ds_parsed.get('confidence','?')}")
    except Exception as e:
        ds_parsed = {"error": str(e)[:200]}
        ds_elapsed = time.perf_counter() - t0
        print(f"  DeepSeek: ERROR - {e}")

    # Qwen
    t0 = time.perf_counter()
    try:
        r = qw_client.chat.completions.create(
            model="Qwen3.6-35B-A3B-Q4_K_M.gguf",
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": PROMPT_A0.format(title=title)},
            ],
            max_tokens=256, temperature=0, top_p=1,
        )
        qw_text = r.choices[0].message.content or ""
        qw_text = qw_text.strip()
        if qw_text.startswith("```"):
            qw_text = re.sub(r"^```\w*\n?", "", qw_text)
            qw_text = re.sub(r"\n?```$", "", qw_text)
        try:
            qw_parsed = json.loads(qw_text)
        except json.JSONDecodeError:
            qw_parsed = {"error": "parse_failed", "raw": qw_text[:200]}
        qw_elapsed = time.perf_counter() - t0
        print(f"  Qwen     ({qw_elapsed:.1f}s): {qw_parsed.get('impact_direction','?')} conf={qw_parsed.get('confidence','?')}")
    except Exception as e:
        qw_parsed = {"error": str(e)[:200]}
        qw_elapsed = time.perf_counter() - t0
        print(f"  Qwen: ERROR - {e}")

    comparisons.append({
        "idx": idx,
        "title": title,
        "deepseek": ds_parsed,
        "deepseek_elapsed": round(ds_elapsed, 1),
        "qwen": qw_parsed,
        "qwen_elapsed": round(qw_elapsed, 1),
    })

# Save
out_path = Path(__file__).parent.parent / "results" / "manual_comparison.json"
with open(out_path, "w") as f:
    json.dump(comparisons, f, ensure_ascii=False, indent=2)

# Print summary table
print(f"\n\n{'='*120}")
print("MANUAL COMPARISON SUMMARY")
print(f"{'='*120}")
print(f"{'#':<3} {'Title':<45} {'DS Dir':<10} {'DS Conf':>6} {'QW Dir':<10} {'QW Conf':>6} {'Match':>6} {'DS(s)':>6} {'QW(s)':>6}")
print("-" * 120)

for c in comparisons:
    ds_dir = c["deepseek"].get("impact_direction", "?")
    qw_dir = c["qwen"].get("impact_direction", "?")
    ds_conf = c["deepseek"].get("confidence", "?")
    qw_conf = c["qwen"].get("confidence", "?")
    match = "✓" if ds_dir == qw_dir else "✗"
    print(f"{c['idx']:<3} {c['title'][:43]:<45} {ds_dir:<10} {str(ds_conf):>6} {qw_dir:<10} {str(qw_conf):>6} {match:>6} {c['deepseek_elapsed']:>5.1f}s {c['qwen_elapsed']:>5.1f}s")

print(f"\nDetailed JSON → {out_path}")
