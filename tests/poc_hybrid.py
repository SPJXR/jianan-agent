# -*- coding: utf-8 -*-
"""A方向混合检索 POC：四方案召回对比实验。

方案：
  1. bm25      —— 现有 FTS5+覆盖率重排（基线，V3 线上现状）
  2. vec-small —— bge-small-zh-v1.5 向量单路（余弦）
  3. vec-large —— bge-large-zh-v1.5 向量单路（余弦）
  4. rrf-*     —— BM25 + 向量 RRF 融合（k=60，各取 top10）

评测集：qa_regression 的 14 道库内题（问题 → 预期文档前缀）。
指标：top-1 命中率 / top-3 命中率 / MRR。
B 组 5 题兜底观察：向量路 top1 相似度与命中文档（误召回风险，仅报告不断言）。

输出：markdown 对比表 + 每题明细（-v），供 POC 报告引用。

用法：python tests/poc_hybrid.py [-v]
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import retrieval, config

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
RRF_K = 60
TOPK_EACH = 10
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

OUT_OF_SCOPE = [
    ("B1", "工地食堂需要办理什么证照？"),
    ("B2", "高温天气工地几点到几点不允许室外作业？"),
    ("B3", "塔吊司机证怎么复审？"),
    ("B4", "帮我写一首关于安全的诗"),
    ("B5", "住建部现任部长是谁？"),
]

VERBOSE = "-v" in sys.argv

import sqlite3
_con = sqlite3.connect(ROOT / "kb" / "kb.sqlite")
CHUNK2DOC = dict(_con.execute("SELECT chunk_id, doc_id FROM chunks").fetchall())
_con.close()


def load_vec(model_name, query_text):
    """编码 query 并返回 (chunk_ids, 相似度排序后的 (chunk_id, score) top 列表)。"""
    from sentence_transformers import SentenceTransformer
    z = np.load(ROOT / "kb" / f"vec_index_{model_name}.npz")
    ids, vecs = list(z["chunk_ids"]), z["vectors"]
    model = SentenceTransformer(str(ROOT / "models" / model_name))
    qv = model.encode([QUERY_PREFIX + query_text], normalize_embeddings=True,
                      convert_to_numpy=True).astype(np.float32)[0]
    sims = vecs @ qv
    order = np.argsort(-sims)[:TOPK_EACH]
    return ids, [(ids[i], float(sims[i])) for i in order]


def bm25_ranked(question):
    """BM25 路现有实现，取 top 各返回 (chunk_id, 伪分数按名次)。"""
    hits = retrieval.search(question, TOPK_EACH)
    return [(h["chunk_id"], 1.0 / (RRF_K + i + 1)) for i, h in enumerate(hits)]


def rrf_merge(list_a, list_b, k=RRF_K, final_k=FINAL_K):
    """标准 RRF：score = Σ 1/(k+rank)，两路名次均从 1 起。"""
    scores = {}
    for lst in (list_a, list_b):
        for rank, (cid, _) in enumerate(lst, start=1):
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])[:final_k]


def doc_of(chunk_id):
    return CHUNK2DOC.get(int(chunk_id)) or CHUNK2DOC.get(chunk_id) or str(chunk_id)


def eval_scheme(name, rank_fn, detail):
    top1 = top3 = 0
    mrr = 0.0
    rows = []
    for tag, q, expect in CASES:
        expects = expect.split("/")
        ranked = rank_fn(q)
        docs = [doc_of(cid) for cid, _ in ranked]
        hit_pos = next((i + 1 for i, d in enumerate(docs) if d in expects), None)
        if hit_pos:
            mrr += 1.0 / hit_pos
            if hit_pos == 1:
                top1 += 1
            if hit_pos <= 3:
                top3 += 1
        rows.append((tag, docs[:3] if hit_pos is None or hit_pos > 1 else docs[:3],
                     "OK" if hit_pos else "MISS"))
        if VERBOSE:
            print(f"  {tag} {q[:16]:<18} -> {docs[:3]} {'OK@'+str(hit_pos) if hit_pos else 'MISS'}")
    n = len(CASES)
    detail[name] = {
        "top1": top1 / n, "top3": top3 / n, "mrr": mrr / n,
        "miss": [r[0] for r in rows if r[2] == "MISS"],
    }
    return detail[name]


def main():
    print(f"评测集: {len(CASES)} 库内题 | RRF k={RRF_K} 各路top{TOPK_EACH} 融合取{FINAL_K}")
    print(f"BM25 参数: TOP_K={config.RETRIEVAL_TOP_K} MIN_COV={config.MIN_COVERAGE}")
    print()

    results = {}

    # 方案1: BM25 基线
    eval_scheme("BM25(基线)", lambda q: bm25_ranked(q), results)

    # 方案2/3: 向量单路（small / large）
    vec_models = {}
    for m in ["bge-small-zh-v1.5", "bge-large-zh-v1.5"]:
        vec_models[m] = {}
        for tag, q in CASES + OUT_OF_SCOPE if False else [(t, q) for t, q, _ in CASES] + [(t, q) for t, q in OUT_OF_SCOPE]:
            ids, top = load_vec(m, q)
            vec_models[m][tag] = top
        eval_scheme(
            f"VEC-{m.split('-')[1]}",
            lambda q, m=m: [(c, s) for c, s in vec_models[m][
                next(t for t, qq, _ in CASES if qq == q)]],
            results)

    # 方案4: RRF 融合（双模型各测）
    for m in ["bge-small-zh-v1.5", "bge-large-zh-v1.5"]:
        short = m.split("-")[1]
        eval_scheme(
            f"RRF(BM25+{short})",
            lambda q, m=m: rrf_merge(
                [(c, s) for c, s in bm25_ranked(q)],
                vec_models[m][next(t for t, qq, _ in CASES if qq == q)]),
            results)

    # ---- 汇总表 ----
    print("\n| 方案 | top-1 | top-3 | MRR | 未命中题 |")
    print("|------|-------|-------|-----|---------|")
    for name, r in results.items():
        print(f"| {name} | {r['top1']:.1%} | {r['top3']:.1%} | {r['mrr']:.3f} | {','.join(r['miss']) or '-'} |")

    # ---- B 组误召回观察（向量路） ----
    print("\nB 组库外题：向量 top1 相似度 / 命中文档（误召回观察，参考线：BM25 覆盖率 < MIN_COVERAGE 即兜底）")
    for m in ["bge-small-zh-v1.5", "bge-large-zh-v1.5"]:
        short = m.split("-")[1]
        for tag, q in OUT_OF_SCOPE:
            top = vec_models[m][tag]
            print(f"  {short} {tag} {q[:14]:<16} top1={top[0][1]:.3f} doc={doc_of(top[0][0])}")

    # ---- CPU 编码延迟参考（small，3 次平均） ----
    import time
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(ROOT / "models" / "bge-small-zh-v1.5"))
    for _ in range(3):
        model.encode([QUERY_PREFIX + "预热"], normalize_embeddings=True)
    t0 = time.time()
    for _ in range(10):
        model.encode([QUERY_PREFIX + "特种作业人员报名考核需要满足什么条件"], normalize_embeddings=True)
    print(f"\nbge-small CPU 单次 query 编码延迟: {(time.time()-t0)/10*1000:.0f} ms")


if __name__ == "__main__":
    main()
