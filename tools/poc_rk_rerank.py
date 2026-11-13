# -*- coding: utf-8 -*-
"""r_k 重排离线 POC（2026-11-13，LongLLMLingua 启示，0080 排序精化候选③）。

论文核心组件（消融贡献最大，-35 分）：问题感知粗粒度选择 r_k =
问题在文档条件下的（负）困惑度 ∝ 条件点互信息。本 POC 离线只读回答两个
登记在案的问题（OPEN-DECISIONS 2026-11-13）：

1. **词面近似版的增量**：词面 r_k 代理（问题词 ∩ 块词 的加权重叠）与现
   hybrid 排序的秩相关——预期高（现排序本就是 BM25 词面），如实验证
   「词面版无增量」的登记判断；
2. **向量语义重排的增量**：查询编码（bge，带指令前缀）与**已预计算的**
   块向量（kb/vec_index，零额外编码成本）余弦重排 context_hits 14 块——
   答案块（含全部/最多关键词组的块）位次移动统计：9+ 补位区 → 1-8 主区
   的提升数、反向下降数，重点核对 SAF-08（氧气 19.5% 块 rank-11）。

口径与诚实约束：
- 答案块识别 = 上下文内命中关键词组数最多的块（run_eval hit_groups 同源），
  平局取位次靠前——是近似，不代表金标；
- 弱命中题（改写路径）不模拟 LLM 改写，特征按原问题路径（与段计数台账
  同口径，弱命中题单列）；
- 本 POC 不动主链路代码；结论只进 OPEN-DECISIONS。

用法：.venv/Scripts/python.exe tools/poc_rk_rerank.py [--out 报告.md]
"""
import argparse
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

EVAL_SET = os.path.join(BASE, "docs", "eval", "eval_set_v2.json")


def norm(s):
    return re.sub(r"\s+", "", s or "")


def hit_groups(text, groups):
    t = norm(text)
    return sum(1 for g in groups if any(norm(w) in t for w in g))


def word_rk(question, text, q_terms):
    """词面 r_k 代理：问题实词在块文本中的出现计数（去停用词后的词面重叠）。"""
    t = text or ""
    return sum(1 for w in q_terms if w in t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from app import config, llm, retrieval, vector_search

    with open(EVAL_SET, encoding="utf-8") as f:
        questions = [q for q in json.load(f)["questions"] if q["type"] == "fact"]

    assert vector_search.available(), "向量索引不可用，POC 无法进行"
    ids = vector_search._state["ids"]
    vecs = vector_search._state["vecs"]
    id2row = {cid: i for i, cid in enumerate(ids)}

    # 弱命中题单列（与段计数台账同口径）
    weak = set()
    rows_out = []
    t_embeds = []
    promoted, demoted, unchanged = [], [], []
    not_in_ctx = []
    for q in questions:
        hits, top_cov = retrieval.hybrid_search(q["question"], config.RECALL_WINDOW)
        if (not hits) or top_cov < config.REWRITE_MIN_COVERAGE:
            weak.add(q["id"])
        primary = hits[:config.RETRIEVAL_TOP_K]
        pd = {h["doc_id"] for h in primary}
        supp = [h for h in hits[config.RETRIEVAL_TOP_K:]
                if h["doc_id"] in pd][:6]
        ctx = primary + supp
        if not ctx:
            not_in_ctx.append((q["id"], None, None))
            continue

        # 答案块：命中关键词组最多者（近似金标）
        best_i, best_g = 0, -1
        for i, h in enumerate(ctx):
            g = hit_groups(h["text"], q.get("key_points", []))
            if g > best_g:
                best_i, best_g = i, g
        cur_rank = best_i + 1

        # 词面 r_k 代理
        q_terms = [w for w in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", q["question"])
                   if len(w) >= 2][:20]

        # 向量重排：查询编码 + 预计算块向量余弦
        t0 = time.time()
        qv = vector_search._state["enc"].encode(
            vector_search.QUERY_PREFIX + q["question"])
        t_embeds.append((time.time() - t0) * 1000)
        sims = []
        for h in ctx:
            r_ = id2row.get(h["chunk_id"])
            sims.append(float(vecs[r_] @ qv) if r_ is not None else -1.0)
        vec_rank = sorted(range(len(ctx)), key=lambda i: -sims[i]).index(best_i) + 1
        wrk = [word_rk(q["question"], h["text"], q_terms) for h in ctx]
        wrk_rank = sorted(range(len(ctx)), key=lambda i: -wrk[i]).index(best_i) + 1

        rows_out.append({"id": q["id"], "cur": cur_rank, "vec": vec_rank,
                         "wrk": wrk_rank, "g": best_g})
        if vec_rank <= 8 and cur_rank >= 9:
            promoted.append(q["id"])
        elif vec_rank >= 9 and cur_rank <= 8:
            demoted.append(q["id"])
        else:
            unchanged.append(q["id"])

    # 秩相关（词面 r_k / 向量重排 vs 当前排序）——答案块位次视角
    def spearman(xs, ys):
        n = len(xs)
        rx = {v: i for i, v in enumerate(sorted(range(n), key=lambda i: xs[i]))}
        ry = {v: i for i, v in enumerate(sorted(range(n), key=lambda i: ys[i]))}
        import statistics
        if n < 3:
            return 0.0
        dx = [rx[i] for i in range(n)]
        dy = [ry[i] for i in range(n)]
        mx, my = statistics.mean(dx), statistics.mean(dy)
        num = sum((a - mx) * (b - my) for a, b in zip(dx, dy))
        den = (sum((a - mx) ** 2 for a in dx) * sum((b - my) ** 2 for b in dy)) ** 0.5
        return num / den if den else 0.0

    sr_wrk = spearman([r["cur"] for r in rows_out], [r["wrk"] for r in rows_out])
    sr_vec = spearman([r["cur"] for r in rows_out], [r["vec"] for r in rows_out])
    t_med = sorted(t_embeds)[len(t_embeds) // 2] if t_embeds else 0

    lines = ["# r_k 重排离线 POC（自动生成）", ""]
    lines.append(f"> 生成：{time.strftime('%Y-%m-%d %H:%M')} · fact 题 {len(rows_out)} 道"
                 f"（弱命中 {len(weak)} 道按原问题路径，单列口径）")
    lines.append("> 答案块=上下文内命中关键词组最多的块（近似金标）；"
                 "向量重排用预计算块向量，仅查询侧一次编码")
    lines.append("")
    lines.append("## 一、答案块位次移动（向量余弦重排 vs 当前排序）")
    lines.append("")
    lines.append(f"- 9+ 补位区 → 1-8 主区提升：**{len(promoted)}** 题"
                 + (f"（{','.join(promoted)}）" if promoted else ""))
    lines.append(f"- 1-8 主区 → 9+ 下降：**{len(demoted)}** 题"
                 + (f"（{','.join(demoted)}）" if demoted else ""))
    lines.append(f"- 位次不变/同区：{len(unchanged)} 题")
    lines.append(f"- 答案块不在上下文（重排无法救）：{len(not_in_ctx)} 题"
                 + (f"（{','.join(i for i, _, _ in not_in_ctx)}）" if not_in_ctx else ""))
    lines.append("")
    lines.append("## 二、秩相关（答案块位次视角）")
    lines.append("")
    lines.append(f"- 词面 r_k 代理 vs 当前排序：Spearman **{sr_wrk:.2f}**"
                 "（现排序即 BM25 词面，预期高相关 → 词面版无增量验证）")
    lines.append(f"- 向量语义重排 vs 当前排序：Spearman **{sr_vec:.2f}**")
    lines.append("")
    lines.append("## 三、延迟可行性")
    lines.append("")
    lines.append(f"- 查询侧单次编码中位耗时 **{t_med:.0f} ms**（CPU ONNX int8，"
                 "块向量零成本——已预计算）。上线形态 = 仅在装配后对 14 块做"
                 "一次余弦重排，无新增模型加载。")
    lines.append("")
    lines.append("## 四、逐题明细（当前 9+ 位或重排后 9+ 位的题）")
    lines.append("")
    lines.append("| 题 | 当前位次 | 向量重排后 | 词面代理 | 关键词组命中 |")
    lines.append("|---|---|---|---|---|")
    for r in rows_out:
        if r["cur"] >= 9 or r["vec"] >= 9:
            lines.append(f"| {r['id']} | {r['cur']} | {r['vec']} | {r['wrk']} | {r['g']} |")
    lines.append("")
    lines.append(f"弱命中题（{len(weak)}）：{', '.join(sorted(weak))}")
    lines.append("")

    report = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"已写入 {args.out}")
    print(report)


if __name__ == "__main__":
    main()
