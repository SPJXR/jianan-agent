# -*- coding: utf-8 -*-
"""C1 向量救回失效诊断（iter4 T2-C1 FAIL 根因）。

C1 = "工地上挖坑底下干活有啥危险要注意的？"（口语，预期 0069/0070 有限空间）。
旧库旧索引：向量 top3 含 0069/0070（救回成功）；新库新索引：top3 全 0071。

对比维度：
  1) 新库新索引（anchor+text 编码）下 C1 的向量 top10；
  2) BM25 top14（弱命中场景的窗口）；
  3) 0069/0070 有限空间相关块的向量相似度排名；
  4) 旧库行为对照：用旧库文本重建临时索引不可行（耗时），
     改为对比块文本本身——旧 0069"有限空间作业"块 vs 新分块后相应块的文本差异。
"""
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import retrieval, vector_search, config  # noqa: E402

Q = "工地上挖坑底下干活有啥危险要注意的？"

print("=" * 78)
print("1) 向量 top10（新索引 anchor+text）")
print("=" * 78)
if vector_search.available():
    hits = vector_search.top_k(Q, 10)
    for i, h in enumerate(hits):
        print(f"  #{i+1} sim={h['sim']} [{h['doc_id']} {h['title'][:18]} | {h['clause'][:10]}] "
              f"anchor={h.get('anchor') or '-'}")
        print(f"     text: {h['text'][:70]}")
else:
    print("  向量路不可用:", vector_search.backend_info())

print()
print("=" * 78)
print("2) BM25 top14（弱命中窗口）")
print("=" * 78)
hits = retrieval.search(Q, 14)
for i, h in enumerate(hits):
    print(f"  #{i+1} cov={h['coverage']} [{h['doc_id']} {h['clause'][:10]}] "
          f"{h['text'][:50]}")

print()
print("=" * 78)
print("3) hybrid_search 融合结果 top8")
print("=" * 78)
hits, top_cov = retrieval.hybrid_search(Q, config.RECALL_WINDOW)
print(f"  top_cov={top_cov}")
for i, h in enumerate(hits):
    via = h.get("via", "bm25")
    print(f"  #{i+1} via={via} sim={h.get('sim', '-')} cov={h['coverage']} "
          f"[{h['doc_id']} {h['clause'][:10]}] {h['text'][:44]}")

print()
print("=" * 78)
print("4) 0069/0070 各块的向量相似度（找「危险/识别」相关块掉到哪）")
print("=" * 78)
if vector_search.available():
    qv = vector_search._state["enc"].encode(vector_search.QUERY_PREFIX + Q)
    import numpy as np
    sims = vector_search._state["vecs"] @ qv
    ids = vector_search._state["ids"]
    order = np.argsort(-sims)
    rank_of = {int(ids[i]): int(r + 1) for r, i in enumerate(order)}
    import sqlite3
    con = sqlite3.connect(os.path.join(BASE, "kb", "kb.sqlite"))
    con.row_factory = sqlite3.Row
    # 0069/0070 里含「危险有害因素」或「有限空间作业」的块（C1 预期答案区）
    rows = con.execute(
        "SELECT chunk_id, doc_id, clause, anchor, text FROM chunks "
        "WHERE doc_id IN ('0069','0070') AND "
        "(text LIKE '%危险有害%' OR text LIKE '%先通风%' OR anchor LIKE '%危险%') "
        "ORDER BY doc_id, chunk_id").fetchall()
    for r in rows:
        cid = int(r["chunk_id"])
        idx = order.tolist().index(ids.index(cid)) if cid in ids else -1
        print(f"  #{r['chunk_id']} [{r['doc_id']} {r['clause'][:10]}] "
              f"vec_rank={rank_of.get(cid, '>all')} sim={sims[ids.index(cid)]:.4f} "
              f"anchor={r['anchor'] or '-'}")
        print(f"     {r['text'][:60]}")
    # 0071 的块为何排前：看向量 top5 里 0071 的 anchor
    con.close()
