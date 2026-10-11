# -*- coding: utf-8 -*-
"""hybrid_search 服务端实现冒烟验证（改造正确性，非召回指标）。

验证三点（对照 tests/poc_conditional.py 已验证的行为）：
1. 强命中题：hybrid_search 与 search 逐块一致（零回归）
2. 弱命中题 C1：向量块置前（via=vector），top_cov 仍是 BM25 判据
3. 降级：HYBRID=off 时等价 search（回滚开关）
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import retrieval, config, vector_search

fails = []

# ---- 1. 向量路状态 ----
info = vector_search.backend_info()
print(f"[info] backend={info['backend']} ok={info['ok']} n_chunks={info['n_chunks']} err={info['err']}")
if not info["ok"]:
    fails.append("向量路不可用")

# ---- 2. 强命中题零回归 ----
strong_qs = [
    "特种作业人员报名考核需要满足什么条件？",   # A1
    "专项施工方案里毗邻建筑物没有防护措施算严重缺陷吗？",  # A5
    "震后应急评估专家组可以采取哪些措施？",     # A7
]
for q in strong_qs:
    base = retrieval.search(q, 8)
    hyb, cov = retrieval.hybrid_search(q, 8)
    same = [h["chunk_id"] for h in base] == [h["chunk_id"] for h in hyb]
    strong = cov >= config.REWRITE_MIN_COVERAGE
    print(f"[strong] {q[:18]}... cov={cov} 一致={same} 强命中分支={strong}")
    if not (same and strong):
        fails.append(f"强命中回归: {q}")

# ---- 3. 弱命中题 C1 向量置前 ----
q_c1 = "工地上挖坑底下干活有啥危险要注意的？"
hyb, cov = retrieval.hybrid_search(q_c1, 8)
vias = [h.get("via", "bm25") for h in hyb]
print(f"[weak] C1 cov={cov} top3 via={vias[:3]} docs={[h['doc_id'] for h in hyb[:3]]}")
if cov >= config.REWRITE_MIN_COVERAGE:
    fails.append("C1 未进入弱命中分支（覆盖率变化？）")
elif vias[:3].count("vector") < 2:
    fails.append("C1 向量未置前")

# ---- 4. HYBRID=off 回退 ----
config.HYBRID = False
vector_search._state["tried"] = False  # 重置单例状态
hyb2, cov2 = retrieval.hybrid_search(q_c1, 8)
base2 = retrieval.search(q_c1, 8)
same2 = [h["chunk_id"] for h in base2] == [h["chunk_id"] for h in hyb2]
config.HYBRID = True
vector_search._state["tried"] = False
print(f"[off] HYBRID=0 等价BM25: {same2}")
if not same2:
    fails.append("HYBRID=off 回退不等价")

print("\n" + ("ALL PASS" if not fails else f"FAIL: {fails}"))
sys.exit(1 if fails else 0)
