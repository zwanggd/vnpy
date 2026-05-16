#!/usr/bin/env python3
"""Analyze all CATL news with DeepSeek V4 Flash and/or Qwen3.6, storing results in news_analysis table."""
from __future__ import annotations

import argparse, json, os, re, signal, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path
from openai import OpenAI

# ── Constants ───────────────────────────────────────────────
MODEL_PATH = Path("/Users/kai/.lmstudio/models/lmstudio-community/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf")
LLAMA_SERVER = "/opt/homebrew/bin/llama-server"
DB_PATH = Path.home() / ".vntrader" / "agent_news.db"
QWEN_BASE_URL = "http://127.0.0.1:8080/v1"
QWEN_MODEL_NAME = "Qwen3.6-35B-A3B-Q4_K_M.gguf"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_KEY = "sk-f070c281b3624c9fb92043006dbc408a"
RESULTS_DIR = Path(__file__).parent.parent / "results_v2"

QWEN_SERVER_ARGS = [
    "-m", str(MODEL_PATH),
    "-c", "4096",
    "-ngl", "99",
    "-fa", "on",
    "-b", "512",
    "-ub", "512",
    "--cache-type-k", "q8_0",
    "--cache-type-v", "q8_0",
    "--parallel", "1",
    "--cache-reuse", "256",
    "--ctx-checkpoints", "32",
    "--cache-ram", "8192",
    "--host", "127.0.0.1",
    "--port", "8080",
    "--reasoning", "off",
]

QWEN_SYSTEM_PROMPT = "你是一个JSON输出机器。只输出合法JSON。不要输出任何解释、Markdown或额外文字。"

# ── Prompt Template ─────────────────────────────────────────
ANALYSIS_PROMPT = """你是一名股票新闻信号分析员。

你的任务是判断一条关于「宁德时代 / CATL」的新闻，在发布当下对公司股价的短期方向影响。

请只根据新闻标题和正文判断。不要使用新闻发布后的股价走势，也不要假设新闻中没有出现的事实。

你可以像分析师一样自由判断，但必须遵守以下标准：

1. 判断的是新闻对股价预期的边际影响，而不是判断公司长期好坏。
2. 关注新闻发布后约 1 到 5 个交易日内可能产生的短期可交易影响。
3. 如果新闻明确改善市场对收入、利润、订单、需求、技术、监管、融资条件、供应链地位、市场份额或战略价值的预期，可以判断为 positive。
4. 如果新闻明确恶化市场对收入、利润、需求、监管、诉讼、融资压力、股本稀释、股东减持压力、治理结构或业务风险的预期，可以判断为 negative。
5. 常规公告通常偏 neutral，但不能因为它是公告就自动判断为 neutral。如果公告内容包含明确交易信号，应根据实际影响判断。
6. 融资、发债、配售、增发、股东转让、减持、回购、授信等事件通常是混合事件。你需要判断短期市场更可能如何解读：偏正面、偏负面，还是中性。
7. 如果正负因素同时存在，而且无法判断哪一方明显占优，则判断为 neutral，并给出中低置信度。
8. 如果信号较弱但方向明确，可以判断为 positive 或 negative，但应降低 confidence 和 signal_strength。
9. 不要因为新闻缺少具体财务数字就过度使用 neutral。
10. 不要因为新闻措辞乐观或悲观，就过度判断为 positive 或 negative。关键是是否存在实际影响路径。

新闻标题：{title}

新闻正文：{content}

只输出 JSON。不要输出 Markdown。不要输出额外解释。

JSON 格式必须如下：
{{
  "direction": "positive|neutral|negative",
  "score": -1.0,
  "confidence": 0.0,
  "signal_strength": "strong|medium|weak|none",
  "event_type": "operating|financial|financing|shareholder_action|regulatory|legal|product|partnership|industry|routine_disclosure|governance|other",
  "impact_channel": "revenue_demand|profit_margin|capital_liquidity|share_supply|regulatory_legal|technology_product|partnership_strategy|governance_control|industry_sentiment|routine|other",
  "rationale": "用一句简短中文说明核心判断理由"
}}"""

# ── Valid enums ─────────────────────────────────────────────
VALID_DIRECTIONS = {"positive", "neutral", "negative"}
VALID_SIGNAL_STRENGTHS = {"strong", "medium", "weak", "none"}
VALID_EVENT_TYPES = {"operating", "financial", "financing", "shareholder_action",
                     "regulatory", "legal", "product", "partnership", "industry",
                     "routine_disclosure", "governance", "other"}
VALID_IMPACT_CHANNELS = {"revenue_demand", "profit_margin", "capital_liquidity",
                         "share_supply", "regulatory_legal", "technology_product",
                         "partnership_strategy", "governance_control",
                         "industry_sentiment", "routine", "other"}


# ── Server Lifecycle ────────────────────────────────────────
def qwen_server_alive():
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"{QWEN_BASE_URL}/models", method="GET"),
            timeout=3
        )
        return True
    except Exception:
        return False


def start_qwen_server():
    """Start llama-server if not already running."""
    if qwen_server_alive():
        print("[Qwen] Server already running")
        return None
    print("[Qwen] Starting llama-server...")
    args = [LLAMA_SERVER] + QWEN_SERVER_ARGS
    log_dir = RESULTS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logf = open(log_dir / "qwen_server.log", "a")
    logf.write(f"\n=== START @ {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n{' '.join(args)}\n")
    logf.flush()
    proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT)
    deadline = time.time() + 120
    while time.time() < deadline:
        if qwen_server_alive():
            print(f"[Qwen] Server ready (pid={proc.pid})")
            return proc
        time.sleep(2)
    proc.kill()
    raise RuntimeError("Qwen server failed to start within 120s")


def stop_qwen_server():
    """Kill any process on port 8080."""
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", ":8080"], stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        for pid in out.split("\n"):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except Exception:
                pass
        time.sleep(2)
        out2 = subprocess.check_output(
            ["lsof", "-ti", ":8080"], stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        for pid in out2.split("\n"):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(1)


def get_server_config_json():
    return json.dumps({
        "server": LLAMA_SERVER,
        "args": QWEN_SERVER_ARGS,
        "model_path": str(MODEL_PATH),
        "base_url": QWEN_BASE_URL,
    }, ensure_ascii=False)


def get_request_params_json(model_name, max_tokens, temperature, extra=None):
    params = {
        "model": model_name,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if extra:
        params.update(extra)
    return json.dumps(params, ensure_ascii=False)


# ── Database ────────────────────────────────────────────────
def get_db():
    return sqlite3.connect(str(DB_PATH))


def already_done(db, news_id, model, prompt_version):
    row = db.execute(
        """SELECT id FROM news_analysis
           WHERE news_id=? AND model=? AND prompt_version=?
           AND parse_success=1 AND error IS NULL""",
        (news_id, model, prompt_version)
    ).fetchone()
    return row is not None


def load_items(n):
    db = sqlite3.connect(str(DB_PATH))
    rows = db.execute(
        """SELECT id, title, COALESCE(content,'') as content, published_at
           FROM agent_raw_news
           WHERE source='eastmoney' AND title LIKE '%宁德时代%'
           ORDER BY id LIMIT ?""",
        (n,)
    ).fetchall()
    db.close()
    return rows


# ── JSON Cleaning ───────────────────────────────────────────
def clean_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


# ── Validation ──────────────────────────────────────────────
def validate_parsed(parsed):
    """Returns (is_valid, error_msg). Validates all enum fields and ranges."""
    errors = []
    d = parsed.get("direction")
    if d not in VALID_DIRECTIONS:
        errors.append(f"invalid direction: {d}")
    s = parsed.get("signal_strength")
    if s not in VALID_SIGNAL_STRENGTHS:
        errors.append(f"invalid signal_strength: {s}")
    e = parsed.get("event_type")
    if e and e not in VALID_EVENT_TYPES:
        errors.append(f"invalid event_type: {e}")
    ic = parsed.get("impact_channel")
    if ic and ic not in VALID_IMPACT_CHANNELS:
        errors.append(f"invalid impact_channel: {ic}")
    score = parsed.get("score")
    if score is not None:
        try:
            score = float(score)
            if score < -1.0 or score > 1.0:
                errors.append(f"score out of range: {score}")
        except (TypeError, ValueError):
            errors.append(f"score not numeric: {score}")
    conf = parsed.get("confidence")
    if conf is not None:
        try:
            conf = float(conf)
            if conf < 0.0 or conf > 1.0:
                errors.append(f"confidence out of range: {conf}")
        except (TypeError, ValueError):
            errors.append(f"confidence not numeric: {conf}")
    return (len(errors) == 0, "; ".join(errors) if errors else None)


# ── UPSERT ──────────────────────────────────────────────────
def upsert_analysis(db, news_id, model, model_provider, prompt_version,
                    direction, score, confidence, signal_strength,
                    event_type, impact_channel, rationale,
                    raw_response, parse_success, error, error_type,
                    retry_count, latency_ms, input_tokens, output_tokens,
                    request_params_json, server_config_json,
                    news_published_at=None):
    """UPSERT with ON CONFLICT DO UPDATE. Only updates if original parse_success=0 or --force."""
    db.execute("""
        INSERT INTO news_analysis (
            news_id, model, model_provider, prompt_version,
            direction, score, confidence, signal_strength,
            event_type, impact_channel, rationale,
            raw_response, parse_success, error, error_type,
            retry_count, latency_ms, input_tokens, output_tokens,
            request_params_json, server_config_json,
            news_published_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(news_id, model, prompt_version) DO UPDATE SET
            direction=excluded.direction,
            score=excluded.score,
            confidence=excluded.confidence,
            signal_strength=excluded.signal_strength,
            event_type=excluded.event_type,
            impact_channel=excluded.impact_channel,
            rationale=excluded.rationale,
            raw_response=excluded.raw_response,
            parse_success=excluded.parse_success,
            error=excluded.error,
            error_type=excluded.error_type,
            retry_count=excluded.retry_count,
            latency_ms=excluded.latency_ms,
            input_tokens=excluded.input_tokens,
            output_tokens=excluded.output_tokens,
            request_params_json=excluded.request_params_json,
            server_config_json=excluded.server_config_json,
            news_published_at=excluded.news_published_at,
            updated_at=CURRENT_TIMESTAMP
        WHERE news_analysis.parse_success=0
    """, (
        news_id, model, model_provider, prompt_version,
        direction, score, confidence, signal_strength,
        event_type, impact_channel, rationale,
        raw_response, parse_success, error, error_type,
        retry_count, latency_ms, input_tokens, output_tokens,
        request_params_json, server_config_json,
        news_published_at,
    ))
    db.commit()


# ── Force update flag ───────────────────────────────────────
_force_flag = False


def upsert_analysis_force(db, news_id, model, model_provider, prompt_version,
                          direction, score, confidence, signal_strength,
                          event_type, impact_channel, rationale,
                          raw_response, parse_success, error, error_type,
                          retry_count, latency_ms, input_tokens, output_tokens,
                          request_params_json, server_config_json,
                          news_published_at=None):
    """UPSERT that forces update regardless of original parse_success."""
    db.execute("""
        INSERT INTO news_analysis (
            news_id, model, model_provider, prompt_version,
            direction, score, confidence, signal_strength,
            event_type, impact_channel, rationale,
            raw_response, parse_success, error, error_type,
            retry_count, latency_ms, input_tokens, output_tokens,
            request_params_json, server_config_json,
            news_published_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(news_id, model, prompt_version) DO UPDATE SET
            direction=excluded.direction,
            score=excluded.score,
            confidence=excluded.confidence,
            signal_strength=excluded.signal_strength,
            event_type=excluded.event_type,
            impact_channel=excluded.impact_channel,
            rationale=excluded.rationale,
            raw_response=excluded.raw_response,
            parse_success=excluded.parse_success,
            error=excluded.error,
            error_type=excluded.error_type,
            retry_count=excluded.retry_count,
            latency_ms=excluded.latency_ms,
            input_tokens=excluded.input_tokens,
            output_tokens=excluded.output_tokens,
            request_params_json=excluded.request_params_json,
            server_config_json=excluded.server_config_json,
            news_published_at=excluded.news_published_at,
            updated_at=CURRENT_TIMESTAMP
    """, (
        news_id, model, model_provider, prompt_version,
        direction, score, confidence, signal_strength,
        event_type, impact_channel, rationale,
        raw_response, parse_success, error, error_type,
        retry_count, latency_ms, input_tokens, output_tokens,
        request_params_json, server_config_json,
        news_published_at,
    ))
    db.commit()


# ── Analysis Runner ─────────────────────────────────────────
def analyze_deepseek(items, prompt_version, force, db):
    """Analyze with DeepSeek V4 Flash API."""
    model_name = DEEPSEEK_MODEL
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE_URL)
    skipped = 0
    succeeded = 0
    failed = 0

    for i, (news_id, title, content, published_at) in enumerate(items):
        # Check skip
        if not force and already_done(db, news_id, model_name, prompt_version):
            skipped += 1
            continue

        request_params_json = get_request_params_json(
            model_name, 120, 0,
            {"response_format": {"type": "json_object"},
             "extra_body": {"thinking": {"type": "disabled"}}}
        )

        user_msg = ANALYSIS_PROMPT.format(title=title, content=content)
        t0 = time.perf_counter()
        raw_text = ""
        error_msg = None
        error_type = None
        parse_success = 0
        pt = ct = 0
        retry = 0

        def _call_api(max_tok):
            nonlocal raw_text, pt, ct
            resp = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": user_msg}],
                max_tokens=max_tok,
                temperature=0,
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw_text = resp.choices[0].message.content or ""
            if resp.usage:
                pt = resp.usage.prompt_tokens
                ct = resp.usage.completion_tokens

        try:
            _call_api(120)
            cleaned = clean_json(raw_text)
            parsed = json.loads(cleaned)
            valid, val_err = validate_parsed(parsed)
            if not valid:
                raise ValueError(f"Enum/range validation failed: {val_err}")
            parse_success = 1
        except (json.JSONDecodeError, Exception) as e:
            retry = 1
            try:
                _call_api(160)
                cleaned = clean_json(raw_text)
                parsed = json.loads(cleaned)
                valid, val_err = validate_parsed(parsed)
                if not valid:
                    raise ValueError(f"Enum/range validation failed after retry: {val_err}")
                parse_success = 1
            except (json.JSONDecodeError, Exception) as e2:
                error_msg = str(e2)[:500]
                error_type = type(e2).__name__
                parsed = {}

        lat = round((time.perf_counter() - t0) * 1000, 1)

        if parse_success:
            succeeded += 1
        else:
            failed += 1

        upsert_analysis(
            db, news_id, model_name, "deepseek", prompt_version,
            parsed.get("direction"), parsed.get("score"), parsed.get("confidence"),
            parsed.get("signal_strength"), parsed.get("event_type"),
            parsed.get("impact_channel"), parsed.get("rationale"),
            raw_text, parse_success, error_msg, error_type,
            retry, lat, pt, ct,
            request_params_json, None,
            news_published_at=published_at,
        )

        status = "OK" if parse_success else "FAIL"
        direc = parsed.get("direction", "?")
        print(f"  [DS] [{i+1}/{len(items)}] {direc:<8} {status} lat={lat:.0f}ms"
              f" tok={pt}/{ct}{' retry' if retry else ''}{' skipped='+str(skipped) if skipped else ''}",
              flush=True)

    print(f"\n[DeepSeek] Done: {succeeded} OK, {failed} failed, {skipped} skipped")
    return {"succeeded": succeeded, "failed": failed, "skipped": skipped}


def analyze_qwen(items, prompt_version, force, db):
    """Analyze with Qwen3.6 local server."""
    model_name = QWEN_MODEL_NAME
    client = OpenAI(base_url=QWEN_BASE_URL, api_key="x")
    skipped = 0
    succeeded = 0
    failed = 0

    server_cfg = get_server_config_json()

    for i, (news_id, title, content, published_at) in enumerate(items):
        if not force and already_done(db, news_id, model_name, prompt_version):
            skipped += 1
            continue

        request_params_json = get_request_params_json(
            model_name, 120, 0,
            {"top_p": 1, "stream": False}
        )

        user_msg = ANALYSIS_PROMPT.format(title=title, content=content)
        t0 = time.perf_counter()
        raw_text = ""
        error_msg = None
        error_type = None
        parse_success = 0
        pt = ct = 0
        retry = 0

        def _call_api(max_tok):
            nonlocal raw_text, pt, ct
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": QWEN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=max_tok,
                temperature=0,
                top_p=1,
                stream=False,
            )
            raw_text = resp.choices[0].message.content or ""
            if resp.usage:
                pt = resp.usage.prompt_tokens
                ct = resp.usage.completion_tokens

        try:
            _call_api(120)
            cleaned = clean_json(raw_text)
            parsed = json.loads(cleaned)
            valid, val_err = validate_parsed(parsed)
            if not valid:
                raise ValueError(f"Enum/range validation failed: {val_err}")
            parse_success = 1
        except (json.JSONDecodeError, Exception) as e:
            retry = 1
            try:
                _call_api(160)
                cleaned = clean_json(raw_text)
                parsed = json.loads(cleaned)
                valid, val_err = validate_parsed(parsed)
                if not valid:
                    raise ValueError(f"Enum/range validation failed after retry: {val_err}")
                parse_success = 1
            except (json.JSONDecodeError, Exception) as e2:
                error_msg = str(e2)[:500]
                error_type = type(e2).__name__
                parsed = {}

        lat = round((time.perf_counter() - t0) * 1000, 1)

        if parse_success:
            succeeded += 1
        else:
            failed += 1

        upsert_analysis(
            db, news_id, model_name, "qwen", prompt_version,
            parsed.get("direction"), parsed.get("score"), parsed.get("confidence"),
            parsed.get("signal_strength"), parsed.get("event_type"),
            parsed.get("impact_channel"), parsed.get("rationale"),
            raw_text, parse_success, error_msg, error_type,
            retry, lat, pt, ct,
            None, server_cfg,
            news_published_at=published_at,
        )

        status = "OK" if parse_success else "FAIL"
        direc = parsed.get("direction", "?")
        print(f"  [QW] [{i+1}/{len(items)}] {direc:<8} {status} lat={lat:.0f}ms"
              f" tok={pt}/{ct}{' retry' if retry else ''}{' skipped='+str(skipped) if skipped else ''}",
              flush=True)

    print(f"\n[Qwen] Done: {succeeded} OK, {failed} failed, {skipped} skipped")
    return {"succeeded": succeeded, "failed": failed, "skipped": skipped}


# ── Comparison Report ───────────────────────────────────────
def generate_report(db, limit, prompt_version, output_path):
    """Generate comparison report."""
    ds_rows = db.execute(
        """SELECT news_id, direction, score, confidence, signal_strength,
                  event_type, impact_channel, rationale
           FROM news_analysis
           WHERE model=? AND prompt_version=? AND parse_success=1
           ORDER BY news_id LIMIT ?""",
        (DEEPSEEK_MODEL, prompt_version, limit)
    ).fetchall()

    qw_rows = db.execute(
        """SELECT news_id, direction, score, confidence, signal_strength,
                  event_type, impact_channel, rationale
           FROM news_analysis
           WHERE model=? AND prompt_version=? AND parse_success=1
           ORDER BY news_id LIMIT ?""",
        (QWEN_MODEL_NAME, prompt_version, limit)
    ).fetchall()

    ds_map = {r[0]: r for r in ds_rows}
    qw_map = {r[0]: r for r in qw_rows}

    common_ids = sorted(set(ds_map) & set(qw_map))
    if not common_ids:
        print("No common items to compare.")
        return

    agree = 0
    disagree = 0

    lines = []
    lines.append("# CATL News Analysis Comparison Report\n")
    lines.append(f"**Prompt Version**: {prompt_version}")
    lines.append(f"**Items compared**: {len(common_ids)}\n")
    lines.append("## Direction Agreement\n")

    for nid in common_ids:
        ds_dir = ds_map[nid][1]
        qw_dir = qw_map[nid][1]
        match = "✓" if ds_dir == qw_dir else "✗"
        if ds_dir == qw_dir:
            agree += 1
        else:
            disagree += 1
        lines.append(f"- **#{nid}**: DS={ds_dir:<8} QW={qw_dir:<8} {match}")

    lines.append(f"\n**Agreement**: {agree}/{len(common_ids)} ({100*agree/len(common_ids):.1f}%)")
    lines.append(f"**Disagreements**: {disagree}/{len(common_ids)} ({100*disagree/len(common_ids):.1f}%)\n")

    # Direction distribution
    lines.append("## Direction Distribution\n")
    for label, rows in [("DeepSeek", ds_rows), ("Qwen", qw_rows)]:
        counts = {}
        for r in rows:
            d = r[1]
            counts[d] = counts.get(d, 0) + 1
        lines.append(f"**{label}**: {json.dumps(counts, ensure_ascii=False)}")

    # Score stats
    lines.append("\n## Score Statistics\n")
    for label, rows in [("DeepSeek", ds_rows), ("Qwen", qw_rows)]:
        scores = sorted([r[2] for r in rows if r[2] is not None])
        if scores:
            n = len(scores)
            lines.append(f"**{label}** (n={n}): min={min(scores):.2f} p50={scores[n//2]:.2f} max={max(scores):.2f}")

    # Confidence stats
    lines.append("\n## Confidence Statistics\n")
    for label, rows in [("DeepSeek", ds_rows), ("Qwen", qw_rows)]:
        confs = sorted([r[3] for r in rows if r[3] is not None])
        if confs:
            n = len(confs)
            lines.append(f"**{label}** (n={n}): min={min(confs):.2f} p50={confs[n//2]:.2f} max={max(confs):.2f}")

    # Signal strength distribution
    lines.append("\n## Signal Strength Distribution\n")
    for label, rows in [("DeepSeek", ds_rows), ("Qwen", qw_rows)]:
        counts = {}
        for r in rows:
            s = r[4]
            counts[s] = counts.get(s, 0) + 1
        lines.append(f"**{label}**: {json.dumps(counts, ensure_ascii=False)}")

    # High confidence disagreements
    lines.append("\n## High-Confidence Disagreements (confidence >= 0.7)\n")
    hc_count = 0
    for nid in common_ids:
        ds_row = ds_map[nid]
        qw_row = qw_map[nid]
        if ds_row[1] != qw_row[1] and ds_row[3] >= 0.7 and qw_row[3] >= 0.7:
            hc_count += 1
            lines.append(f"### News #{nid}")
            lines.append(f"- DS: {ds_row[1]} (cf={ds_row[3]:.2f}) — {ds_row[7]}")
            lines.append(f"- QW: {qw_row[1]} (cf={qw_row[3]:.2f}) — {qw_row[7]}")
            lines.append("")
    lines.append(f"**Total high-confidence disagreements**: {hc_count}")

    report = "\n".join(lines)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(report)
        print(f"Report saved → {output_path}")
    else:
        print(report)


# ── Validate ────────────────────────────────────────────────
def run_validation(db, prompt_version):
    """Validate all records for enum/range compliance."""
    rows = db.execute(
        """SELECT id, model, news_id, direction, score, confidence,
                  signal_strength, event_type, impact_channel
           FROM news_analysis
           WHERE prompt_version=? AND parse_success=1""",
        (prompt_version,)
    ).fetchall()

    errors = []
    for row in rows:
        rid, model, nid, d, sc, cf, ss, et, ic = row
        if d not in VALID_DIRECTIONS:
            errors.append(f"#{rid} ({model} news#{nid}): invalid direction='{d}'")
        if ss and ss not in VALID_SIGNAL_STRENGTHS:
            errors.append(f"#{rid} ({model} news#{nid}): invalid signal_strength='{ss}'")
        if et and et not in VALID_EVENT_TYPES:
            errors.append(f"#{rid} ({model} news#{nid}): invalid event_type='{et}'")
        if ic and ic not in VALID_IMPACT_CHANNELS:
            errors.append(f"#{rid} ({model} news#{nid}): invalid impact_channel='{ic}'")
        if sc is not None and (sc < -1.0 or sc > 1.0):
            errors.append(f"#{rid} ({model} news#{nid}): score={sc} out of range")
        if cf is not None and (cf < 0.0 or cf > 1.0):
            errors.append(f"#{rid} ({model} news#{nid}): confidence={cf} out of range")

    # UNIQUE constraint check
    dupes = db.execute(
        """SELECT news_id, model, prompt_version, COUNT(*)
           FROM news_analysis GROUP BY news_id, model, prompt_version
           HAVING COUNT(*) > 1"""
    ).fetchall()
    for d in dupes:
        errors.append(f"UNIQUE violation: news_id={d[0]} model={d[1]} pv={d[2]} count={d[3]}")

    if errors:
        print(f"VALIDATION FAILED — {len(errors)} violations:")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"VALIDATION PASSED — all {len(rows)} records compliant")


# ── Main ────────────────────────────────────────────────────
def main():
    global _force_flag

    parser = argparse.ArgumentParser(description="Analyze CATL news with LLMs")
    parser.add_argument("--model", choices=["deepseek", "qwen", "both"], default="both",
                        help="Which model(s) to run")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max items to analyze")
    parser.add_argument("--prompt-version", default="v1",
                        help="Prompt version tag (default: v1)")
    parser.add_argument("--force", action="store_true",
                        help="Re-analyze even if already successful")
    parser.add_argument("--compare", action="store_true",
                        help="Generate comparison report")
    parser.add_argument("--output", type=str, default=None,
                        help="Output path for comparison report")
    parser.add_argument("--validate", action="store_true",
                        help="Run validation checks")
    args = parser.parse_args()

    _force_flag = args.force
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Validate mode ──
    if args.validate:
        db = get_db()
        run_validation(db, args.prompt_version)
        db.close()
        return

    # ── Compare mode ──
    if args.compare:
        db = get_db()
        limit = args.limit or 99999
        generate_report(db, limit, args.prompt_version, args.output)
        db.close()
        return

    # ── Analyze mode ──
    limit = args.limit or 99999
    items = load_items(limit)
    if not items:
        print("No items found to analyze.")
        return

    print(f"Loaded {len(items)} items (limit={args.limit}, prompt_version={args.prompt_version})")
    print(f"Force re-analysis: {args.force}\n")

    db = get_db()

    qwen_proc = None
    try:
        if args.model in ("deepseek", "both"):
            print(f"{'='*60}")
            print(f"### DEEPSEEK V4 FLASH ###")
            print(f"{'='*60}")
            analyze_deepseek(items, args.prompt_version, args.force, db)

        if args.model in ("qwen", "both"):
            print(f"\n{'='*60}")
            print(f"### QWEN3.6 LOCAL ###")
            print(f"{'='*60}")
            qwen_proc = start_qwen_server()
            analyze_qwen(items, args.prompt_version, args.force, db)

    finally:
        if qwen_proc:
            print("\n[Qwen] Stopping server...")
            stop_qwen_server()
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
