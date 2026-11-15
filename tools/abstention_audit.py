# -*- coding: utf-8 -*-
"""弃答路径审计（2026-11-15，A-MEM 启示落地）。

A-MEM（NeurIPS 2025）在 LOCOMO adversarial（识别不可回答）类上反低于
LoCoMo 基线：GPT-4o-mini F1 50.03 vs 69.23——**更强的记忆组织反而更
倾向于「挤出答案」而非弃答**。本工具把该警示变成项目的可机判守卫：

1. 历史 62 题结果：拒答/边界组（本应弃答）按证据强度（ctx_cov）分桶，
   核心检查 = **硬答数**（本应弃答却给出无拒答标记的答案）。
2. fact 组按证据桶统计弃答率/通过率（对照）。
3. 在线台账（ADR-011）按 top_cov 分桶统计拒答标记与答案长度（样本量
   如实标注）。

回归守卫价值：未来若有人调整 MIN_COVERAGE 兜底判据或提示词，本工具
能立刻发现「本应弃答的题开始硬答」——诚实拒答是一等公民，不能被
检索/记忆/上下文增强挤掉。

口径诚实声明：
- ctx_cov = sources 全文命中关键词组占比（run_eval 口径）；
  coverage = 台账里的 top_cov（检索最高分，兜底判据本身）——两者不同，
  分表报告，不混算；
- 弃答判定 = backend=='no_answer' 或答案含拒答标记词表
  （与 app/feedback.py 同源），词表面向拒答模板，非语义判断；
- 在线台账为冒烟/POC 流量（非生产分布），只作补充观察。

用法：
    .venv/Scripts/python.exe tools/abstention_audit.py --runs ctx-24,ctx-31 [--ledger] [--out 报告.md]
"""
import argparse
import glob
import io
import json
import os
import statistics
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.feedback import REFUSAL_MARKERS, classify_answer  # noqa: E402

RESULTS_DIR = os.path.join(BASE, "docs", "eval", "results")
LEDGER_PATH = os.path.join(BASE, "data", "feedback_ledger.jsonl")


def is_abstained(answer: str, backend: str | None = None) -> bool:
    """弃答判定（纯函数）：兜底路径或答案含拒答标记词表。"""
    if backend == "no_answer":
        return True
    return any(m in (answer or "") for m in REFUSAL_MARKERS)


def evidence_bucket(ctx_cov: float, cut: float = 0.5) -> str:
    """证据强度分桶（纯函数）：high = 上下文覆盖 ≥ cut。"""
    return "high" if (ctx_cov or 0) >= cut else "low"


def classify_edge_row(row: dict) -> str:
    """本应弃答题的四分类（纯函数）：abstained / boundary_ack / hard /
    no_response。

    boundary_ack 单列是刻意的：ctx-24 EDGE-05 的真实答案「知识库中可依据
    的条款只涉及…未列出具体技术指标数值」并引用佐证不足——是**合理的
    边界说明**（缺席承认措辞，与 app.feedback.ABSENCE_ACK / 错误复制率
    copy_review 桶同源），不是 A-MEM 式「挤出答案」。若把它算硬答，
    就是机械指标伪造告警（项目里第 2 次遇到这题，防误报纪律）。
    no_response 同理：POC 请求故障不算弃答也不算硬答。
    """
    ans = (row.get("answer") or "").strip()
    backend = row.get("backend")
    if backend == "no_answer":
        return "abstained"
    if not ans:
        return "no_response"
    cls = classify_answer(ans)
    if cls["refusal"]:
        return "abstained"
    if cls["ack"]:
        return "boundary_ack"
    return "hard"


def load_run(tag):
    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, f"eval_{tag}_*.json")))
    if not paths:
        raise SystemExit(f"找不到 eval_{tag}_*.json")
    with open(paths[-1], encoding="utf-8") as f:
        return os.path.basename(paths[-1]), json.load(f)


def main():
    # stdout 包装只在 CLI 入口做（importlib 加载做单测时不碰流）
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--ledger", action="store_true")
    ap.add_argument("--cut", type=float, default=0.5)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    lines = ["# 弃答路径审计（A-MEM 警示的可机判守卫，自动生成）", ""]
    lines.append(f"> 生成：{time.strftime('%Y-%m-%d %H:%M')} · 证据桶 cut={args.cut} "
                 "（ctx_cov=关键词覆盖率；台账 coverage=top_cov，两者不混算）")
    lines.append("> A-MEM 对照：LOCOMO adversarial（识别不可答）F1 50.03 低于"
                 "基线 69.23——更强组织更会「挤出答案」")
    lines.append("")
    lines.append("## 一、本应弃答组（refusal/boundary）：硬答数是核心告警")
    lines.append("")
    lines.append("| run | 题数 | ctx_cov 均值 | 弃答数 | 合理边界说明 | **硬答数** | 无响应 | 硬答题 ID |")
    lines.append("|---|---|---|---|---|---|---|---|")
    hard_total = 0
    for tag in args.runs.split(","):
        fname, data = load_run(tag.strip())
        edges = [r for r in data.get("rows", [])
                 if r.get("type") in ("refusal", "boundary")]
        groups = {"abstained": [], "boundary_ack": [], "hard": [],
                  "no_response": []}
        for r in edges:
            groups[classify_edge_row(r)].append(r)
        hard_total += len(groups["hard"])
        mean_cov = (statistics.mean([r.get("ctx_cov", 0) for r in edges])
                    if edges else 0)
        lines.append(f"| {fname} | {len(edges)} | {mean_cov:.2f} | "
                     f"{len(groups['abstained'])}/{len(edges)} | "
                     f"{len(groups['boundary_ack'])} | "
                     f"**{len(groups['hard'])}** | {len(groups['no_response'])} | "
                     f"{','.join(r['id'] for r in groups['hard']) or '-'} |")
    lines.append("")
    lines.append("## 二、fact 组按证据强度分桶（对照）")
    lines.append("")
    lines.append("| run | 桶 | 题数 | 弃答率 | 通过率 |")
    lines.append("|---|---|---|---|---|")
    for tag in args.runs.split(","):
        fname, data = load_run(tag.strip())
        facts = [r for r in data.get("rows", []) if r.get("type") == "fact"]
        for b in ("high", "low"):
            grp = [r for r in facts
                   if evidence_bucket(r.get("ctx_cov", 0), args.cut) == b]
            na = sum(1 for r in grp
                     if is_abstained(r.get("answer"), r.get("backend")))
            nok = sum(1 for r in grp if r.get("ok"))
            lines.append(f"| {fname} | {b} (ctx_cov "
                         f"{'≥' if b == 'high' else '<'}{args.cut}) | "
                         f"{len(grp)} | {na}/{len(grp)} | {nok}/{len(grp)} |")
    lines.append("")

    if args.ledger and os.path.exists(LEDGER_PATH):
        rows = []
        with open(LEDGER_PATH, encoding="utf-8") as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
        lines.append("## 三、在线台账（top_cov 分桶，样本非生产分布）")
        lines.append("")
        lines.append("| 桶 | 行数 | 拒答标记 | answer_chars 中位 |")
        lines.append("|---|---|---|---|")
        for b in ("high", "low"):
            grp = [r for r in rows
                   if evidence_bucket(r.get("coverage") or 0, args.cut) == b]
            nr = sum(1 for r in grp if r.get("refusal") or
                     r.get("backend") == "no_answer")
            med = (statistics.median([r.get("answer_chars", 0) for r in grp])
                   if grp else 0)
            lines.append(f"| {b} (top_cov "
                         f"{'≥' if b == 'high' else '<'}{args.cut}) | {len(grp)} | "
                         f"{nr}/{len(grp)} | {med:.0f} |")
        lines.append("")
    elif args.ledger:
        lines.append("## 三、在线台账")
        lines.append("")
        lines.append("（data/feedback_ledger.jsonl 不存在）")
        lines.append("")

    lines.append("## 结论")
    lines.append("")
    if hard_total == 0:
        lines.append("**A-MEM 风险路径未复现**：各 run 本应弃答题的硬答数均为 0"
                     "（弃答 + 合理边界说明覆盖全部）。结构上由 MIN_COVERAGE "
                     "兜底判据在生成前切断——证据强度无法把「未找到」挤成答案；"
                     "「合理边界说明」是承认缺席并引用佐证的合规形态（EDGE-05 "
                     "case，与错误复制率 copy_review 桶同源）。该审计转为回归"
                     "守卫：未来任何兜底判据/提示词改动后若出现硬答，即触发告警。")
    else:
        lines.append(f"**告警**：本应弃答题出现 {hard_total} 次硬答——"
                     "疑似证据挤出弃答（A-MEM 方向），需逐题人工复核答案头，"
                     "并检查 MIN_COVERAGE / 拒答契约是否被改动。")
    lines.append("")
    lines.append("边界：弃答用词表判定（非语义）；ctx_cov 为覆盖率的关键词"
                 "口径，弱命中题的改写合并不模拟；在线台账为冒烟/POC 流量。")

    report = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"已写入 {args.out}")
    print(report)


if __name__ == "__main__":
    main()
