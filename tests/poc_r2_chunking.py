# -*- coding: utf-8 -*-
"""R2 表格感知分块 POC（ADR-005 预验证，只读不动正式库）。

用法：
    python tools/build_kb.py --out kb/kb_r2_poc.sqlite   # 先构建新分块库
    python tests/poc_r2_chunking.py

设计：
    - BASE 库 = 正式 kb.sqlite 的副本 + anchor 列全 NULL —— 新评分代码在
      NULL 锚点下退化为旧行为（cov 匹配面=纯 text），与线上 v5.1 同口径；
    - NEW 库 = kb_r2_poc.sqlite（表格感知分块 + anchor）；
    - 同一套 retrieval.search（BM25 主路）跑两库，模拟 main.py 的 ADR-004
      上下文装配（top8 主证据 + 窗口内同文档补位），按 run_eval 同口径
      （norm + hit_groups over context text）计算 ctx_cov 代理指标；
    - 4 个目标题（SAF-07/SUP-02/SUP-03/GOV-07）逐题打印答案块在 30 位
      窗口内的排名与上下文可见性。

判据：
    1) 目标题答案块进 top-8（主证据）或至少进上下文（同文档补位）；
    2) 55 道 fact 题 ctx_cov 代理指标不劣化（ctx_full 数 >= 基线）。
"""
import io
import json
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import app.config as config  # noqa: E402
from app import retrieval  # noqa: E402

OLD_DB = os.path.join(BASE, "kb", "kb.sqlite")
NEW_DB = os.path.join(BASE, "kb", "kb_r2_poc.sqlite")
BASE_DB = os.path.join(BASE, "kb", "kb_r2_base.sqlite")
EVAL_SET = os.path.join(BASE, "docs", "eval", "eval_set_v2.json")

# 目标题答案块定位（在库内必须同时含每组的全部模式）
TARGETS = {
    "SAF-07": [["机械强制通风措施", "出入口"], ["30min"]],
    "SUP-02": [["站车位置", "吊装参数表"]],
    "SUP-03": [["拆撑", "漏水漏砂"]],
    "GOV-07": [["（四）施工安全监管（33项）"], ["工程质量安全检查（129项）"], ["JGJ 46"]],
}


def make_base_db():
    """旧分块库 + anchor 全 NULL = 旧行为复刻（评分代码同一套）"""
    if os.path.exists(BASE_DB):
        os.remove(BASE_DB)
    shutil.copy(OLD_DB, BASE_DB)
    con = sqlite3.connect(BASE_DB)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(chunks)")]
        if "anchor" not in cols:
            con.execute("ALTER TABLE chunks ADD COLUMN anchor TEXT")
            con.commit()
    finally:
        con.close()


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def hit_groups(text: str, groups) -> set:
    t = norm(text)
    return {i for i, g in enumerate(groups) if any(norm(w) in t for w in g)}


def context_of(hits):
    """复刻 main.py ADR-004 装配：先按 RECALL_WINDOW 截断（main.py 将窗口
    作为检索 top_k 传入），top-8 主证据 + 窗口内(9~W)同文档补位"""
    hits = hits[:config.RECALL_WINDOW]
    primary = hits[:config.RETRIEVAL_TOP_K]
    pdocs = {h["doc_id"] for h in primary}
    supp = [h for h in hits[config.RETRIEVAL_TOP_K:] if h["doc_id"] in pdocs]
    return primary, supp


def find_answer_chunks(db_path, patterns):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    out = []
    try:
        for group in patterns:
            rows = con.execute(
                "SELECT chunk_id, doc_id, clause, anchor FROM chunks WHERE " +
                " AND ".join("text LIKE ?" for _ in group),
                tuple(f"%{p}%" for p in group)).fetchall()
            out.append([dict(r) for r in rows])
    finally:
        con.close()
    return out


def main():
    make_base_db()
    spec = json.load(open(EVAL_SET, encoding="utf-8"))
    items = spec if isinstance(spec, list) else spec.get("items", spec.get("questions", []))
    facts = [q for q in items if q["type"] == "fact"]

    # ---------- 1) 目标题：答案块排名 ----------
    print("=" * 78)
    print("一、目标题答案块排名（30 位窗口，[] = 进上下文）")
    print("=" * 78)
    for qid, patterns in TARGETS.items():
        q = next(x for x in items if x["id"] == qid)
        print(f"\n### {qid}  {q['question']}")
        for label, db_path in (("BASE", BASE_DB), ("NEW ", NEW_DB)):
            retrieval.DB_PATH = db_path
            hits = retrieval.search(q["question"], 30)
            order = {h["chunk_id"]: i + 1 for i, h in enumerate(hits)}
            primary, supp = context_of(hits)
            ctx_ids = {h["chunk_id"] for h in primary + supp}
            groups = find_answer_chunks(db_path, patterns)
            marks = []
            for gi, rows in enumerate(groups):
                for r in rows:
                    rank = order.get(r["chunk_id"])
                    inctx = r["chunk_id"] in ctx_ids
                    marks.append(
                        f"P{gi}#{r['chunk_id']}({r['doc_id']})"
                        f"={rank if rank else '>30'}{'[ctx]' if inctx else ''}")
            top3 = " ".join(f"{h['doc_id']}:{h['coverage']}" for h in hits[:3])
            print(f"  {label}: top3={top3}")
            print(f"        answer: {' '.join(marks) if marks else '(定位失败)'}")

    # ---------- 2) 55 道 fact 题：ctx_cov 代理指标 before/after ----------
    print()
    print("=" * 78)
    print("二、fact 题 ctx_cov 代理指标（BM25 模拟装配，run_eval 同口径）")
    print("=" * 78)

    # 预取每题在两库的 30 位命中（窗口扫描复用，避免重复检索）
    cache = {}
    for q in facts:
        hits_pair = []
        for db_path in (BASE_DB, NEW_DB):
            retrieval.DB_PATH = db_path
            hits_pair.append(retrieval.search(q["question"], 30))
        cache[q["id"]] = hits_pair

    def sweep(window):
        old_w = config.RECALL_WINDOW
        config.RECALL_WINDOW = window
        try:
            stats = {}
            for label in (0, 1):  # 0=base 1=new
                full = 0
                for q in facts:
                    groups = q.get("keywords") or []
                    n = len(groups) or 1
                    primary, supp = context_of(cache[q["id"]][label])
                    ctx_text = " ".join(h["text"] for h in primary + supp)
                    if len(hit_groups(ctx_text, groups)) / n >= 0.999:
                        full += 1
                stats[label] = full
            return stats
        finally:
            config.RECALL_WINDOW = old_w

    print("\n窗口扫描（ctx_full / 55）:")
    print(f"  {'window':>6} | BASE | NEW")
    for w in (14, 15, 16, 18):
        s = sweep(w)
        print(f"  {w:>6} | {s[0]:>4} | {s[1]:>4}")

    # 默认窗口 14 的逐题对比
    rows_out = []
    for q in facts:
        groups = q.get("keywords") or []
        n = len(groups) or 1
        covs = {}
        for label in (0, 1):
            primary, supp = context_of(cache[q["id"]][label])
            ctx_text = " ".join(h["text"] for h in primary + supp)
            covs[label] = round(len(hit_groups(ctx_text, groups)) / n, 2)
        rows_out.append((q["id"], covs[0], covs[1], q["question"]))

    worse = [(i, b, nw, qs) for i, b, nw, qs in rows_out if nw < b]
    better = [(i, b, nw, qs) for i, b, nw, qs in rows_out if nw > b]
    base_full = sum(1 for _, b, _, _ in rows_out if b >= 0.999)
    new_full = sum(1 for _, _, nw, _ in rows_out if nw >= 0.999)
    print(f"\nctx_full(=1.0): BASE {base_full}/55  ->  NEW {new_full}/55")
    print(f"提升 {len(better)} 题 / 下降 {len(worse)} 题")
    if better:
        print("\n-- 提升 --")
        for i, b, nw, qs in better:
            print(f"  {i}: {b:.2f} -> {nw:.2f}  {qs[:30]}")
    if worse:
        print("\n-- 下降（需复核）--")
        for i, b, nw, qs in worse:
            print(f"  {i}: {b:.2f} -> {nw:.2f}  {qs[:30]}")
    # 明细落盘
    out_path = os.path.join(BASE, "docs", "eval", "results", "poc_r2_ctxcov.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("id\tbase\tnew\tquestion\n")
        for i, b, nw, qs in rows_out:
            f.write(f"{i}\t{b:.2f}\t{nw:.2f}\t{qs}\n")
    print(f"\n明细已写入 {os.path.relpath(out_path, BASE)}")


if __name__ == "__main__":
    main()
