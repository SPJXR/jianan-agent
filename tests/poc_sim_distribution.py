# -*- coding: utf-8 -*-
"""POC 补充实验：向量 top1 相似度在库内/库外题上的分布，寻找兜底判据阈值。

核心问题：若向量单路替代 BM25 主排序，「未找到」兜底不能再依赖 BM25 覆盖率，
需确认库内题与库外题的 top1 相似度是否可分。
"""
import io
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

IN_SCOPE = [
    ("A1", "特种作业人员报名考核需要满足什么条件？"),
    ("A2", "特种作业操作资格考核成绩能保留多久？"),
    ("A3", "施工现场的安全网有什么要求？可以用普通的密目网吗？"),
    ("A4", "桩头凿除有什么规定？"),
    ("A5", "专项施工方案里毗邻建筑物没有防护措施算严重缺陷吗？"),
    ("A6", "起重吊装的专项施工方案要注意什么？"),
    ("A7", "震后应急评估专家组可以采取哪些措施？"),
    ("A8", "震后建筑安全评估专家队由谁管理？"),
    ("A9", "项目开工怎么办理？走什么流程？"),
    ("A10", "历史文化街区划定有什么标准？"),
    ("C1", "工地上挖坑底下干活有啥危险要注意的？"),
    ("C2", "考特种作业证有年龄限制没？"),
    ("C3", "震完了房子咋评估谁能去评？"),
    ("C4", "密目网着火了怎么办"),
]
OUT_OF_SCOPE = [
    ("B1", "工地食堂需要办理什么证照？"),
    ("B2", "高温天气工地几点到几点不允许室外作业？"),
    ("B3", "塔吊司机证怎么复审？"),
    ("B4", "帮我写一首关于安全的诗"),
    ("B5", "住建部现任部长是谁？"),
]

from sentence_transformers import SentenceTransformer
from app import retrieval

model = SentenceTransformer(str(ROOT / "models" / "bge-small-zh-v1.5"))
z = np.load(ROOT / "kb" / "vec_index_bge-small-zh-v1.5.npz")
ids, vecs = list(z["chunk_ids"]), z["vectors"]
_con = sqlite3.connect(ROOT / "kb" / "kb.sqlite")
C2D = dict(_con.execute("SELECT chunk_id, doc_id FROM chunks").fetchall())
_con.close()

print("库内题（top1/top2 相似度 + BM25 覆盖率对照）：")
print("tag  vec_top1  vec_top2  bm25_top1_cov")
in_sims = []
for tag, q in IN_SCOPE:
    qv = model.encode([QUERY_PREFIX + q], normalize_embeddings=True, convert_to_numpy=True)[0]
    sims = vecs @ qv
    order = np.argsort(-sims)[:2]
    hits = retrieval.search(q, 3)
    cov = hits[0]["coverage"] if hits else 0
    in_sims.append(float(sims[order[0]]))
    print(f"{tag:<4} {sims[order[0]]:.3f}    {sims[order[1]]:.3f}    {cov}")

print("\n库外题（top1 相似度）：")
out_sims = []
for tag, q in OUT_OF_SCOPE:
    qv = model.encode([QUERY_PREFIX + q], normalize_embeddings=True, convert_to_numpy=True)[0]
    sims = vecs @ qv
    top = np.argmax(sims)
    out_sims.append(float(sims[top]))
    print(f"{tag:<4} {sims[top]:.3f}   doc={C2D[ids[top]]}")

import statistics
print(f"\n库内 top1: min={min(in_sims):.3f} mean={statistics.mean(in_sims):.3f}")
print(f"库外 top1: max={max(out_sims):.3f} mean={statistics.mean(out_sims):.3f}")
sep = (min(in_sims) + max(out_sims)) / 2
print(f"可分性: 库内min={min(in_sims):.3f} vs 库外max={max(out_sims):.3f} "
      f"{'可分' if min(in_sims) > max(out_sims) else '重叠，需区间策略'} | 中点≈{sep:.3f}")
