# -*- coding: utf-8 -*-
"""句级支持性评测（2026-11-15，ALCE 启示落地，P4 期候选⑤）。

ALCE（EMNLP 2023）citation recall/precision 的规则轻量版（不引 NLI）：
对历史评测结果按句拆分答案，用**题面关键词组**做句↔所引块绑定判定——

- **句级支持率**（rule citation recall，组级）：关键词组 g 出现在句 s 中时，
  s 需带引用 [n] 且第 n 块也含 g——「该句关键词组 ⊆ 所引块」；
- **引用相关率**（rule citation precision，引用级）：带组句上的每条引用，
  其块含该句至少一个关键词组（ALCE「无关引用」的规则近似）；
- **无引用组句数**：含关键词组却无 [n] 的句子（ALCE「语句缺引用」结构缺
  陷的直接度量）。

诚实边界（报告头声明）：
- 规则版判据是词面重合（关键词组同现），不是 NLI 蕴含——**更严口径的
  必要不充分条件**；测不了改写式支持（与 62 题规则断言同一取舍）；
- 上下文按**原问题路径**确定性重建（弱命中题的改写合并不模拟，单列
  不计入统计）；引用编号 [n] 与重建块序一一对应（强命中题即服务端实况）；
- 无组句上的引用不判定（无金标锚点），单列统计。

用法：
    .venv/Scripts/python.exe tools/cite_precision.py --runs ctx-24,ctx-31 [--out 报告.md]
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.feedback import split_sentences  # noqa: E402  # 与在线台账同源切分

EVAL_SET = os.path.join(BASE, "docs", "eval", "eval_set_v2.json")
RESULTS_DIR = os.path.join(BASE, "docs", "eval", "results")
_CITE_RE = re.compile(r"\[(\d{1,3})\]")


def norm(s):
    return re.sub(r"\s+", "", s or "")


def groups_in(text, groups):
    """题面关键词组在 text 中命中的组下标列表。"""
    t = norm(text)
    return [i for i, g in enumerate(groups)
            if any(norm(w) in t for w in g)]


def _group_in_block(g, block):
    b = norm(block)
    return any(norm(w) in b for w in g)


def sentence_support(answer: str, groups, blocks) -> dict:
    """句级支持性（纯函数）：返回计数与逐句明细。"""
    sents = split_sentences(answer)
    tot_occ = sup_occ = 0            # (句, 组) 对：总数 / 被所引块支持数
    judge_cites = rel_cites = 0      # 带组句上的引用：可判数 / 相关数
    ung_cites = 0                    # 无组句上的引用（不判定）
    uncited_g_sents = 0              # 含组却无引用的句子
    detail = []
    for s in sents:
        ns = [int(m) for m in _CITE_RE.findall(s)]
        valid = [n for n in ns if 1 <= n <= len(blocks)]
        gs = groups_in(s, groups)
        d = {"s": s[:60], "cites": ns, "groups": gs, "sup": []}
        for gi in gs:
            tot_occ += 1
            ok = any(_group_in_block(groups[gi], blocks[n - 1]) for n in valid)
            if ok:
                sup_occ += 1
            d["sup"].append(ok)
        if gs:
            for n in valid:
                judge_cites += 1
                if any(_group_in_block(groups[gi], blocks[n - 1]) for gi in gs):
                    rel_cites += 1
            if not valid:
                uncited_g_sents += 1
        else:
            ung_cites += len(valid)
        detail.append(d)
    return {"tot_occ": tot_occ, "sup_occ": sup_occ,
            "judge_cites": judge_cites, "rel_cites": rel_cites,
            "ung_cites": ung_cites, "uncited_g_sents": uncited_g_sents,
            "n_sent": len(sents), "detail": detail}


def load_run(tag):
    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, f"eval_{tag}_*.json")))
    if not paths:
        raise SystemExit(f"找不到 eval_{tag}_*.json")
    with open(paths[-1], encoding="utf-8") as f:
        return os.path.basename(paths[-1]), json.load(f)


def main():
    # stdout 包装只在 CLI 入口做（importlib 加载本模块做单测时不碰流）
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from app import config, retrieval

    with open(EVAL_SET, encoding="utf-8") as f:
        qs = {q["id"]: q for q in json.load(f)["questions"]
              if q["type"] == "fact"}

    lines = ["# 句级支持性评测（ALCE citation precision 规则轻量版，自动生成）", ""]
    lines.append(f"> 生成：{time.strftime('%Y-%m-%d %H:%M')} · 判据 = 关键词组在"
                 "句与其所引块中同现（词面，非 NLI）；上下文按原问题路径重建，"
                 "弱命中题不计入；无组句引用不判定（口径详见工具头注释）。")
    lines.append("")
    lines.append("| run | fact 题 | (句,组)对 | 句级支持率 | 可判引用 | 引用相关率 | 无引用组句 | 无组句引用 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    all_detail = []
    weak_total = set()
    for tag in args.runs.split(","):
        fname, data = load_run(tag.strip())
        agg = {k: 0 for k in ("tot_occ", "sup_occ", "judge_cites",
                              "rel_cites", "ung_cites", "uncited_g_sents")}
        n_q = 0
        for r in data.get("rows", []):
            if r.get("type") != "fact" or not r.get("answer"):
                continue
            q = qs.get(r["id"])
            if not q:
                continue
            hits, top_cov = retrieval.hybrid_search(
                q["question"], config.RECALL_WINDOW)
            if (not hits) or top_cov < config.REWRITE_MIN_COVERAGE:
                weak_total.add(r["id"])
                continue  # 原问题路径近似不适用，不计入
            primary = hits[:config.RETRIEVAL_TOP_K]
            pd = {h["doc_id"] for h in primary}
            supp = [h for h in hits[config.RETRIEVAL_TOP_K:]
                    if h["doc_id"] in pd][:6]
            blocks = [h["text"] for h in (primary + supp)]
            if not blocks:
                continue
            res = sentence_support(r["answer"], q.get("key_points", []), blocks)
            for k in agg:
                agg[k] += res[k]
            n_q += 1
            sup_rate = res["sup_occ"] / res["tot_occ"] if res["tot_occ"] else 1
            if res["tot_occ"] and (sup_rate < 0.999 or res["uncited_g_sents"]):
                all_detail.append((fname, r["id"], res))
        sr = f"{agg['sup_occ']}/{agg['tot_occ']}" if agg["tot_occ"] else "-"
        cr = f"{agg['rel_cites']}/{agg['judge_cites']}" if agg["judge_cites"] else "-"
        lines.append(f"| {fname} | {n_q} | {agg['tot_occ']} | {sr} | "
                     f"{agg['judge_cites']} | {cr} | {agg['uncited_g_sents']} | "
                     f"{agg['ung_cites']} |")
    lines.append("")
    lines.append(f"弱命中题（改写路径，不计入）：{len(weak_total)} 道"
                 + (f"（{', '.join(sorted(weak_total))}）" if weak_total else ""))
    lines.append("")
    lines.append("## 逐题明细（句级支持率未满或存在无引用组句）")
    lines.append("")
    if all_detail:
        lines.append("| run | 题 | (句,组) | 支持 | 可判引用 | 相关 | 无引用组句 |")
        lines.append("|---|---|---|---|---|---|---|")
        for fname, qid, res in all_detail:
            lines.append(f"| {fname} | {qid} | {res['tot_occ']} | {res['sup_occ']} | "
                         f"{res['judge_cites']} | {res['rel_cites']} | "
                         f"{res['uncited_g_sents']} |")
        lines.append("")
        lines.append("**判读提示**：支持率 < 满分的 (句,组) 对 = 关键事实句所引块"
                     "不含该词组——ALCE 意义上的引用支持性缺口候选；无引用组句 = "
                     "结构缺陷（契约要求事实句带 [n]）。逐句定位用工具的 detail 输出。")
    else:
        lines.append("（无——所有计入题的句级支持率均为满分）")

    report = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"已写入 {args.out}")
    print(report)


if __name__ == "__main__":
    main()
