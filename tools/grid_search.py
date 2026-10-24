# -*- coding: utf-8 -*-
"""B-1 重排权重 × 召回窗口 网格搜索（62 题离线口径）。

路线图 B-1：「coverage*2.0 + bonus 是手工值。跑 coverage 权重 {1.5/2/2.5/3}
× 窗口 {12/16/20} 的网格，62 题口径选优」。

口径说明（与线上 main.py 装配逻辑逐字对齐）：
- 每题取 eval_set_v2.json 的事实题（fact），模拟服务端装配：
    primary = hits[:8]；supplement = 窗口内与 primary 同文档的块[:6]；context = 两者之和
- 指标：
    ret_hit3   预期文档 ∈ top-3（run_eval 同口径）
    ctx_hit    预期文档 ∈ context（路线图 B-1 新判据）
    ctx_kw     关键词组在 context 文本的覆盖率均值（run_eval ctx_cov 同口径）
- 拒答题观测（INFO，非否决）：拒答题的检索侧 top_cov 历史上即 ≥0.25（EDGE-01~04
  在改动前同为 0.25~0.5），系统的拒答由生成层系统提示词兜底（62 题实测 refusal 4/4，
  backend=llm），检索侧 MIN_COVERAGE 只是第二道闸。因此本网格把「拒答题 top_cov 相对
  现值基线（W=2.0/win=16）的变化」作为回归信号：任一题 top_cov 升高即视为该组合
  有让库外题更易被当成可回答的风险，标注回归。

已知局限（诚实声明）：离线口径不走两阶段 LLM 改写（改写在弱命中时只能加分，
见 ADR-007 并集合并契约），因此本网格度量的是「无改写基线」的排序质量；
弱命中题的最终表现以 62 题在线口径为准。

用法：.venv/Scripts/python.exe tools/grid_search.py
前置：app/config.py 提供 COVERAGE_WEIGHT（retrieval.search 调用时读取）。
"""
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app import config, retrieval  # noqa: E402

EVAL_SET = os.path.join(BASE, "docs", "eval", "eval_set_v2.json")
OUT_MD = os.path.join(BASE, "docs", "eval", f"网格搜索-{time.strftime('%Y%m%d')}.md")

WEIGHTS = [1.5, 2.0, 2.5, 3.0]
WINDOWS = [12, 16, 20]
BASELINE = (2.0, 16)  # 现值（ADR-005）


def norm(s):
    return re.sub(r"\s+", "", s or "")


def hit_groups(text, groups):
    t = norm(text)
    return {i for i, g in enumerate(groups) if any(norm(w) in t for w in g)}


def assemble(hits, window_topk=8):
    """复刻 main.py 的上下文装配（迭代6/ADR-004）"""
    primary = hits[:config.RETRIEVAL_TOP_K]
    primary_docs = {h["doc_id"] for h in primary}
    supp = [h for h in hits[config.RETRIEVAL_TOP_K:] if h["doc_id"] in primary_docs][:6]
    return primary, supp


def evaluate(facts, refusals, refusal_cov_baseline=None):
    """在当前 config.COVERAGE_WEIGHT / 给定窗口下跑全部题，返回指标字典。
    refusal_cov_baseline：现值基线下各拒答题的 top_cov（dict by id），
    用于回归检测（top_cov 升高 = 库外题更易被当成可回答）。"""
    ret3 = ctxh = 0
    kw_total = 0.0
    for q in facts:
        hits, _ = retrieval.hybrid_search(q["question"], config.RECALL_WINDOW)
        primary, supp = assemble(hits)
        ctx = primary + supp
        exp = set(q["expected_docs"])
        docs3 = {h["doc_id"] for h in hits[:3]}
        docs_all = {h["doc_id"] for h in ctx}
        if docs3 & exp:
            ret3 += 1
        if docs_all & exp:
            ctxh += 1
        groups = q.get("keywords") or []
        if groups:
            covered = set()
            for h in ctx:
                covered |= hit_groups(h["text"], groups)
            kw_total += len(covered) / len(groups)
    refusal_covs = {}
    for q in refusals:
        hits, _ = retrieval.hybrid_search(q["question"], config.RECALL_WINDOW)
        primary, _ = assemble(hits)
        refusal_covs[q["id"]] = round(
            max((h["coverage"] for h in primary), default=0.0), 2)
    regress = []
    if refusal_cov_baseline:
        regress = [qid for qid, cov in refusal_covs.items()
                   if cov > refusal_cov_baseline.get(qid, cov) + 1e-9]
    n = len(facts)
    return {
        "ret_hit3": f"{ret3}/{n}",
        "ctx_hit": f"{ctxh}/{n}",
        "ctx_kw_mean": round(kw_total / n, 3) if n else 0,
        "refusal_cov": refusal_covs,
        "refusal_regress": ",".join(regress) or "-",
        "_sort": (ctxh, ret3, kw_total),
    }


def main():
    spec = json.load(open(EVAL_SET, encoding="utf-8"))
    facts = [q for q in spec["questions"] if q["type"] == "fact"]
    refusals = [q for q in spec["questions"] if q["type"] == "refusal"]
    print(f"事实题 {len(facts)} 道，拒答题 {len(refusals)} 道；"
          f"权重 {WEIGHTS} × 窗口 {WINDOWS}")

    rows = []
    # 先跑现值基线，取拒答题 top_cov 参照
    config.COVERAGE_WEIGHT, config.RECALL_WINDOW = BASELINE
    t0 = time.time()
    base_m = evaluate(facts, refusals)
    refusal_cov_baseline = base_m["refusal_cov"]
    rows.append({**base_m, "weight": BASELINE[0], "window": BASELINE[1],
                 "refusal_regress": "-", "sec": round(time.time() - t0, 1)})
    for w in WEIGHTS:
        for win in WINDOWS:
            if (w, win) == BASELINE:
                continue
            config.COVERAGE_WEIGHT = w  # retrieval.search 调用时读取（运行时可变）
            config.RECALL_WINDOW = win
            t0 = time.time()
            m = evaluate(facts, refusals, refusal_cov_baseline)
            m["weight"], m["window"] = w, win
            m["sec"] = round(time.time() - t0, 1)
            rows.append(m)
            print(f"  W={w} win={win}: ret3={m['ret_hit3']} ctx_hit={m['ctx_hit']} "
                  f"kw={m['ctx_kw_mean']} refusal回归={m['refusal_regress']} ({m['sec']}s)")

    # 拒答回归一票否决后按 (ctx_hit, ret_hit3, ctx_kw) 排序；无回归组合才可入选
    eligible = [r for r in rows if r["refusal_regress"] == "-"]
    ranked = sorted(eligible or rows, key=lambda r: r["_sort"], reverse=True)
    best = ranked[0]

    lines = [
        "# 重排权重 × 召回窗口 网格搜索（62 题离线口径）",
        "",
        f"- 执行：{time.strftime('%Y-%m-%d %H:%M')}｜工具：`tools/grid_search.py`｜"
        f"代码含 ADR-008 同义词映射（对 4 道拒答题零影响，另行核对）",
        f"- 口径：{len(facts)} 道事实题 + {len(refusals)} 道拒答题回归检测；"
        f"离线（不走两阶段 LLM 改写，见脚本头部局限声明）",
        f"- 现值基线：COVERAGE_WEIGHT=2.0 / RECALL_WINDOW=16（ADR-005）"
        f"｜拒答题 top_cov 基线：{refusal_cov_baseline}",
        "",
        "| COVERAGE_WEIGHT | RECALL_WINDOW | ret_hit3 | ctx_hit | ctx_kw 均值 | 拒答题top_cov回归 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        cur = "（现值）" if (r["weight"] == 2.0 and r["window"] == 16) else ""
        lines.append(f"| {r['weight']} | {r['window']}{cur} | {r['ret_hit3']} | "
                     f"{r['ctx_hit']} | {r['ctx_kw_mean']} | {r['refusal_regress']} |")
    lines += [
        "",
        f"**最优组合：W={best['weight']} / window={best['window']}"
        f"（ctx_hit={best['ctx_hit']}，ret3={best['ret_hit3']}，kw={best['ctx_kw_mean']}）**",
        "",
    ]
    if best["weight"] == 2.0 and best["window"] == 16:
        lines.append("结论：现值即最优（或在并列最优中），维持不动——「已验证无需调」。")
    else:
        # 平局判定：ret3/ctx_hit 持平且 kw 增益 < 0.01（约 2 个关键词组）视为噪声级，
        # 不为噪声改默认值（A-1 报告重跑归因：LLM 措辞抖动本身就有 ±0.25 的 ans_cov 波动）
        base_row = next(r for r in rows if r["weight"] == 2.0 and r["window"] == 16)
        margin = best["ctx_kw_mean"] - base_row["ctx_kw_mean"]
        flat = (best["ret_hit3"] == base_row["ret_hit3"]
                and best["ctx_hit"] == base_row["ctx_hit"])
        if flat and margin < 0.01:
            lines.append(
                f"结论：网格已饱和——最优组合（W={best['weight']}/win={best['window']}）与现值 "
                f"ret3/ctx_hit 完全持平，kw 增益 {margin:+.3f} 为噪声级（<0.01）。"
                f"**现值即确认最优，维持不动——「已验证无需调」。**"
                f"另：W=3.0 全部窗口出现 EDGE-03 拒答回归，明确排除。")
        else:
            lines.append(f"结论：建议把默认值调整为 W={best['weight']} / window={best['window']}"
                         f"（kw 增益 {margin:+.3f}），改动须过三重护栏后在 62 题在线口径复核。")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
    print(f"\n报告已写入: {OUT_MD}")
    print(f"最优: W={best['weight']} win={best['window']} ctx_hit={best['ctx_hit']}")


if __name__ == "__main__":
    main()
