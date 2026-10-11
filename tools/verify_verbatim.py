# -*- coding: utf-8 -*-
"""条款逐字契约校验（可重跑）。

对 kb/kb.sqlite 中每个 chunk 的 text，校验它是否逐字来自 kb/text/<doc_id>.txt，
按三种口径分别统计，任何口径都不命中的片段列为 FAIL 并打印样例。

用法：
    python tools/verify_verbatim.py                 # 全量校验，输出 tests/verbatim_check.txt + json
    python tools/verify_verbatim.py --sample 5      # 每个 FAIL 口径最多打印几条样例

口径说明：
  strict   片段原文直接是源文本的子串
  no_page  去掉源文本中的【第N页】分页标记后再比对
  no_ws    两侧折叠全部空白后再比对（中文不需要空格，排版换行不应算作不一致）
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'kb', 'kb.sqlite')
TEXT_DIR = os.path.join(BASE, 'kb', 'text')
META = os.path.join(BASE, 'kb', 'docs_meta.json')
OUT_TXT = os.path.join(BASE, 'tests', 'verbatim_check.txt')
OUT_JSON = os.path.join(BASE, 'tests', 'verbatim_check.json')

PAGE_MARK = re.compile(r'【第\d+页】')


def collapse_ws(s: str) -> str:
    return re.sub(r'\s+', '', s)


def load_meta():
    try:
        with open(META, encoding='utf-8') as f:
            return json.load(f).get('docs', {})
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=3)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    rows = con.execute('SELECT chunk_id, doc_id, seq, text FROM chunks ORDER BY chunk_id').fetchall()
    docs = {d: t for d, t in con.execute('SELECT doc_id, title FROM docs').fetchall()}
    con.close()

    meta = load_meta()
    src_cache = {}

    def source(doc_id):
        if doc_id not in src_cache:
            p = os.path.join(TEXT_DIR, str(doc_id) + '.txt')
            if not os.path.exists(p):
                src_cache[doc_id] = None
            else:
                with open(p, encoding='utf-8', errors='replace') as f:
                    raw = f.read()
                src_cache[doc_id] = {
                    'raw': raw,
                    'no_page': PAGE_MARK.sub('', raw),
                    'nows': collapse_ws(PAGE_MARK.sub('', raw)),
                }
        return src_cache[doc_id]

    stat = defaultdict(lambda: {'strict': 0, 'no_page': 0, 'nows': 0, 'fail': 0})
    fails = []
    missing_src = set()

    for cid, doc_id, seq, text in rows:
        if text is None:
            text = ''
        s = source(doc_id)
        if s is None:
            missing_src.add(doc_id)
            stat[doc_id]['fail'] += 1
            fails.append((cid, doc_id, seq, '源文本文件缺失 kb/text/%s.txt' % doc_id, text[:80]))
            continue
        needle = text
        if needle and needle in s['raw']:
            stat[doc_id]['strict'] += 1
        elif needle and needle in s['no_page']:
            stat[doc_id]['no_page'] += 1
        elif collapse_ws(needle) and collapse_ws(needle) in s['nows']:
            stat[doc_id]['nows'] += 1
        else:
            stat[doc_id]['fail'] += 1
            fails.append((cid, doc_id, seq, '三种口径均未命中', text[:120]))

    total = len(rows)
    ok = sum(v['strict'] + v['no_page'] + v['nows'] for v in stat.values())
    bad = sum(v['fail'] for v in stat.values())

    lines = []
    lines.append('条款逐字契约校验')
    lines.append('数据库: %s' % DB)
    lines.append('片段总数: %d   逐字命中: %d   不一致: %d' % (total, ok, bad))
    lines.append('命中口径分布: strict=%d  去分页标记=%d  折叠空白=%d' % (
        sum(v['strict'] for v in stat.values()),
        sum(v['no_page'] for v in stat.values()),
        sum(v['nows'] for v in stat.values())))
    if missing_src:
        lines.append('!! 缺源文本的 doc_id: %s' % sorted(missing_src))
    lines.append('')
    lines.append('%-8s %-34s %6s %6s %6s %6s' % ('doc_id', 'title', '命中', '去页码', '折叠', '不一致'))
    for doc_id in sorted(stat, key=lambda d: (-stat[d]['fail'], str(d))):
        v = stat[doc_id]
        title = (docs.get(doc_id) or (meta.get(str(doc_id), {}) or {}).get('title') or '')[:32]
        lines.append('%-8s %-34s %6d %6d %6d %6d' % (doc_id, title, v['strict'], v['no_page'], v['nows'], v['fail']))
    lines.append('')
    if fails:
        lines.append('===== 不一致明细（最多打印 %d 条 / 类）=====' % args.sample)
        by_reason = defaultdict(list)
        for f in fails:
            by_reason[f[3]].append(f)
        for reason, items in by_reason.items():
            lines.append('-- %s: %d 条' % (reason, len(items)))
            for cid, doc_id, seq, _, frag in items[:args.sample]:
                lines.append('   chunk_id=%s doc=%s seq=%s | %s' % (cid, doc_id, seq, frag.replace('\n', ' ⏎ ')))
    else:
        lines.append('===== 全部片段逐字命中，0 处不一致 =====')

    report = '\n'.join(lines)
    os.makedirs(os.path.dirname(OUT_TXT), exist_ok=True)
    with open(OUT_TXT, 'w', encoding='utf-8') as f:
        f.write(report + '\n')
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump({'total': total, 'verbatim_ok': ok, 'mismatch': bad,
                   'strict': sum(v['strict'] for v in stat.values()),
                   'no_page': sum(v['no_page'] for v in stat.values()),
                   'collapsed_ws': sum(v['nows'] for v in stat.values()),
                   'per_doc': {str(k): v for k, v in stat.items()}}, f, ensure_ascii=False, indent=1)
    print(report)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
