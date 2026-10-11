# -*- coding: utf-8 -*-
"""DEF-04 检索排序诊断：新库 top16 的 score/cov/via，答案块为何排 12。"""
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import retrieval, config  # noqa: E402

Q = "有限空间内氧气浓度多少算合格？"

hits, top_cov = retrieval.hybrid_search(Q, config.RECALL_WINDOW)
print(f"window={config.RECALL_WINDOW} top_cov={top_cov}")
for i, h in enumerate(hits):
    has = "19.5" in h["text"] or "23.5" in h["text"]
    via = h.get("via", "bm25")
    print(f"  #{i+1:>2} score={h.get('score')} cov={h['coverage']} via={via:>6} "
          f"[{h['doc_id']} {h['clause'][:10]}] {'***答案***' if has else ''} "
          f"{h['text'][:36]!r}")

# BASE 库（旧行为）对照
print("\n== 旧库（BASE）对照 ==")
retrieval.DB_PATH = os.path.join(BASE, "kb", "kb_r2_base.sqlite")
hits2 = retrieval.search(Q, 16)
for i, h in enumerate(hits2):
    has = "19.5" in h["text"] or "23.5" in h["text"]
    print(f"  #{i+1:>2} score={h.get('score')} cov={h['coverage']} "
          f"[{h['doc_id']} {h['clause'][:10]}] {'***答案***' if has else ''} "
          f"{h['text'][:36]!r}")
