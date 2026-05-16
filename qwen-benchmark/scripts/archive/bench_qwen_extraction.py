"""Qwen3.6 structured JSON extraction benchmark.

Usage:
  python backtests/scripts/bench_qwen_extraction.py
"""
import json, time, re, sqlite3, os, sys
from openai import OpenAI
import concurrent.futures

QWEN_URL = 'http://127.0.0.1:8080/v1'
QWEN_MODEL = 'Qwen3.6-35B-A3B-Q4_K_M.gguf'
WORKERS = 4
SAMPLES = 50

PROMPT = '''你是A股新闻影响评估助手。请只输出合法JSON，不要输出Markdown。
任务：分析新闻对股票300750.SZSE（宁德时代）的影响。

新闻标题：{title}

输出JSON（严格按此格式，8个字段全英文key）：
{{"event":"中文摘要","relation_type":"direct_company","impact_direction":"positive","impact_strength":0.5,"time_horizon":"short","confidence":0.7,"reason":"中文理由","evidence":"新闻关键句"}}'''

def clean_json(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    return text.strip()

def eval_one(client, idx, db_id, title):
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {'role': 'system', 'content': '你是一个JSON输出机器。只输出合法JSON。'},
                {'role': 'user', 'content': PROMPT.format(title=title)}
            ],
            max_tokens=256, temperature=0,
        )
        text = clean_json(r.choices[0].message.content or '')
        try:
            parsed = json.loads(text)
        except:
            parsed = None
        valid = parsed and all(k in parsed for k in ['event','impact_direction','impact_strength','confidence'])
        return {
            'idx': idx, 'title': title[:60], 'elapsed': time.time()-t0,
            'pt': r.usage.prompt_tokens, 'ct': r.usage.completion_tokens,
            'valid': valid,
            'dir': parsed.get('impact_direction') if parsed else None,
            'has_think': '<think>' in (r.choices[0].message.content or ''),
            'raw_preview': text[:200],
        }
    except Exception as e:
        return {'idx': idx, 'title': title[:60], 'error': str(e)[:150], 'elapsed': time.time()-t0, 'valid': False}

def main():
    client = OpenAI(base_url=QWEN_URL, api_key='x')
    db = sqlite3.connect(os.path.expanduser('~/.vntrader/agent_news.db'))
    items = [(r[0], r[1]) for r in db.execute(
        "SELECT id, title FROM agent_raw_news WHERE source='eastmoney' AND title LIKE '%宁德时代%' ORDER BY RANDOM() LIMIT ?",
        (SAMPLES,)
    ).fetchall()]
    db.close()

    print(f'Qwen3.6-35B-A3B (workers={WORKERS}, {len(items)} items)')
    print('='*60)

    results = [None]*len(items)
    done = [0]
    def do(i, rid, title):
        r = eval_one(client, i, rid, title)
        results[i] = r
        done[0] += 1
        valid = 'OK' if r.get('valid') else 'FAIL'
        think = 'THINK' if r.get('has_think') else ''
        print(f'  [{done[0]:2d}/{len(items)}] {r.get("elapsed",0):.1f}s {valid} {think}  {title[:40]}', flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(lambda x: do(*x), [(i, rid, title) for i, (rid, title) in enumerate(items)]))

    valid = [r for r in results if r.get('valid')]
    think = [r for r in results if r.get('has_think')]
    elapsed = [r.get('elapsed',0) for r in results if r.get('elapsed',0)>0]
    pt = [r.get('pt',0) for r in valid]
    ct = [r.get('ct',0) for r in valid]
    dirs = {}
    for r in valid:
        d = r.get('dir','?')
        dirs[d] = dirs.get(d,0)+1

    print(f'\nSuccess: {len(valid)}/{len(items)} ({100*len(valid)/len(items):.0f}%)')
    print(f'Think blocks: {len(think)}/{len(items)} ({100*len(think)/len(items):.0f}%)')
    print(f'Time: avg={sum(elapsed)/len(elapsed):.1f}s min={min(elapsed):.1f}s max={max(elapsed):.1f}s')
    if pt: print(f'Tokens: prompt_avg={sum(pt)/len(pt):.0f} completion_avg={sum(ct)/len(ct):.0f}')
    print(f'Direction: {dirs}')

    fails = [r for r in results if not r.get('valid')]
    if fails:
        print(f'\nFailure samples ({len(fails)} total):')
        for r in fails[:3]:
            print(f'  #{r["idx"]}: {r.get("error","")[:150]}')
            print(f'    raw: {r.get("raw_preview","")[:150]}')

    return results

if __name__ == '__main__':
    main()
