#!/usr/bin/env python3
"""Qwen3.6-35B-A3B Fast-Funnel Benchmark.

Phase 1: 20 items × 1 run per config → pick best config
Phase 2: 50 items × 2 runs best config + 50 items × 1 run baseline

Output: JSONL per config, summary CSV per group, master summary CSV.
"""
from __future__ import annotations

import csv
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import urllib.request
from openai import OpenAI

# ── Paths ────────────────────────────────────────────────────
MODEL_PATH = Path(
    "/Users/kai/.lmstudio/models/lmstudio-community/"
    "Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf"
)
LLAMA_SERVER_BIN = "/opt/homebrew/bin/llama-server"
DB_PATH = Path.home() / ".vntrader" / "agent_news.db"
BASE_URL = "http://127.0.0.1:8080/v1"
MODEL_NAME = "Qwen3.6-35B-A3B-Q4_K_M.gguf"
RESULTS_DIR = Path(__file__).parent.parent / "results"

SERVER_START_TIMEOUT = 60


# ── Prompt Variants ───────────────────────────────────────────
SYSTEM_PROMPT = "你是一个JSON输出机器。只输出合法JSON。不要输出任何解释、Markdown或额外文字。"

PROMPTS = {
    "A0": {
        "user": """你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。
任务：分析新闻对股票300750.SZSE（宁德时代）的影响。

新闻标题：{title}

输出JSON（严格按此格式，8个字段全英文key）：
{{"event":"中文摘要","relation_type":"direct_company","impact_direction":"positive","impact_strength":0.5,"time_horizon":"short","confidence":0.7,"reason":"中文理由","evidence":"新闻关键句"}}""",
        "max_tokens": 160,
        "verify_fields": ["event", "impact_direction", "impact_strength", "confidence"],
    },
    "A1": {
        "user": """你是A股新闻影响评估助手。分析新闻对宁德时代(300750.SZSE)的影响。只输出JSON。

新闻标题：{title}

输出JSON（direction/confidence/reason）：
{{"impact_direction":"positive/negative/neutral","confidence":0.7,"reason":"中文理由"}}""",
        "max_tokens": 96,
        "verify_fields": ["impact_direction", "confidence", "reason"],
    },
    "A2": {
        "user": """你是A股新闻影响评估助手。分析新闻对宁德时代(300750.SZSE)的影响。只输出JSON。

新闻标题：{title}

输出JSON（仅方向+置信度）：
{{"impact_direction":"positive/negative/neutral","confidence":0.7}}""",
        "max_tokens": 48,
        "verify_fields": ["impact_direction", "confidence"],
    },
    "A3": {
        "user": """你是A股新闻影响评估助手。分析新闻对宁德时代(300750.SZSE)的影响。只输出JSON。

新闻标题：{title}

输出JSON（direction/confidence/reason，reason不超过20个中文字符）：
{{"impact_direction":"positive/negative/neutral","confidence":0.7,"reason":"不超过20个中文字符的理由"}}""",
        "max_tokens": 80,
        "verify_fields": ["impact_direction", "confidence", "reason"],
    },
}

# ── Server Config ────────────────────────────────────────────
@dataclass
class ServerConfig:
    config_id: str
    ctx: int = 4096
    ngl: int = 99
    fa: bool = True
    batch: int = 2048
    ubatch: int = 2048
    cache_k: str = "q8_0"
    cache_v: str = "q8_0"
    parallel: int = 4
    cache_reuse: int = 256
    ctx_checkpoints: int = 32
    cache_ram: int = 8192

    def to_args(self) -> list[str]:
        return [
            "-m", str(MODEL_PATH),
            "-c", str(self.ctx),
            "-ngl", str(self.ngl),
            "-fa", "on" if self.fa else "off",
            "-b", str(self.batch),
            "-ub", str(self.ubatch),
            "--cache-type-k", self.cache_k,
            "--cache-type-v", self.cache_v,
            "--parallel", str(self.parallel),
            "--cache-reuse", str(self.cache_reuse),
            "--ctx-checkpoints", str(self.ctx_checkpoints),
            "--cache-ram", str(self.cache_ram),
            "--host", "127.0.0.1",
            "--port", "8080",
            "--reasoning", "off",
        ]


# ── Server Lifecycle ──────────────────────────────────────────
def server_alive() -> bool:
    try:
        req = urllib.request.Request(f"{BASE_URL}/models", method="GET")
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def start_server(config: ServerConfig) -> subprocess.Popen:
    stop_server()
    args = [LLAMA_SERVER_BIN] + config.to_args()
    print(f"  SERVER: {' '.join(args[:6])} ...")
    log_f = open(RESULTS_DIR / "server.log", "a")
    log_f.write(f"\n=== {config.config_id} @ {time.strftime('%H:%M:%S')} ===\n")
    log_f.write(" ".join(args) + "\n")
    log_f.flush()
    proc = subprocess.Popen(args, stdout=log_f, stderr=subprocess.STDOUT)
    deadline = time.time() + SERVER_START_TIMEOUT
    while time.time() < deadline:
        if server_alive():
            print(f"  SERVER: {config.config_id} ready (pid={proc.pid})")
            return proc
        time.sleep(2)
    proc.kill()
    raise RuntimeError(f"Server {config.config_id} startup timeout")


def stop_server():
    try:
        output = subprocess.check_output(
            ["lsof", "-ti", ":8080"], stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        if output:
            for pid in output.split("\n"):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except Exception:
                    pass
            time.sleep(2)
            output2 = subprocess.check_output(
                ["lsof", "-ti", ":8080"], stderr=subprocess.DEVNULL, timeout=3
            ).decode().strip()
            if output2:
                for pid in output2.split("\n"):
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except Exception:
                        pass
    except Exception:
        pass
    time.sleep(1)


# ── Data Loading ──────────────────────────────────────────────
def load_items(n: int) -> list[tuple[int, str]]:
    db = sqlite3.connect(str(DB_PATH))
    items = [
        (r[0], r[1])
        for r in db.execute(
            "SELECT id, title FROM agent_raw_news "
            "WHERE source='eastmoney' AND title LIKE '%宁德时代%' "
            "ORDER BY id LIMIT ?",
            (n,),
        ).fetchall()
    ]
    db.close()
    return items


# ── Streaming Request ────────────────────────────────────────
def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def request_one(
    client: OpenAI, idx: int, db_id: int, title: str,
    prompt_id: str, worker_id: int, verbose: bool = True,
) -> dict:
    prompt_cfg = PROMPTS[prompt_id]
    t0 = time.perf_counter()
    ttft_ms = None
    full_text = ""
    prompt_tokens = 0
    completion_tokens = 0

    try:
        stream = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_cfg["user"].format(title=title)},
            ],
            max_tokens=prompt_cfg["max_tokens"],
            temperature=0, top_p=1,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if ttft_ms is None:
                ttft_ms = (time.perf_counter() - t0) * 1000
            if chunk.choices and chunk.choices[0].delta.content:
                full_text += chunk.choices[0].delta.content
            if chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
        total_latency_ms = (time.perf_counter() - t0) * 1000
        if ttft_ms is None:
            ttft_ms = total_latency_ms

        cleaned = clean_json(full_text)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            parsed = None

        verify_fields = prompt_cfg["verify_fields"]
        valid = bool(parsed and all(k in parsed for k in verify_fields))
        label = parsed.get("impact_direction") if parsed else None
        confidence = parsed.get("confidence") if parsed else None

        return {
            "idx": idx, "db_id": db_id, "title": title[:80],
            "prompt_id": prompt_id, "worker_id": worker_id,
            "input_tokens": prompt_tokens, "output_tokens": completion_tokens,
            "total_latency_ms": round(total_latency_ms, 1),
            "ttft_ms": round(ttft_ms, 1) if ttft_ms else None,
            "direction": label, "confidence": confidence,
            "json_parse_success": valid, "error": None,
        }
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "idx": idx, "db_id": db_id, "title": title[:80],
            "prompt_id": prompt_id, "worker_id": worker_id,
            "input_tokens": 0, "output_tokens": 0,
            "total_latency_ms": round(elapsed, 1),
            "ttft_ms": None,
            "direction": None, "confidence": None,
            "json_parse_success": False, "error": str(exc)[:200],
        }


# ── Run Batch ─────────────────────────────────────────────────
def run_batch(
    client: OpenAI, items: list[tuple[int, str]],
    prompt_id: str, workers: int, config_id: str,
    label_prefix: str = "",
) -> list[dict]:
    results: list = [None] * len(items)
    done = [0]
    tag = f"{label_prefix} {config_id}" if label_prefix else config_id

    def do(i: int, db_id: int, title: str, w: int):
        r = request_one(client, i, db_id, title, prompt_id, w)
        results[i] = r
        done[0] += 1
        ok = "OK" if r["json_parse_success"] else "FAIL"
        print(f"  [{tag}] [{done[0]:2d}/{len(items)}] "
              f"w{w} {r['total_latency_ms']:.0f}ms "
              f"in={r['input_tokens']} out={r['output_tokens']} "
              f"ttft={r['ttft_ms']:.0f}ms {ok}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = []
        for i, (db_id, title) in enumerate(items):
            futures.append(ex.submit(do, i, db_id, title, i % workers))
        for _ in as_completed(futures):
            pass
    return [r for r in results if r is not None]


# ── Summarize ─────────────────────────────────────────────────
def summarize(results: list[dict], config_id: str) -> dict:
    valid = [r for r in results if r["json_parse_success"]]
    failed = [r for r in results if not r["json_parse_success"]]
    elapsed = [r["total_latency_ms"] for r in results if r["total_latency_ms"] > 0]
    ttft_vals = [r["ttft_ms"] for r in results if r.get("ttft_ms")]
    out_tokens = [r["output_tokens"] for r in valid]
    labels: dict[str, int] = {}
    for r in valid:
        d = r.get("direction", "?")
        labels[d] = labels.get(d, 0) + 1

    sorted_elapsed = sorted(elapsed)
    n = len(sorted_elapsed)
    wall_s = sum(elapsed) / 1000 if elapsed else 0
    total = len(results)

    return {
        "config_id": config_id,
        "total": total,
        "success": len(valid),
        "success_rate_pct": round(100 * len(valid) / total, 1) if total else 0,
        "avg_latency_ms": round(sum(elapsed) / len(elapsed), 0) if elapsed else 0,
        "p50_latency_ms": round(sorted_elapsed[n // 2], 0) if n else 0,
        "p90_latency_ms": round(sorted_elapsed[int(n * 0.9)], 0) if n else 0,
        "avg_ttft_ms": round(sum(ttft_vals) / len(ttft_vals), 0) if ttft_vals else 0,
        "avg_output_tokens": round(sum(out_tokens) / len(out_tokens), 0) if out_tokens else 0,
        "throughput_req_s": round(total / wall_s, 2) if wall_s > 0 else 0,
        "labels": json.dumps(labels, ensure_ascii=False),
        "wall_time_s": round(wall_s, 1),
    }


def print_summary(s: dict):
    print(f"  {'─'*55}")
    print(f"  {s['config_id']}: {s['success']}/{s['total']} OK ({s['success_rate_pct']}%)")
    print(f"  Latency: avg={s['avg_latency_ms']:.0f}ms p50={s['p50_latency_ms']:.0f}ms "
          f"p90={s['p90_latency_ms']:.0f}ms  TTFT={s['avg_ttft_ms']:.0f}ms")
    print(f"  Output tokens: {s['avg_output_tokens']:.0f}  "
          f"Throughput: {s['throughput_req_s']:.2f} req/s")
    print(f"  Labels: {s['labels']}")


# ── Save ──────────────────────────────────────────────────────
def save_jsonl(results: list[dict], config_id: str):
    out_dir = RESULTS_DIR / config_id
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / "results.jsonl"
    with open(fname, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def save_summary_csv(summaries: list[dict], filename: str):
    if not summaries:
        return
    filepath = RESULTS_DIR / filename
    all_keys = list(dict.fromkeys(k for s in summaries for k in s.keys()))
    with open(filepath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(summaries)
    print(f"  Summary → {filepath}")


# ══════════════════════════════════════════════════════════════
# PHASE 1: EXPLORATORY (20 items × 1 run)
# ══════════════════════════════════════════════════════════════

def run_group1_prompts(items_20: list, client: OpenAI) -> list[dict]:
    """A0-A3, workers=4, baseline server, 20 items × 1 run."""
    workers = 4
    summaries = []
    for pid in ["A0", "A1", "A2", "A3"]:
        cid = f"g1_{pid}"
        print(f"\n{'─'*60}\nGroup 1 - {pid} (max_tokens={PROMPTS[pid]['max_tokens']})")
        results = run_batch(client, items_20, pid, workers, cid, "G1")
        save_jsonl(results, cid)
        s = summarize(results, cid)
        s["prompt_id"] = pid
        s["max_tokens"] = PROMPTS[pid]["max_tokens"]
        s["workers"] = workers
        print_summary(s)
        summaries.append(s)
    return summaries


def run_group2_workers(items_20: list, client: OpenAI) -> list[dict]:
    """Workers 1,4,6, baseline server, A0 prompt, 20 items × 1 run."""
    pid = "A0"
    summaries = []
    for w in [1, 4, 6]:
        cid = f"g2_w{w}"
        print(f"\n{'─'*60}\nGroup 2 - workers={w}")
        results = run_batch(client, items_20, pid, w, cid, "G2")
        save_jsonl(results, cid)
        s = summarize(results, cid)
        s["workers"] = w
        s["prompt_id"] = pid
        print_summary(s)
        summaries.append(s)
    return summaries


def run_group3_parallel(items_20: list) -> list[dict]:
    """Server parallel=1,4,6 with matching workers, 20 items × 1 run."""
    pid = "A0"
    summaries = []
    for p in [1, 4, 6]:
        cid = f"g3_p{p}"
        config = ServerConfig(config_id=cid, parallel=p)
        print(f"\n{'#'*60}\nGroup 3 - server parallel={p}, workers={p}")
        proc = start_server(config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items_20, pid, p, cid, "G3")
            save_jsonl(results, cid)
            s = summarize(results, cid)
            s["server_parallel"] = p
            s["workers"] = p
            s["prompt_id"] = pid
            print_summary(s)
            summaries.append(s)
        finally:
            stop_server()
            time.sleep(3)
    return summaries


def run_group4_ctx(items_20: list) -> list[dict]:
    """Context 4096, 8192, parallel=4 workers=4, 20 items × 1 run."""
    pid = "A0"
    workers = 4
    summaries = []
    for c in [4096, 8192]:
        cid = f"g4_c{c}"
        config = ServerConfig(config_id=cid, ctx=c)
        print(f"\n{'#'*60}\nGroup 4 - ctx={c}")
        proc = start_server(config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items_20, pid, workers, cid, "G4")
            save_jsonl(results, cid)
            s = summarize(results, cid)
            s["ctx"] = c
            s["workers"] = workers
            s["server_parallel"] = 4
            print_summary(s)
            summaries.append(s)
        finally:
            stop_server()
            time.sleep(3)
    return summaries


def run_group5_batch(items_20: list) -> list[dict]:
    """Batch/ubatch (512,512), (1024,1024), (2048,2048), 20 items × 1 run."""
    pid = "A0"
    workers = 4
    combos = [(512, 512), (1024, 1024), (2048, 2048)]
    summaries = []
    for b, ub in combos:
        cid = f"g5_b{b}_ub{ub}"
        config = ServerConfig(config_id=cid, batch=b, ubatch=ub)
        print(f"\n{'#'*60}\nGroup 5 - batch={b} ubatch={ub}")
        proc = start_server(config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items_20, pid, workers, cid, "G5")
            save_jsonl(results, cid)
            s = summarize(results, cid)
            s["batch"] = b
            s["ubatch"] = ub
            s["workers"] = workers
            print_summary(s)
            summaries.append(s)
        finally:
            stop_server()
            time.sleep(3)
    return summaries


# ══════════════════════════════════════════════════════════════
# PHASE 2: VALIDATION (50 items, best config × 2 + baseline × 1)
# ══════════════════════════════════════════════════════════════

def run_validation(items_50: list, best_config: ServerConfig, best_prompt: str,
                   best_workers: int) -> list[dict]:
    """Run baseline (50 × 1) and best config (50 × 2)."""
    summaries = []
    BASELINE = ServerConfig("val_baseline")

    # Baseline: 1 run
    print(f"\n{'#'*60}\nVALIDATION - Baseline (50 items × 1 run)")
    proc = start_server(BASELINE)
    try:
        client = OpenAI(base_url=BASE_URL, api_key="x")
        results = run_batch(client, items_50, best_prompt or "A0", best_workers or 4,
                            "val_baseline", "VAL")
        save_jsonl(results, "val_baseline")
        s = summarize(results, "val_baseline")
        s["phase"] = "validation_baseline"
        print_summary(s)
        summaries.append(s)
    finally:
        stop_server()
        time.sleep(3)

    # Best config: 2 runs
    for rnd in [1, 2]:
        cid = f"val_best_r{rnd}"
        best_config.config_id = cid
        print(f"\n{'#'*60}\nVALIDATION - Best config (50 items, run {rnd}/2)")
        proc = start_server(best_config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items_50, best_prompt or "A0",
                                best_workers or 4, cid, "VAL")
            save_jsonl(results, cid)
            s = summarize(results, cid)
            s["phase"] = "validation_best"
            s["round"] = rnd
            print_summary(s)
            summaries.append(s)
        finally:
            stop_server()
            time.sleep(3)

    return summaries


# ── Main ──────────────────────────────────────────────────────
def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    items_20 = load_items(20)
    items_50 = load_items(50)
    print(f"Loaded: {len(items_20)} exploratory items, {len(items_50)} validation items\n")

    all_summaries: list[dict] = []
    start_ts = time.time()

    # ── Group 1: Prompts (no restart) ──
    print(f"{'#'*60}\n### GROUP 1: Prompt / max_tokens ###\n{'#'*60}")
    config = ServerConfig("baseline_g1")
    proc = start_server(config)
    try:
        client = OpenAI(base_url=BASE_URL, api_key="x")
        all_summaries.extend(run_group1_prompts(items_20, client))
    finally:
        stop_server()
        time.sleep(2)
    save_summary_csv([s for s in all_summaries if s["config_id"].startswith("g1_")],
                     "summary_group1.csv")

    # ── Group 2: Workers (no restart) ──
    print(f"\n{'#'*60}\n### GROUP 2: Client Workers ###\n{'#'*60}")
    config = ServerConfig("baseline_g2")
    proc = start_server(config)
    try:
        client = OpenAI(base_url=BASE_URL, api_key="x")
        all_summaries.extend(run_group2_workers(items_20, client))
    finally:
        stop_server()
        time.sleep(2)
    save_summary_csv([s for s in all_summaries if s["config_id"].startswith("g2_")],
                     "summary_group2.csv")

    # ── Group 3: Server Parallel ──
    print(f"\n{'#'*60}\n### GROUP 3: Server Parallel ###\n{'#'*60}")
    all_summaries.extend(run_group3_parallel(items_20))
    save_summary_csv([s for s in all_summaries if s["config_id"].startswith("g3_")],
                     "summary_group3.csv")

    # ── Group 4: Context Size ──
    print(f"\n{'#'*60}\n### GROUP 4: Context Size ###\n{'#'*60}")
    all_summaries.extend(run_group4_ctx(items_20))
    save_summary_csv([s for s in all_summaries if s["config_id"].startswith("g4_")],
                     "summary_group4.csv")

    # ── Group 5: Batch/Ubatch ──
    print(f"\n{'#'*60}\n### GROUP 5: Batch / Ubatch ###\n{'#'*60}")
    all_summaries.extend(run_group5_batch(items_20))
    save_summary_csv([s for s in all_summaries if s["config_id"].startswith("g5_")],
                     "summary_group5.csv")

    # ── Phase 1 Summary ──
    elapsed_phase1 = time.time() - start_ts
    print(f"\n{'='*60}")
    print(f"PHASE 1 COMPLETE in {elapsed_phase1:.0f}s ({elapsed_phase1/60:.1f}m)")
    print(f"{'='*60}")

    # ── Phase 1 Leaderboard ──
    print(f"\n{'Config':<30} {'OK%':>6} {'Avg':>8} {'P50':>8} {'P90':>8} {'TTFT':>8} {'OutTk':>6} {'Req/s':>7} {'Labels'}")
    print("-" * 110)
    for s in all_summaries:
        if s["config_id"].startswith("val_"):
            continue
        print(
            f"{s['config_id']:<30} "
            f"{s['success_rate_pct']:>5.0f}% "
            f"{s['avg_latency_ms']:>8.0f} "
            f"{s['p50_latency_ms']:>8.0f} "
            f"{s['p90_latency_ms']:>8.0f} "
            f"{s['avg_ttft_ms']:>8.0f} "
            f"{s['avg_output_tokens']:>6.0f} "
            f"{s['throughput_req_s']:>7.2f} "
            f"{s['labels']}"
        )

    # Save phase 1 master
    save_summary_csv(all_summaries, "summary_phase1_all.csv")

    # ══════════════════════════════════════════════════════════
    # PHASE 2: Validation — pick best config
    # ══════════════════════════════════════════════════════════
    # Pick best by: success_rate first, then throughput (higher is better)
    exploratory = [s for s in all_summaries if not s["config_id"].startswith("val_")]
    exploratory.sort(key=lambda x: (-x["success_rate_pct"], -x["throughput_req_s"]))
    best = exploratory[0]

    print(f"\n{'='*60}")
    print(f"BEST EXPLORATORY CONFIG: {best['config_id']}")
    print(f"  Success: {best['success_rate_pct']}%  Throughput: {best['throughput_req_s']} req/s")
    print(f"  Avg latency: {best['avg_latency_ms']}ms  TTFT: {best['avg_ttft_ms']}ms")
    print(f"{'='*60}")

    # Reconstruct best config from summary
    best_prompt = best.get("prompt_id", "A0")
    best_workers = best.get("workers", 4)
    best_sc = ServerConfig(
        config_id="val_best",
        parallel=best.get("server_parallel", 4),
        ctx=best.get("ctx", 4096),
        batch=best.get("batch", 2048),
        ubatch=best.get("ubatch", 2048),
    )

    val_summaries = run_validation(items_50, best_sc, best_prompt, best_workers)
    all_summaries.extend(val_summaries)
    save_summary_csv(val_summaries, "summary_validation.csv")

    # ── Final Report ──
    elapsed_total = time.time() - start_ts
    print(f"\n{'#'*60}")
    print(f"### ALL DONE in {elapsed_total:.0f}s ({elapsed_total/60:.1f}m) ###")
    print(f"{'#'*60}")

    print(f"\n{'Phase':<10} {'Config':<30} {'OK%':>6} {'Avg ms':>8} {'P50':>8} {'Req/s':>7}")
    print("-" * 80)
    for s in all_summaries:
        phase = s.get("phase", "exploratory")
        print(
            f"{phase:<10} {s['config_id']:<30} "
            f"{s['success_rate_pct']:>5.0f}% "
            f"{s['avg_latency_ms']:>8.0f} "
            f"{s['p50_latency_ms']:>8.0f} "
            f"{s['throughput_req_s']:>7.2f}"
        )

    save_summary_csv(all_summaries, "summary_master.csv")
    print(f"\nAll results → {RESULTS_DIR}")


if __name__ == "__main__":
    main()
