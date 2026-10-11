# -*- coding: utf-8 -*-
"""导出 kb.sqlite 全部文档文本到 docs/eval/_kb_dump.txt，供评测集命题核对。

每份文档输出：doc_id、标题、chunk 数、总字符数，然后是截断后的正文。
用法：.venv/Scripts/python.exe tools/dump_kb_text.py [每文档截断字符数，默认 40000]
"""
import io
import os
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "kb", "kb.sqlite")
META = os.path.join(BASE, "kb", "docs_meta.json")
OUT = os.path.join(BASE, "docs", "eval", "_kb_dump.txt")

CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 40000

import json  # noqa: E402

with open(META, "r", encoding="utf-8") as f:
    meta = json.load(f)["docs"]

conn = sqlite3.connect(DB)
cur = conn.cursor()
print("=== schema ===")
for row in cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
    print(row[0], "|", (row[1] or "").replace("\n", " ")[:200])
print()

# 找出正文表与列
tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
body_table, doc_col, txt_col = None, None, None
for cand in ("chunks", "chunk", "docs", "kb_chunks"):
    if cand in tables:
        cols = [r[1] for r in cur.execute("PRAGMA table_info(%s)" % cand)]
        print("table %s cols: %s" % (cand, cols))
        if body_table is None:
            body_table = cand
            for c in cols:
                if c.lower() in ("doc_id", "docid", "doc"):
                    doc_col = c
                if c.lower() in ("content", "text", "body", "chunk_text"):
                    txt_col = c
if body_table is None:
    print("!! 未找到正文表，退出")
    raise SystemExit(1)
print("use table=%s doc=%s text=%s" % (body_table, doc_col, txt_col))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as out:
    rows = cur.execute(
        "SELECT %s, %s FROM %s ORDER BY %s" % (doc_col, txt_col, body_table, doc_col)
    ).fetchall()
    by_doc = {}
    for d, t in rows:
        by_doc.setdefault(d, []).append(t or "")
    total = 0
    for d in sorted(by_doc):
        title = meta.get(str(d), {}).get("title", "?")
        text = "\n".join(by_doc[d])
        n = len(text)
        total += n
        head = "#### DOC %s | %s | chunks=%d chars=%d\n" % (d, title, len(by_doc[d]), n)
        out.write(head)
        body = text[:CAP]
        out.write(body.replace("\r", ""))
        if n > CAP:
            out.write("\n...[截断，共 %d 字符]" % n)
        out.write("\n\n")
        print("%s %-30s chunks=%3d chars=%6d cap=%d" % (d, title[:30], len(by_doc[d]), n, min(n, CAP)))
print("total chars = %d, dump -> %s" % (total, OUT))
