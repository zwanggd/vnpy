#!/usr/bin/env python3
"""Full benchmark with NEW prompt — fast funnel: 20-item exploratory + 50-item validation."""
from __future__ import annotations

import csv, json, math, os, re, signal, sqlite3, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from openai import OpenAI

# ── Constants ───────────────────────────────────────────────
MODEL_PATH = Path("/Users/kai/.lmstudio/models/lmstudio-community/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf")
LLAMA_SERVER = "/opt/homebrew/bin/llama-server"
DB_PATH = Path.home() / ".vntrader" / "agent_news.db"
BASE_URL = "http://127.0.0.1:8080/v1"
MODEL_NAME = "Qwen3.6-35B-A3B-Q4_K_M.gguf"
RESULTS_DIR = Path(__file__).parent.parent / "results_v2"
DEEPSEEK_KEY = "sk-f070c281b3624c9fb92043006dbc408a"
EXPLORATORY_N = 20
VALIDATION_N = 50

NEW_PROMPT = """你是一个股票新闻事件分类器。你的任务是判断新闻在发布当下对公司股价的短期方向影响。

只基于新闻文本本身，不考虑之后实际股价走势。

优先判断新闻是否通过以下路径影响股价：
- revenue_or_demand: 收入、订单、销量、客户需求、市场份额
- profit_or_margin: 利润、毛利率、成本、费用
- financing_or_liquidity: 融资、现金流、债务、资本补充
- share_supply: 配股、增发、减持、股本稀释、股份转让
- regulatory_or_legal: 监管、诉讼、处罚、批准、政策
- product_or_partnership: 新产品、战略合作、技术突破
- governance_or_control: 控制权、管理层、股东结构
- routine_disclosure: 月报表、翌日披露、普通董事会决议等常规公告

判断规则：
1. 如果新闻明确改善收入、利润、订单、需求、监管批准或融资能力，倾向 positive。
2. 如果新闻明确带来诉讼、监管、亏损、需求下滑、债务压力、减持压力或稀释压力，倾向 negative。
3. 常规披露默认 neutral。
4. 融资/配售/增发是混合事件：资本补充为正，股本稀释为负；如果没有明显一方占优，判 neutral。
5. 股东转让/减持不是自动 negative；只有控股股东、大比例、折价、连续减持、控制权不确定时才明显 negative。
6. 如果影响路径间冲突，判 neutral 或给较低 confidence。
7. 如果新闻缺少明确业务、财务、监管或股本供给影响，判 neutral。

新闻标题：{title}

请只输出合法JSON。"""

OUTPUT_FORMAT = """{{
"event_type": "operating|financing|share_supply|regulatory|legal|product|partnership|governance|routine|other",
"impact_channel": "revenue_or_demand|profit_or_margin|financing_or_liquidity|share_supply|regulatory_or_legal|product_or_partnership|governance_or_control|routine_disclosure|other",
"direction": "positive|neutral|negative",
"score": 0.0,
"confidence": 0.0
}}"""

SYSTEM_PROMPT = "你是一个JSON输出机器。只输出合法JSON。不要输出任何解释、Markdown或额外文字。"

VERIFY_FIELDS = ["event_type", "impact_channel", "direction", "score", "confidence"]


@dataclass
class ServerConfig:
    config_id: str
    ctx: int = 4096; ngl: int = 99; fa: bool = True
    batch: int = 2048; ubatch: int = 2048
    cache_k: str = "q8_0"; cache_v: str = "q8_0"
    parallel: int = 4; cache_reuse: int = 256
    ctx_checkpoints: int = 32; cache_ram: int = 8192

    def to_args(self):
        return ["-m", str(MODEL_PATH), "-c", str(self.ctx), "-ngl", str(self.ngl),
                "-fa", "on" if self.fa else "off", "-b", str(self.batch), "-ub", str(self.ubatch),
                "--cache-type-k", self.cache_k, "--cache-type-v", self.cache_v,
                "--parallel", str(self.parallel), "--cache-reuse", str(self.cache_reuse),
                "--ctx-checkpoints", str(self.ctx_checkpoints), "--cache-ram", str(self.cache_ram),
                "--host", "127.0.0.1", "--port", "8080", "--reasoning", "off"]


def server_alive():
    try: urllib.request.urlopen(urllib.request.Request(f"{BASE_URL}/models", method="GET"), timeout=3); return True
    except: return False


def start_server(cfg: ServerConfig):
    stop_server()
    args = [LLAMA_SERVER] + cfg.to_args()
    logf = open(RESULTS_DIR / "server.log", "a")
    logf.write(f"\n=== {cfg.config_id} @ {time.strftime('%H:%M:%S')} ===\n{' '.join(args)}\n")
    logf.flush()
    proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT)
    deadline = time.time() + 60
    while time.time() < deadline:
        if server_alive():
            print(f"  SERVER {cfg.config_id} ready (pid={proc.pid})"); return proc
        time.sleep(2)
    proc.kill(); raise RuntimeError(f"server {cfg.config_id} timeout")


def stop_server():
    try:
        out = subprocess.check_output(["lsof", "-ti", ":8080"], stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        for pid in out.split("\n"):
            try: os.kill(int(pid), signal.SIGTERM)
            except: pass
        time.sleep(2)
        out2 = subprocess.check_output(["lsof", "-ti", ":8080"], stderr=subprocess.DEVNULL, timeout=3).decode().strip()
        for pid in out2.split("\n"):
            try: os.kill(int(pid), signal.SIGKILL)
            except: pass
    except: pass
    time.sleep(1)


def load_items(n: int):
    db = sqlite3.connect(str(DB_PATH))
    items = [(r[0], r[1]) for r in db.execute(
        "SELECT id, title FROM agent_raw_news WHERE source='eastmoney' AND title LIKE '%宁德时代%' ORDER BY id LIMIT ?", (n,)
    ).fetchall()]
    db.close(); return items


def clean_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text); text = re.sub(r"\n?```$", "", text)
    return text.strip()


def request_one(client, idx, db_id, title, worker_id, verbose=True):
    t0 = time.perf_counter(); ttft = None; text = ""; pt = ct = 0
    user_msg = NEW_PROMPT.format(title=title) + "\n\n" + OUTPUT_FORMAT
    try:
        stream = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
            max_tokens=80, temperature=0, top_p=1, stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if ttft is None: ttft = (time.perf_counter() - t0) * 1000
            if chunk.choices and chunk.choices[0].delta.content: text += chunk.choices[0].delta.content
            if chunk.usage: pt, ct = chunk.usage.prompt_tokens, chunk.usage.completion_tokens
        lat = (time.perf_counter() - t0) * 1000
        if ttft is None: ttft = lat
        parsed = json.loads(clean_json(text)) if text else None
        valid = bool(parsed and all(k in parsed for k in VERIFY_FIELDS))
        direction = parsed.get("direction") if parsed else None
        return {"idx": idx, "db_id": db_id, "title": title[:80], "worker_id": worker_id,
                "input_tokens": pt, "output_tokens": ct, "total_latency_ms": round(lat, 1),
                "ttft_ms": round(ttft, 1) if ttft else None,
                "direction": direction, "score": parsed.get("score") if parsed else None,
                "confidence": parsed.get("confidence") if parsed else None,
                "event_type": parsed.get("event_type") if parsed else None,
                "impact_channel": parsed.get("impact_channel") if parsed else None,
                "json_parse_success": valid, "error": None}
    except Exception as e:
        lat = (time.perf_counter() - t0) * 1000
        return {"idx": idx, "db_id": db_id, "title": title[:80], "worker_id": worker_id,
                "input_tokens": 0, "output_tokens": 0, "total_latency_ms": round(lat, 1),
                "ttft_ms": None, "direction": None, "confidence": None,
                "json_parse_success": False, "error": str(e)[:200]}


def run_batch(client, items, workers, config_id):
    results = [None] * len(items); done = [0]
    def do(i, db_id, title, w):
        r = request_one(client, i, db_id, title, w); results[i] = r; done[0] += 1
        ok = "OK" if r["json_parse_success"] else "FAIL"
        print(f"  [{config_id}] [{done[0]:2d}/{len(items)}] w{w} {r['total_latency_ms']:.0f}ms out={r['output_tokens']} {ok}", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(do, i, db_id, title, i % workers) for i, (db_id, title) in enumerate(items)]
        for _ in as_completed(futures): pass
    return [r for r in results if r is not None]


def summarize(results, config_id):
    valid = [r for r in results if r["json_parse_success"]]
    e = [r["total_latency_ms"] for r in results if r["total_latency_ms"] > 0]
    ttft = [r["ttft_ms"] for r in results if r.get("ttft_ms")]
    ot = [r["output_tokens"] for r in valid]
    labels = {}; [labels.update({r.get("direction","?"): labels.get(r.get("direction","?"), 0) + 1}) for r in valid]
    n = len(e); se = sorted(e)
    return {
        "config_id": config_id, "total": len(results), "success": len(valid),
        "success_rate_pct": round(100*len(valid)/len(results),1) if results else 0,
        "avg_latency_ms": round(sum(e)/n,0) if n else 0,
        "p50_latency_ms": round(se[n//2],0) if n else 0,
        "p90_latency_ms": round(se[int(n*0.9)],0) if n else 0,
        "avg_ttft_ms": round(sum(ttft)/len(ttft),0) if ttft else 0,
        "avg_output_tokens": round(sum(ot)/len(ot),0) if ot else 0,
        "labels": json.dumps(labels, ensure_ascii=False),
    }


def print_summary(s, extra=""):
    print(f"  {s['config_id']}: {s['success']}/{s['total']} OK ({s['success_rate_pct']}%) "
          f"avg={s['avg_latency_ms']:.0f}ms p50={s['p50_latency_ms']:.0f}ms "
          f"ttft={s['avg_ttft_ms']:.0f}ms out={s['avg_output_tokens']:.0f} {extra} {s['labels']}")


def save_jsonl(results, config_id):
    d = RESULTS_DIR / config_id; d.mkdir(parents=True, exist_ok=True)
    with open(d / "results.jsonl", "w") as f:
        for r in results: f.write(json.dumps(r, ensure_ascii=False) + "\n")


def save_csv(summaries, filename):
    if not summaries: return
    all_keys = list(dict.fromkeys(k for s in summaries for k in s.keys()))
    with open(RESULTS_DIR / filename, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore"); w.writeheader(); w.writerows(summaries)


# ══════════════════════════════════════════════════════════════
def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    items20 = load_items(EXPLORATORY_N)
    items50 = load_items(VALIDATION_N)
    print(f"Loaded: {len(items20)} exploratory, {len(items50)} validation\n")
    all_summaries = []
    start = time.time()

    # ══ DeepSeek Ground Truth ══
    print(f"{'#'*60}\n### DEEPSEEK GROUND TRUTH (new prompt) ###\n{'#'*60}")
    ds_client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
    for n_items, label in [(EXPLORATORY_N, "ds_exp"), (VALIDATION_N, "ds_val")]:
        items = items20 if label == "ds_exp" else items50
        out_dir = RESULTS_DIR / label; out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "results.jsonl"
        results = []
        print(f"\nDeepSeek {label} ({n_items} items):")
        for i, (db_id, title) in enumerate(items):
            t0 = time.perf_counter()
            user_msg = NEW_PROMPT.format(title=title) + "\n\n" + OUTPUT_FORMAT
            try:
                r = ds_client.chat.completions.create(
                    model="deepseek-v4-pro", messages=[{"role": "user", "content": user_msg}],
                    max_tokens=100, temperature=0, response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": "disabled"}},
                )
                text = clean_json(r.choices[0].message.content or "")
                parsed = json.loads(text)
                valid = bool(parsed and all(k in parsed for k in VERIFY_FIELDS))
                results.append({"idx": i, "db_id": db_id, "title": title[:80],
                    "direction": parsed.get("direction"), "score": parsed.get("score"),
                    "confidence": parsed.get("confidence"), "event_type": parsed.get("event_type"),
                    "impact_channel": parsed.get("impact_channel"),
                    "elapsed_s": round(time.perf_counter()-t0, 1), "valid": valid})
                print(f"  [{i+1:2d}/{n_items}] {(time.perf_counter()-t0):.1f}s {parsed.get('direction','?'):<8} cf={parsed.get('confidence','?')}", flush=True)
            except Exception as e:
                results.append({"idx": i, "error": str(e)[:200], "valid": False})
                print(f"  [{i+1:2d}/{n_items}] FAIL: {str(e)[:80]}", flush=True)
        with open(out_file, "w") as f:
            for r in results: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        labels = {}; [labels.update({r.get("direction","?"): labels.get(r.get("direction","?"),0)+1}) for r in results if r.get("valid")]
        print(f"  DeepSeek {label}: {sum(1 for r in results if r.get('valid'))}/{n_items} OK  labels={labels}")

    # ══ Qwen Exploratory Groups ══
    print(f"\n{'#'*60}\n### QWEN EXPLORATORY (20 items) ###\n{'#'*60}")

    # G1: Workers 1,4
    print(f"\n-- Group: Workers (server baseline) --")
    config = ServerConfig("g_new")
    proc = start_server(config)
    try:
        client = OpenAI(base_url=BASE_URL, api_key="x")
        for w in [1, 4]:
            cid = f"g2_w{w}"; results = run_batch(client, items20, w, cid)
            save_jsonl(results, cid); s = summarize(results, cid); s["workers"] = w
            print_summary(s); all_summaries.append(s)
    finally: stop_server(); time.sleep(2)

    # G2: Server Parallel
    print(f"\n-- Group: Server Parallel --")
    for p in [1, 4]:
        cid = f"g3_p{p}"; config = ServerConfig(cid, parallel=p)
        proc = start_server(config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items20, p, cid); save_jsonl(results, cid)
            s = summarize(results, cid); s["server_parallel"] = p; s["workers"] = p
            print_summary(s); all_summaries.append(s)
        finally: stop_server(); time.sleep(2)

    # G3: Context
    print(f"\n-- Group: Context Size --")
    for c in [4096, 8192]:
        cid = f"g4_c{c}"; config = ServerConfig(cid, ctx=c)
        proc = start_server(config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items20, 4, cid); save_jsonl(results, cid)
            s = summarize(results, cid); s["ctx"] = c; s["workers"] = 4
            print_summary(s); all_summaries.append(s)
        finally: stop_server(); time.sleep(2)

    # G4: Batch
    print(f"\n-- Group: Batch/Ubatch --")
    for b, ub in [(512, 512), (2048, 2048)]:
        cid = f"g5_b{b}_ub{ub}"; config = ServerConfig(cid, batch=b, ubatch=ub)
        proc = start_server(config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items20, 4, cid); save_jsonl(results, cid)
            s = summarize(results, cid); s["batch"] = b; s["ubatch"] = ub; s["workers"] = 4
            print_summary(s); all_summaries.append(s)
        finally: stop_server(); time.sleep(2)

    save_csv(all_summaries, "summary_exploratory.csv")

    # ══ Validation: 50 items ══
    print(f"\n{'#'*60}\n### VALIDATION (50 items) ###\n{'#'*60}")

    # Baseline
    print(f"\n-- Baseline (parallel=4, workers=4) --")
    config = ServerConfig("val_base"); proc = start_server(config)
    try:
        client = OpenAI(base_url=BASE_URL, api_key="x")
        results = run_batch(client, items50, 4, "val_base"); save_jsonl(results, "val_base")
        s = summarize(results, "val_base"); s["phase"] = "validation"; print_summary(s); all_summaries.append(s)
    finally: stop_server(); time.sleep(2)

    # Best config: pick by success_rate then latency
    exploratory = [s for s in all_summaries if not s["config_id"].startswith("val_")]
    exploratory.sort(key=lambda x: (-x["success_rate_pct"], x["avg_latency_ms"]))
    best = exploratory[0]
    best_w = best.get("workers", 4); best_p = best.get("server_parallel", 4)
    best_ctx = best.get("ctx", 4096); best_b = best.get("batch", 2048); best_ub = best.get("ubatch", 2048)
    print(f"\nBEST: {best['config_id']} ({best['avg_latency_ms']:.0f}ms, {best['success_rate_pct']}%)")

    for rnd in [1, 2]:
        cid = f"val_best_r{rnd}"
        config = ServerConfig(cid, parallel=best_p, ctx=best_ctx, batch=best_b, ubatch=best_ub)
        proc = start_server(config)
        try:
            client = OpenAI(base_url=BASE_URL, api_key="x")
            results = run_batch(client, items50, best_w, cid); save_jsonl(results, cid)
            s = summarize(results, cid); s["phase"] = "validation_best"; s["round"] = rnd
            print_summary(s); all_summaries.append(s)
        finally: stop_server(); time.sleep(2)

    save_csv(all_summaries, "summary_master.csv")

    # ══ Accuracy vs DeepSeek ══
    print(f"\n{'#'*60}\n### ACCURACY vs DEEPSEEK ###\n{'#'*60}")
    ds_labels = {}
    with open(RESULTS_DIR / "ds_val" / "results.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if r.get("valid"): ds_labels[r["idx"]] = r["direction"]

    for cid in ["val_base", "val_best_r1", "val_best_r2"]:
        path = RESULTS_DIR / cid / "results.jsonl"
        if not path.exists(): continue
        qw_labels = {}
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if r.get("json_parse_success"): qw_labels[r["idx"]] = r.get("direction")
        common = set(ds_labels) & set(qw_labels)
        matches = sum(1 for i in common if ds_labels[i] == qw_labels[i])
        acc = 100 * matches / len(common)
        print(f"  {cid}: {matches}/{len(common)} = {acc:.1f}% vs DeepSeek")

    elapsed = time.time() - start
    print(f"\n{'#'*60}\n### DONE in {elapsed:.0f}s ({elapsed/60:.1f}m) ###\n{'#'*60}")
    print(f"Results → {RESULTS_DIR}")


if __name__ == "__main__":
    main()
