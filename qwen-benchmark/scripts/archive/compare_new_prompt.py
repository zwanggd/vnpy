#!/usr/bin/env python3
"""Quick 10-item comparison: new prompt + new output format, DeepSeek vs Qwen."""
import json, os, re, sqlite3, time
from pathlib import Path
from openai import OpenAI

DEEPSEEK_KEY = "sk-f070c281b3624c9fb92043006dbc408a"
QWEN_URL = "http://127.0.0.1:8080/v1"
DB = Path.home() / ".vntrader" / "agent_news.db"

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

请只输出合法JSON，不要输出任何解释、Markdown或额外文字。"""

OUTPUT_FORMAT = """按以下JSON格式输出：
{{"event_type":"operating|financing|share_supply|regulatory|legal|product|partnership|governance|routine|other","impact_channel":"revenue_or_demand|profit_or_margin|financing_or_liquidity|share_supply|regulatory_or_legal|product_or_partnership|governance_or_control|routine_disclosure|other","direction":"positive|neutral|negative","score":-1.0,"confidence":0.0}}

score取值规则：positive取0.1到1.0，negative取-1.0到-0.1，neutral取0。"""

SYSTEM_PROMPT = "你是一个JSON输出机器。只输出合法JSON。不要输出任何解释、Markdown或额外文字。"

# Same 10 items from manual comparison
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
    user_msg = NEW_PROMPT.format(title=title) + "\n\n" + OUTPUT_FORMAT
    print(f"\n#{idx}: {title[:80]}")

    # DeepSeek
    t0 = time.perf_counter()
    try:
        r = ds_client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=200, temperature=0,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        ds_text = (r.choices[0].message.content or "").strip()
        if ds_text.startswith("```"):
            ds_text = re.sub(r"^```\w*\n?", "", ds_text)
            ds_text = re.sub(r"\n?```$", "", ds_text)
        ds = json.loads(ds_text)
        ds_elapsed = time.perf_counter() - t0
        print(f"  DS ({ds_elapsed:.1f}s): {ds.get('direction'):<8} ch={ds.get('impact_channel','?')} sc={ds.get('score')} cf={ds.get('confidence')}")
    except Exception as e:
        ds = {"error": str(e)[:200]}
        ds_elapsed = time.perf_counter() - t0
        print(f"  DS: ERROR - {e}")

    # Qwen
    t0 = time.perf_counter()
    try:
        r = qw_client.chat.completions.create(
            model="Qwen3.6-35B-A3B-Q4_K_M.gguf",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=200, temperature=0, top_p=1,
        )
        qw_text = (r.choices[0].message.content or "").strip()
        if qw_text.startswith("```"):
            qw_text = re.sub(r"^```\w*\n?", "", qw_text)
            qw_text = re.sub(r"\n?```$", "", qw_text)
        qw = json.loads(qw_text)
        qw_elapsed = time.perf_counter() - t0
        print(f"  QW ({qw_elapsed:.1f}s): {qw.get('direction'):<8} ch={qw.get('impact_channel','?')} sc={qw.get('score')} cf={qw.get('confidence')}")
    except Exception as e:
        qw = {"error": str(e)[:200]}
        qw_elapsed = time.perf_counter() - t0
        print(f"  QW: ERROR - {e}")

    comparisons.append({
        "idx": idx, "title": title,
        "ds": ds, "ds_s": round(ds_elapsed, 1),
        "qw": qw, "qw_s": round(qw_elapsed, 1),
    })

# Save
out_path = Path(__file__).parent.parent / "results" / "comparison_new_prompt.json"
with open(out_path, "w") as f:
    json.dump(comparisons, f, ensure_ascii=False, indent=2)

# Summary
print(f"\n{'='*110}")
print(f"{'#':<3} {'Title':<42} {'DS':<9} {'QW':<9} {'Agree':>6} {'DS ch':<28} {'QW ch':<28}")
print("-" * 110)
agree = 0
for c in comparisons:
    ds_d = c["ds"].get("direction", "?")
    qw_d = c["qw"].get("direction", "?")
    match = "✓" if ds_d == qw_d else "✗"
    if ds_d == qw_d:
        agree += 1
    print(f"{c['idx']:<3} {c['title'][:40]:<42} {ds_d:<9} {qw_d:<9} {match:>6} {c['ds'].get('impact_channel','?'):<28} {c['qw'].get('impact_channel','?'):<28}")
print(f"\n  Agree: {agree}/{len(comparisons)} ({100*agree/len(comparisons):.0f}%)")
print(f"  vs old prompt (A0): 6/10 (60%)")

# Old vs new comparison
print(f"\n{'='*80}")
print("OLD PROMPT vs NEW PROMPT — Disagreements resolved?")
print(f"{'='*80}")
old_disagree = {0: ("neutral","positive"), 2: ("positive","neutral"), 6: ("positive","negative"), 10: ("neutral","negative")}
for c in comparisons:
    idx = c["idx"]
    if idx in old_disagree:
        old_ds, old_qw = old_disagree[idx]
        new_ds = c["ds"].get("direction","?")
        new_qw = c["qw"].get("direction","?")
        old_agree = "✗"
        new_agree = "✓" if new_ds == new_qw else "✗"
        print(f"  #{idx}: old DS={old_ds} QW={old_qw} {old_agree} → new DS={new_ds} QW={new_qw} {new_agree}")
