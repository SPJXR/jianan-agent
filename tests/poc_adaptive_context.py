# -*- coding: utf-8 -*-
"""POC：按题自适应上下文装配（上下文改进计划第 2 期第一项）。

问题：基线（ctx-baseline 20261103）显示 cite_util_avg=0.25——54 题里 42 题
被引用块全部落在 top-8 主证据内，只有 12 题真正用到 9~14 位的同文档补位。
当前装配恒定 14 块，对 42 题是 75% 的噪音预算。

方法：本地复算每题 hybrid_search 的命中结构（coverage 分布），用基线 JSON
的真实被引位次（cite_pos）作为"需要真值"，模拟不同判据 + 不同补位上限，
选出「被引块零丢失 + 平均装配块数最小」的策略参数。

局限：线上弱命中题（C 组口语题）实际经 LLM 改写后并集合并（ADR-007），
本地单次检索排名与线上不同——本 POC 对这类题单独标注，判据只依赖
命中结构特征（对改写路径不敏感），最终以线上 62 题全量回归为准。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app import retrieval, config  # noqa: E402

BASELINE = os.path.join(BASE, "docs", "eval", "results", "eval_ctx-baseline_20261103.json")
EVAL_SET = os.path.join(BASE, "docs", "eval", "eval_set_v2.json")


def main():
    bl = json.load(open(BASELINE, encoding="utf-8"))
    cite_by_id = {r["id"]: r.get("cite_pos", []) for r in bl["rows"] if r["type"] == "fact"}
    spec = json.load(open(EVAL_SET, encoding="utf-8"))
    qs = [q for q in spec["questions"] if q["type"] == "fact" and q["id"] in cite_by_id]

    rows = []
    for q in qs:
        hits, top_cov = retrieval.hybrid_search(q["question"], config.RECALL_WINDOW)
        primary = hits[:config.RETRIEVAL_TOP_K]
        # 命中结构特征（装配前可得的信号）
        active_n = sum(1 for h in primary if h.get("coverage", 0) > 0)
        top3_cov = max((h.get("coverage", 0) for h in hits[:3]), default=0.0)
        cite_pos = cite_by_id[q["id"]]
        needed = max(cite_pos) if cite_pos else 0
        rows.append({
            "id": q["id"], "active_n": active_n, "top_cov": round(top_cov, 2),
            "top3_cov": round(top3_cov, 2), "needed": needed,
            "rewrite_path": top_cov < config.REWRITE_MIN_COVERAGE,
            "cite_pos": cite_pos,
        })

    n = len(rows)
    print(f"题数: {n}（其中线上走改写路径的弱命中题 {sum(r['rewrite_path'] for r in rows)} 道）")
    print(f"基线平均装配块数: 14.0（恒定）")

    # ---- 特征与 needed 的相关性速览 ----
    print("\n== active_n（top-8 内 coverage>0 块数）vs needed（被引最大位次）==")
    for k in range(1, 9):
        grp = [r for r in rows if r["active_n"] == k]
        if grp:
            need9 = sum(1 for r in grp if r["needed"] >= 9)
            print(f"  active_n={k}: {len(grp):2} 题，其中需要补位(needed>=9) {need9}")

    # ---- 策略模拟 ----
    # 策略形如 (active_n_low, active_n_high, supp_cap)：active_n 在 [low, high] 内给 supp_cap
    # 其余给 6（全补位）。目标是 needed>=9 的 12 题全部判为"全补位"。
    print("\n== 策略模拟（被引块保留率 / 平均装配块数）==")
    need9_ids = {r["id"] for r in rows if r["needed"] >= 9}
    best = []
    for low in range(1, 9):
        for cap in (0, 2, 3, 4):
            # 策略：active_n <= low 且 top_cov >= 0.5（强命中）→ 补位 cap；否则 6
            miss = []
            total_blocks = []
            for r in rows:
                strong = r["active_n"] <= low and r["top_cov"] >= 0.5
                supp_cap = cap if strong else 6
                window = 8 + supp_cap
                total_blocks.append(window)
                if r["needed"] > window:
                    miss.append(r["id"])
            avg = sum(total_blocks) / n
            ok = not (set(miss) & need9_ids) or not miss
            tag = "SAFE" if not miss else ("RISK:" + ",".join(miss[:3]))
            best.append((avg, miss, low, cap, tag))
            print(f"  active_n<={low} & topcov>=0.5 -> supp={cap}: 平均 {avg:.1f} 块, {tag}")

    safe = [b for b in best if not b[1]]
    if safe:
        safe.sort()
        avg, miss, low, cap, _ = safe[0]
        print(f"\n最优安全策略: active_n<={low} 且 top_cov>=0.5 → 补位 {cap} 条；"
              f"平均装配 {avg:.1f} 块（基线 14.0，降 {(1-avg/14)*100:.0f}%），被引块零丢失")


if __name__ == "__main__":
    main()
