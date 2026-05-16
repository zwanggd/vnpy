#!/usr/bin/env python3
"""Run A0 baseline on 50 items for label quality comparison with A2."""
import json, re, sqlite3, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

BASE_URL = "http://127.0.0.1:8080/v1"
MODEL = "Qwen3.6-35B-A3B-Q4_K_M.gguf"
DB = Path.home() / ".vntrader" / "agent_news.db"
RESULTS = Path(__file__).parent.parent / "results"

PROMPT_A0 = """你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。
任务：分析新闻对股票300750.SZSE（宁德时代）的影响。

新闻标题：{title}

输出JSON（严格按此格式，8个字段全英文key）：
{"event":"中文摘要","relation_type":"direct_company","impact_direction":"positive","impact_strength":0.5,"time_horizon":"short","confidence":0.7,"reason":"中文理由","evidence":"新闻关键句"}"""

SYSTEM = "你是一个JSON输出机器。只输出合法JSON。不要输出任何解释、Markdown或额外文字。"

db = sqlite3.connect(str(DB))
items = [(r[0], r[1]) for r in db.execute(
    "SELECT id, title FROM agent_raw_news WHERE source='eastmoney' AND title LIKE '%宁德时代%' ORDER BY id LIMIT 50"
).fetchall()]
db.close()

client = OpenAI(base_url=BASE_URL, api_key="x")
results = [None] * 50
done = [0]

def do(i, db_id, title):
    t0 = time.perf_counter()
    ttft = None
    text = ""
    pt = ct = 0
    try:
        stream = client.chat.completions.create(
            model=MODEL,
            messages=[{"role":"system","content":SYSTEM},
                      {"role":"user","content":PROMPT_A0.format(title=title)}],
            max_tokens=160, temperature=0, top_p=1, stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            if chunk.choices and chunk.choices[0].delta.content:
                text += chunk.choices[0].delta.content
            if chunk.usage:
                pt = chunk.usage.prompt_tokens
                ct = chunk.usage.completion_tokens
        lat = (time.perf_counter() - t0) * 1000
        if ttft is None:
            ttft = lat
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        parsed = json.loads(text) if text else None
        valid = bool(parsed and all(k in parsed for k in ["event","impact_direction","impact_strength","confidence"]))
        results[i] = {
            "idx": i, "total_latency_ms": round(lat,1),
            "ttft_ms": round(ttft,1) if ttft else None,
            "input_tokens": pt, "output_tokens": ct,
            "json_parse_success": valid,
            "direction": parsed.get("impact_direction") if parsed else None,
        }
        done[0] += 1
        print(f"  [A0_50] [{done[0]:2d}/50] {lat:.0f}ms out={ct} {'OK' if valid else 'FAIL'}", flush=True)
    except Exception as e:
        results[i] = {"idx": i, "total_latency_ms": (time.perf_counter()-t0)*1000,
                       "json_parse_success": False, "error": str(e)[:200]}
        done[0] += 1

with ThreadPoolExecutor(max_workers=4) as ex:
    futures = [ex.submit(do, i, db_id, title) for i, (db_id, title) in enumerate(items)]
    for _ in as_completed(futures):
        pass

valid = [r for r in results if r.get("json_parse_success")]
elapsed = [r["total_latency_ms"] for r in results if r["total_latency_ms"] > 0]
out_tokens = [r["output_tokens"] for r in valid]
labels = {}
for r in valid:
    d = r.get("direction", "?")
    labels[d] = labels.get(d, 0) + 1

print(f"\nA0 50-item baseline:")
print(f"  Success: {len(valid)}/{len(results)} ({100*len(valid)/len(results):.0f}%)")
print(f"  Latency: avg={sum(elapsed)/len(elapsed):.0f}ms p50={sorted(elapsed)[len(elapsed)//2]:.0f}ms")
print(f"  Output tokens: avg={sum(out_tokens)/len(out_tokens):.0f}")
print(f"  Labels: {labels}")

out_dir = RESULTS / "val_baseline_A0"
out_dir.mkdir(parents=True, exist_ok=True)
with open(out_dir / "results.jsonl", "w") as f:
    for r in results:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"  Saved -> {out_dir}")
