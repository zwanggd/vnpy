"""Compare DeepSeek vs local Qwen structured JSON extraction.

Usage:
  export DEEPSEEK_API_KEY=sk-...
  python backtests/scripts/bench_llm_compare.py [--samples 50] [--qwen-workers 4]
"""
from __future__ import annotations

import json, os, re, sqlite3, sys, time
from argparse import ArgumentParser
from datetime import timedelta
from openai import OpenAI

QWEN_URL = "http://127.0.0.1:8080/v1"
QWEN_MODEL = "Qwen3.6-35B-A3B-Q4_K_M.gguf"
DEEPSEEK_MODEL = "deepseek-v4-pro"
DEEPSEEK_BASE = "https://api.deepseek.com"
SAMPLES = 50
QWEN_WORKERS = 4

PROMPT = """\
你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。
任务：分析新闻对股票300750.SZSE（宁德时代）的影响。

新闻标题：{title}

输出JSON（严格按此格式，8个字段全英文key）：
{{"event":"中文摘要","relation_type":"direct_company","impact_direction":"positive","impact_strength":0.5,"time_horizon":"short","confidence":0.7,"reason":"中文理由","evidence":"新闻关键句"}}"""


def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def run_deepseek(items: list[tuple[int, str]]) -> list[dict]:
    import concurrent.futures

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    client = OpenAI(api_key=key, base_url=DEEPSEEK_BASE)
    results: list[dict | None] = [None] * len(items)

    def do(i: int, rid: int, title: str) -> None:
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": PROMPT.format(title=title)}],
                max_tokens=256,
                temperature=0,
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            )
            text = clean_json(r.choices[0].message.content or "")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            valid = bool(parsed and all(k in parsed for k in ("event", "impact_direction", "impact_strength", "confidence")))
            results[i] = {
                "idx": i, "title": title[:60], "elapsed": time.time() - t0,
                "pt": r.usage.prompt_tokens, "ct": r.usage.completion_tokens,
                "valid": valid,
                "dir": parsed.get("impact_direction") if parsed else None,
            }
        except Exception as exc:
            results[i] = {"idx": i, "title": title[:60], "error": str(exc)[:150], "elapsed": time.time() - t0, "valid": False}
        n = sum(1 for r in results if r is not None)
        print(f"  DS [{n}/{len(items)}] {results[i].get('elapsed', 0):.1f}s {'OK' if results[i].get('valid') else 'FAIL'}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        list(ex.map(lambda x: do(*x), [(i, rid, title) for i, (rid, title) in enumerate(items)]))
    return [r for r in results if r is not None]  # type: ignore[return-value]


def run_qwen(items: list[tuple[int, str]]) -> list[dict]:
    import concurrent.futures

    client = OpenAI(base_url=QWEN_URL, api_key="x")
    results: list[dict | None] = [None] * len(items)

    def do(i: int, rid: int, title: str) -> None:
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个JSON输出机器。只输出合法JSON。"},
                    {"role": "user", "content": PROMPT.format(title=title)},
                ],
                max_tokens=256, temperature=0,
            )
            text = clean_json(r.choices[0].message.content or "")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            valid = bool(parsed and all(k in parsed for k in ("event", "impact_direction", "impact_strength", "confidence")))
            results[i] = {
                "idx": i, "title": title[:60], "elapsed": time.time() - t0,
                "pt": r.usage.prompt_tokens, "ct": r.usage.completion_tokens,
                "valid": valid,
                "dir": parsed.get("impact_direction") if parsed else None,
                "has_think": "<think>" in (r.choices[0].message.content or ""),
                "raw_preview": text[:200],
            }
        except Exception as exc:
            results[i] = {"idx": i, "title": title[:60], "error": str(exc)[:150], "elapsed": time.time() - t0, "valid": False}
        n = sum(1 for r in results if r is not None)
        print(f"  QW [{n}/{len(items)}] {results[i].get('elapsed', 0):.1f}s {'OK' if results[i].get('valid') else 'FAIL'}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=QWEN_WORKERS) as ex:
        list(ex.map(lambda x: do(*x), [(i, rid, title) for i, (rid, title) in enumerate(items)]))
    return [r for r in results if r is not None]  # type: ignore[return-value]


def print_stats(name: str, results: list[dict]) -> list[dict]:
    valid = [r for r in results if r.get("valid")]
    elapsed = [r.get("elapsed", 0) for r in results if r.get("elapsed", 0) > 0]
    pt = [r.get("pt", 0) for r in valid]
    ct = [r.get("ct", 0) for r in valid]
    think = [r for r in results if r.get("has_think")]
    dirs: dict[str, int] = {}
    for r in valid:
        d = r.get("dir", "?")
        dirs[d] = dirs.get(d, 0) + 1
    print(f"\n{name}: {len(valid)}/{len(results)} OK ({100 * len(valid) / len(results):.0f}%)")
    if elapsed:
        print(f"  Time:  avg={sum(elapsed) / len(elapsed):.1f}s  min={min(elapsed):.1f}s  max={max(elapsed):.1f}s  wall={sum(elapsed):.0f}s")
    if pt:
        print(f"  Tokens: prompt_avg={sum(pt) / len(pt):.0f}  completion_avg={sum(ct) / len(ct):.0f}")
    if think:
        print(f"  Think blocks: {len(think)}/{len(results)}")
    print(f"  Direction: {dirs}")
    return valid


def main() -> None:
    p = ArgumentParser(description="Compare LLM structured JSON extraction")
    p.add_argument("--samples", type=int, default=SAMPLES)
    p.add_argument("--qwen-workers", type=int, default=QWEN_WORKERS)
    p.add_argument("--qwen-only", action="store_true")
    p.add_argument("--ds-only", action="store_true")
    args = p.parse_args()

    db = sqlite3.connect(os.path.expanduser("~/.vntrader/agent_news.db"))
    items = [
        (r[0], r[1])
        for r in db.execute(
            "SELECT id, title FROM agent_raw_news WHERE source='eastmoney' AND title LIKE '%宁德时代%' ORDER BY RANDOM() LIMIT ?",
            (args.samples,),
        ).fetchall()
    ]
    db.close()

    print(f"Benchmark: {len(items)} items\n")

    if not args.qwen_only:
        print("--- DeepSeek v4-pro ---")
        ds = run_deepseek(items)
        print_stats("DeepSeek v4-pro", ds)

    if not args.ds_only:
        print("\n--- Qwen3.6-35B-A3B ---")
        qw = run_qwen(items)
        print_stats("Qwen3.6-35B-A3B", qw)


if __name__ == "__main__":
    main()
