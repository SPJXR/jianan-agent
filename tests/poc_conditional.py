# -*- coding: utf-8 -*-
"""POC 补充实验3：条件向量补充（最终候选方案）。

规则：
- 强命中（max coverage >= REWRITE_MIN_COVERAGE=0.5）：完全走 BM25 原排序，向量不参与
- 弱命中（max coverage < 0.5，即现状会触发 LLM 改写的场景）：
  sources = 向量 top5（sim 降序） + BM25 top3（去重追加）
- 兜底判定与改写触发逻辑完全不变

对照指标：14 题 top-1/top-3/MRR（首轮检索，不含改写），及各题分支路径。
"""
import io
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import retrieval, config

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
VEC_TOP = 5
BM25_KEEP = 3

CASES = [
    ("A1", "特种作业人员报名考核需要满足什么条件？", "0063"),
    ("A2", "特种作业操作资格考核成绩能保留多久？", "0063"),
    ("A3", "施工现场的安全网有什么要求？可以用普通的密目网吗？", "0072"),
    ("A4", "桩头凿除有什么规定？", "0072"),
    ("A5", "专项施工方案里毗邻建筑物没有防护措施算严重缺陷吗？", "0071"),
    ("A6", "起重吊装的专项施工方案要注意什么？", "0071"),
    ("A7", "震后应急评估专家组可以采取哪些措施？", "0011"),
    ("A8", "震后建筑安全评估专家队由谁管理？", "0003"),
    ("A9", "项目开工怎么办理？走什么流程？", "0067"),
    ("A10", "历史文化街区划定有什么标准？", "0006"),
    ("C1", "工地上挖坑底下干活有啥危险要注意的？", "0069/0070"),
    ("C2", "考特种作业证有年龄限制没？", "0063"),
    ("C3", "震完了房子咋评估谁能去评？", "0011"),
    ("C4", "密目网着火了怎么办", "0072"),
]

from sentence_transformers import SentenceTransformer
model = SentenceTransformer(str(ROOT / "models" / "bge-small-zh-v1.5"))
z = np.load(ROOT / "kb" / "vec_index_bge-small-zh-v1.5.npz")
ids, vecs = list(z["chunk_ids"]), z["vectors"]
_con = sqlite3.connect(ROOT / "kb" / "kb.sqlite")
C2D = dict(_con.execute("SELECT chunk_id, doc_id FROM chunks").fetchall())
_con.close()


def conditional_hybrid(q):
    """返回 (排序后的 chunk_id 列表, 分支路径标记)。"""
    bm25_hits = retrieval.search(q, 8)
    if not bm25_hits:
        return [], "no_hit"
    max_cov = max(h["coverage"] for h in bm25_hits)
    if max_cov >= config.REWRITE_MIN_COVERAGE:
        # 强命中：BM25 原样
        return [h["chunk_id"] for h in bm25_hits], "strong(bm25)"
    # 弱命中：向量置前 + BM25 追加
    qv = model.encode([QUERY_PREFIX + q], normalize_embeddings=True, convert_to_numpy=True)[0]
    sims = vecs @ qv
    order = np.argsort(-sims)[:VEC_TOP]
    vec_ids = [int(ids[i]) for i in order]
    out = list(vec_ids)
    for h in bm25_hits[:BM25_KEEP]:
        if h["chunk_id"] not in out:
            out.append(h["chunk_id"])
    return out, "weak(vec_first)"


top1 = top3 = 0
mrr = 0.0
paths = {}
print("tag  路径              top3 文档")
for tag, q, expect in CASES:
    expects = expect.split("/")
    ranked, path = conditional_hybrid(q)
    paths[path] = paths.get(path, 0) + 1
    docs = [C2D[c] for c in ranked]
    pos = next((i + 1 for i, d in enumerate(docs) if d in expects), None)
    mark = f"OK@{pos}" if pos else "MISS"
    if pos:
        mrr += 1 / pos
        top1 += pos == 1
        top3 += pos <= 3
    print(f"{tag:<4} {path:<16} {docs[:3]} {mark}")

n = len(CASES)
print(f"\n条件补充方案: top1={top1/n:.1%} top3={top3/n:.1%} MRR={mrr/n:.3f}")
print(f"分支分布: {paths}")
print("对照: BM25 基线 top1=71.4% top3=85.7% MRR=0.792；VEC-small 单路 top1=78.6% top3=100% MRR=0.893")
