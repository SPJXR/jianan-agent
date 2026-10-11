# -*- coding: utf-8 -*-
"""POC 补充实验2：加权融合权重定标。

架构（V4 定稿方向）：BM25 主链路不变，向量做重排增强 + 补充召回。
score_final = bm25_score + VEC_W * vec_sim
补充召回块（BM25 未召回但向量 top10 内）：score = VEC_W * vec_sim，coverage=0。

本实验网格搜索 VEC_W，指标：14 题测试集 top-1/top-3/MRR。
"""
import io
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import retrieval

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
VEC_TOP = 10
FINAL_K = 8

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

# 预计算每题向量 top10
vec_tops = {}
for tag, q, _ in CASES:
    qv = model.encode([QUERY_PREFIX + q], normalize_embeddings=True, convert_to_numpy=True)[0]
    sims = vecs @ qv
    order = np.argsort(-sims)[:VEC_TOP]
    vec_tops[tag] = {int(ids[i]): float(sims[i]) for i in order}


def hybrid_rank(q, tag, vec_w):
    """BM25 主链路结果（含内部 score）+ 向量重排 + 补充召回。"""
    bm25_hits = retrieval.search(q, VEC_TOP)  # 取宽一点便于对齐
    scored = {}
    for h in bm25_hits:
        cid = h["chunk_id"]
        vs = vec_tops[tag].get(cid, 0.0)
        scored[cid] = h["score"] + vec_w * vs
    # 补充召回：向量 top10 中 BM25 未召回的
    for cid, vs in vec_tops[tag].items():
        if cid not in scored:
            scored[cid] = vec_w * vs
    ranked = sorted(scored.items(), key=lambda x: -x[1])[:FINAL_K]
    return ranked


print("| VEC_W | top-1 | top-3 | MRR | 未命中 |")
print("|-------|-------|-------|-----|--------|")
for w in [0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]:
    top1 = top3 = 0
    mrr = 0.0
    miss = []
    for tag, q, expect in CASES:
        expects = expect.split("/")
        ranked = hybrid_rank(q, tag, w)
        docs = [C2D[c] for c, _ in ranked]
        pos = next((i + 1 for i, d in enumerate(docs) if d in expects), None)
        if pos:
            mrr += 1 / pos
            top1 += pos == 1
            top3 += pos <= 3
        else:
            miss.append(tag)
    n = len(CASES)
    print(f"| {w} | {top1/n:.1%} | {top3/n:.1%} | {mrr/n:.3f} | {','.join(miss) or '-'} |")
