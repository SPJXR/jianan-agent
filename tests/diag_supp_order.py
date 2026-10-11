# -*- coding: utf-8 -*-
"""supp 序号验证：DEF-04 答案块与 PM-06 #210 在 supplement 列表中的位置。

若两者 supp 序号均 ≤6，则「supplement ≤6 条截断」可同时：
  - 缩短 DEF-04 上下文（16→14 条），改善 LLM 拒答
  - 保住 PM-06 #210（窗口 16 收益不丢）
"""
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import retrieval, config  # noqa: E402

CASES = [
    ("DEF-04", "有限空间内氧气浓度多少算合格？",
     lambda h: "19.5" in h["text"] or "23.5" in h["text"]),
    ("PM-06", "哪些工程属于要办消防设计审查的特殊建设工程？",
     lambda h: "一类高层" in h["text"]),
    ("SAF-07", "有限空间作业前通风有哪些硬性要求？",
     lambda h: "30min" in h["text"] or "机械强制通风" in h["text"]),
]

for qid, q, pred in CASES:
    hits, top_cov = retrieval.hybrid_search(q, config.RECALL_WINDOW)
    primary = hits[:config.RETRIEVAL_TOP_K]
    pdocs = {h["doc_id"] for h in primary}
    supp = [h for h in hits[config.RETRIEVAL_TOP_K:] if h["doc_id"] in pdocs]
    print(f"== {qid} == window={config.RECALL_WINDOW} n_hits={len(hits)} "
          f"primary={len(primary)} supp={len(supp)}")
    for i, h in enumerate(supp):
        mark = " <<<" if pred(h) else ""
        print(f"   supp[{i+1}] rank={config.RETRIEVAL_TOP_K + i + 1 if h in hits else '?'} "
              f"[{h['doc_id']}] {h['text'][:30]!r}{mark}")
    # 答案块在 primary 的情况
    for i, h in enumerate(primary):
        if pred(h):
            print(f"   *** primary[{i+1}] 含答案 [{h['doc_id']}] ***")
    print()
