# -*- coding: utf-8 -*-
"""错误复制率与拒答形态分析（2026-11-13，RECOMP 启示落地，ADR-011 增补）。

RECOMP（ICLR 2024）核心警示：证据不含答案时，完整 Top-5 上下文让模型
81% 仍从证据复制答案。本工具对历史评测结果做同维度测量：

- **copy_rate**（拒答/边界组）：本应答「未找到/未收录」却仍带 [n] 引用
  给出断言的比例——错误复制的直接度量；
- **refusal_with_cite**：拒答但仍带引用的比例（拒答形态观察——GOV-06
  跨日漂移正是拒答形态变化，此指标让漂移自动显形）；
- **拒答形态明细**：任何类型题中含拒答标记的答案，列 cited/长度，
  供「裸拒答 vs 带说明拒答」的分布对比。

口径：app/feedback.py classify_answer（与 run_eval.py 新增 copy_rate 同源）。
对正常 fact 题不做 copy 判定（cited∧¬refusal 是正常作答）。

用法：
    .venv/Scripts/python.exe tools/copy_rate.py --runs ctx-24,ctx-31 [--out 报告.md]
"""
import argparse
import glob
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.feedback import classify_answer  # noqa: E402

RESULTS_DIR = os.path.join(BASE, "docs", "eval", "results")


def load(tag):
    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, f"eval_{tag}_*.json")))
    if not paths:
        raise SystemExit(f"找不到 eval_{tag}_*.json")
    with open(paths[-1], encoding="utf-8") as f:
        return os.path.basename(paths[-1]), json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="逗号分隔的 tag")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    lines = ["# 错误复制率与拒答形态分析（自动生成）", ""]
    lines.append("> 口径：app/feedback.py classify_answer；copy 仅在拒答/边界组解读；"
                 "RECOMP 对照：证据无关时完整 Top-5 错误复制率 81%，选择性增强后 39%。")
    lines.append("> **copy_review**：带引用但含缺席承认措辞（未列出/未包含…）——"
                 "合理佐证行为，需人工复核不计入 copy（EDGE-05 误报教训，2026-11-13）。")
    lines.append("")
    lines.append("| run | 拒答/边界题数 | copy_rate | copy_review | refusal_with_cite |")
    lines.append("|---|---|---|---|---|")
    all_refusal_forms = []
    copy_details = []
    for tag in args.runs.split(","):
        fname, data = load(tag.strip())
        edges = [r for r in data.get("rows", []) if r.get("type") != "fact"]
        copy_n, rc_n, rv_n = 0, 0, 0
        for r in edges:
            cls = classify_answer(r.get("answer") or "")
            copy_n += int(cls["copy"])
            rc_n += int(cls["refusal"] and cls["cited"])
            rv_n += int(cls["review"])
            if cls["copy"] or cls["review"]:
                copy_details.append((fname, r["id"], cls["copy"],
                                     (r.get("answer") or "")[:100]))
        lines.append(f"| {fname} | {len(edges)} | {copy_n}/{len(edges)} | "
                     f"{rv_n}/{len(edges)} | {rc_n}/{len(edges)} |")
        for r in data.get("rows", []):
            a = r.get("answer") or ""
            cls = classify_answer(a)
            if cls["refusal"]:
                all_refusal_forms.append((fname, r["id"], r.get("type"),
                                          cls["cited"], len(a)))
    lines.append("")
    lines.append("## copy / review 命中明细")
    lines.append("")
    if copy_details:
        lines.append("| run | 题 | 桶 | 答案头 |")
        lines.append("|---|---|---|---|")
        for fname, qid, is_copy, head in copy_details:
            lines.append(f"| {fname} | {qid} | {'copy（需修）' if is_copy else 'review（合理佐证？）'} | "
                         f"{head.replace(chr(10), ' ')} |")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 拒答形态明细（含拒答标记的全部答案）")
    lines.append("")
    lines.append("| run | 题 | 类型 | 带引用 | 答案长度 |")
    lines.append("|---|---|---|---|---|")
    for fname, qid, typ, cited, n in all_refusal_forms:
        lines.append(f"| {fname} | {qid} | {typ} | {'Y' if cited else 'N'} | {n} |")
    lines.append("")
    lines.append("**解读提示**：同一题跨 run 的「带引用/长度」变化即拒答形态漂移"
                 "（GOV-06：带说明长拒答 ↔ 裸拒答 36 字）；copy_rate>0 需逐题人工"
                 "复核复制了哪段无关上下文。")

    report = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"已写入 {args.out}")
    print(report)


if __name__ == "__main__":
    main()
