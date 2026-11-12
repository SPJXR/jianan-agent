# -*- coding: utf-8 -*-
"""提示词段计数台账（2026-11-12，ACE 启示落地 P3+，ADR-011）。

动机：GOV-06 跨日漂移归因花了人肉 A/B 探针 + 多轮复测；本工具把
「哪个段在场、结果如何」机械聚合，让 62 题每次跑完自动输出：
  1. 段通过率对比（段在场 vs 缺席的通过率，按 run）；
  2. 结果翻转三分类：
     A 段归因候选——结果翻转且活跃段集合变化（需 A/B 探针终审，
       GOV-06 案例：落在 A 但探针证明是漂移——工具只提线索不定罪）；
     B 漂移候选——结果翻转且活跃段集合相同（优先怀疑 LLM 服务端漂移）；
     C 稳定——结果未变。
  3. 在线台账联查（可选 --ledger）：data/feedback_ledger.jsonl 中该题的
     哈希命中与引用越界记录。

段特征对每题**确定性**计算（今日检索、原问题路径，与 app/main.py 装配逻辑
同源镜像）：validity（上下文含〔状态〕标注片段）、adjacent（相邻注入块数）、
rewrite_would（弱命中会尝试改写——LLM 非确定，仅记录不参与判定）。

口径与诚实约束：
- 特征按「该 run 的服务端实际启用的段」折算（run=tag:seg1,seg2），因为
  历史跑分时代码里未必有该段——这正是 ctx-24（无 3.1）vs ctx-31（有 3.1）
  的对照基础；
- 弱命中题的最终上下文受 LLM 改写合并影响，离线特征是原问题路径的近似，
  报告单列 rewrite_would=True 的题，不据此下结论；
- 段归因候选 ≠ 结论：A/B 探针才是终审（与 3.1 报告的 GOV-06 归因纪律一致）。

用法：
    .venv/Scripts/python.exe tools/segment_ledger.py \
        --runs ctx-24:validity,ctx-31:validity,adjacent [--set docs/eval/eval_set_v2.json] \
        [--ledger] [--out]
    run 规格：tag[:seg1,seg2]——tag 自动匹配 docs/eval/results/eval_<tag>_*.json
    （多文件取最新）；不传段列表 = 全段活跃（按当前代码）。
"""
import argparse
import glob
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

RESULTS_DIR = os.path.join(BASE, "docs", "eval", "results")
LEDGER_PATH = os.path.join(BASE, "data", "feedback_ledger.jsonl")
ALL_SEGS = ("validity", "adjacent")


def load_eval_set(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["questions"]


def compute_features(question, config, retrieval, llm):
    """确定性段特征：与 main.py 装配逻辑同源镜像（原问题路径，不模拟改写）。"""
    hits, top_cov = retrieval.hybrid_search(question, config.RECALL_WINDOW)
    if not hits:
        return {"validity": False, "adjacent": 0, "rewrite_would": False,
                "n_ctx": 0, "top_cov": 0.0}
    primary = hits[:config.RETRIEVAL_TOP_K]
    primary_docs = {h["doc_id"] for h in primary}
    supplement = [h for h in hits[config.RETRIEVAL_TOP_K:]
                  if h["doc_id"] in primary_docs][:6]
    context_hits = primary + supplement
    validity = any(llm.validity_note(h.get("valid_status") or "")
                   for h in context_hits)
    in_ctx_ids = {h["chunk_id"] for h in context_hits}
    adjacent = 0
    for h in context_hits:
        if adjacent >= 3:
            break
        tail = h["text"].rstrip()[-1:] if h["text"].rstrip() else ""
        if tail not in ("，", "、", "；", "："):
            continue
        try:
            ctx = retrieval.get_chunk_context(h["chunk_id"])
        except Exception:
            continue
        nxt = (ctx or {}).get("next")
        if not nxt:
            continue
        try:
            nxt_id = retrieval.get_chunk_id_by_seq(h["doc_id"], nxt["seq"])
        except Exception:
            nxt_id = None
        if nxt_id is not None and nxt_id in in_ctx_ids:
            continue
        adjacent += 1
    return {"validity": bool(validity), "adjacent": int(adjacent),
            "rewrite_would": bool((not hits) or top_cov < config.REWRITE_MIN_COVERAGE),
            "n_ctx": len(context_hits), "top_cov": round(top_cov, 3)}


def load_run(tag):
    """tag -> 最新结果文件（eval_<tag>_<date>.json）。"""
    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, f"eval_{tag}_*.json")))
    if not paths:
        raise SystemExit(f"找不到 eval_{tag}_*.json（在 {RESULTS_DIR}）")
    with open(paths[-1], encoding="utf-8") as f:
        data = json.load(f)
    rows = {r["id"]: r for r in data.get("rows", [])}
    return os.path.basename(paths[-1]), data.get("summary", {}), rows


def outcome(row):
    """fact 题看 ok；boundary/refusal 题看 pass；缺行 None。"""
    if row is None:
        return None
    if row.get("type") == "fact":
        return bool(row.get("ok"))
    return row.get("pass") if "pass" in row else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=os.path.join(BASE, "docs", "eval", "eval_set_v2.json"))
    ap.add_argument("--runs", required=True,
                    help="run 规格，用 ; 分隔（段列表内用逗号）："
                         "'tag1:seg1,seg2;tag2'——段列表=该 run 服务端实际启用的段，"
                         "缺省全段活跃（按当前代码）")
    ap.add_argument("--ledger", action="store_true", help="附在线台账联查")
    ap.add_argument("--out", default=None, help="报告输出路径（默认打印）")
    args = ap.parse_args()

    from app import config, llm, retrieval  # 延迟导入：保证 --help 无 jieba 噪声

    questions = load_eval_set(args.set)
    feats = {}
    for q in questions:
        feats[q["id"]] = compute_features(q["question"], config, retrieval, llm)

    runs = []
    for spec in args.runs.replace("+", ";").split(";"):
        spec = spec.strip()
        if not spec:
            continue
        tag, _, segs = spec.partition(":")
        active = tuple(s.strip() for s in segs.split(",") if s.strip()) or ALL_SEGS
        fname, summary, rows = load_run(tag)
        runs.append({"tag": tag, "active": active, "file": fname,
                     "summary": summary, "rows": rows})

    lines = []
    lines.append("# 提示词段计数台账（自动生成）")
    lines.append("")
    lines.append(f"> 生成：{time.strftime('%Y-%m-%d %H:%M')} · 评测集 {os.path.basename(args.set)} "
                 f"· 特征按今日检索确定性复算（原问题路径，弱命中改写不模拟）")
    lines.append("")
    lines.append("| run | 结果文件 | 服务端启用段 |")
    lines.append("|---|---|---|")
    for r in runs:
        lines.append(f"| {r['tag']} | {r['file']} | {','.join(r['active'])} |")
    lines.append("")

    # ---- 段通过率对比（每 run 内：段在场 vs 缺席）----
    lines.append("## 一、段通过率对比（fact 题）")
    lines.append("")
    lines.append("| run | 段 | 在场题数 | 在场通过率 | 缺席题数 | 缺席通过率 |")
    lines.append("|---|---|---|---|---|---|")
    for r in runs:
        for seg in ALL_SEGS:
            present, absent = [], []
            for q in questions:
                row = r["rows"].get(q["id"])
                if row is None or row.get("type") != "fact":
                    continue
                oc = outcome(row)
                if oc is None:
                    continue
                eff = seg in r["active"] and bool(feats[q["id"]].get(
                    "validity" if seg == "validity" else "adjacent"))
                (present if eff else absent).append(oc)
            pr = f"{sum(present)}/{len(present)}" if present else "-"
            ar = f"{sum(absent)}/{len(absent)}" if absent else "-"
            lines.append(f"| {r['tag']} | {seg} | {len(present)} | {pr} | "
                         f"{len(absent)} | {ar} |")
    lines.append("")

    # ---- 翻转三分类（基线 = 第一个 run）----
    base = runs[0]
    lines.append(f"## 二、结果翻转三分类（基线 = {base['tag']}）")
    lines.append("")
    lines.append("- **A 段归因候选**：结果翻转 + 活跃段集合变化 → 需 A/B 探针终审，"
                 "工具只提线索不定罪（GOV-06 教训：落在 A 仍可能是漂移）")
    lines.append("- **B 漂移候选**：结果翻转 + 活跃段集合相同 → 优先怀疑 LLM 服务端漂移"
                 "（跨日 ±1 属噪声，需同日同批次复核）")
    lines.append("")
    bucket_a, bucket_b = [], []
    for r in runs[1:]:
        for q in questions:
            o0, o1 = outcome(base["rows"].get(q["id"])), outcome(r["rows"].get(q["id"]))
            if o0 is None or o1 is None or o0 == o1:
                continue
            def eff(run):
                f = feats[q["id"]]
                return (("validity" in run["active"] and f["validity"]),
                        ("adjacent" in run["active"] and f["adjacent"] > 0))
            (bucket_a if eff(base) != eff(r) else bucket_b).append(
                (q["id"], base["tag"], r["tag"], o0, o1, feats[q["id"]]))
    lines.append(f"### A 段归因候选（{len(bucket_a)} 题）")
    lines.append("")
    if bucket_a:
        lines.append("| 题 | 基线 run | 对比 run | 结果 | 段特征 validity/adjacent |")
        lines.append("|---|---|---|---|---|")
        for qid, b, r, o0, o1, f in bucket_a:
            lines.append(f"| {qid} | {b} | {r} | {'OK' if o0 else 'MISS'}→"
                         f"{'OK' if o1 else 'MISS'} | {f['validity']}/{f['adjacent']} |")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append(f"### B 漂移候选（{len(bucket_b)} 题）")
    lines.append("")
    if bucket_b:
        lines.append("| 题 | 基线 run | 对比 run | 结果 | 段特征 validity/adjacent |")
        lines.append("|---|---|---|---|---|")
        for qid, b, r, o0, o1, f in bucket_b:
            lines.append(f"| {qid} | {b} | {r} | {'OK' if o0 else 'MISS'}→"
                         f"{'OK' if o1 else 'MISS'} | {f['validity']}/{f['adjacent']} |")
    else:
        lines.append("（无）")
    lines.append("")

    # ---- 弱命中题单列（rewrite 非确定，特征近似）----
    weak_ids = [q["id"] for q in questions if feats[q["id"]]["rewrite_would"]]
    lines.append(f"## 三、弱命中题（rewrite_would，{len(weak_ids)} 题）")
    lines.append("")
    lines.append("这些题服务端会走 LLM 改写，最终上下文可能与离线特征不符——"
                 "本报告的特征是原问题路径近似，不据此下结论：")
    lines.append("")
    lines.append(", ".join(weak_ids) if weak_ids else "（无）")
    lines.append("")

    # ---- 在线台账联查（可选）----
    if args.ledger and os.path.exists(LEDGER_PATH):
        from app import feedback
        qh = {q["id"]: feedback.qhash(q["question"]) for q in questions}
        online = {}
        with open(LEDGER_PATH, encoding="utf-8") as f:
            for ln in f:
                try:
                    row = json.loads(ln)
                except Exception:
                    continue
                online.setdefault(row.get("qhash"), []).append(row)
        lines.append("## 四、在线台账联查（data/feedback_ledger.jsonl）")
        lines.append("")
        lines.append("| 题 | 线上问次 | cite_bad 命中 | backends |")
        lines.append("|---|---|---|---|")
        for qid, h in qh.items():
            rows_ = online.get(h)
            if not rows_:
                continue
            bad = sum(1 for r in rows_ if r.get("cite_bad"))
            bks = ",".join(sorted({str(r.get("backend")) for r in rows_}))
            lines.append(f"| {qid} | {len(rows_)} | {bad} | {bks} |")
        lines.append("")
    elif args.ledger:
        lines.append("## 四、在线台账联查")
        lines.append("")
        lines.append("（data/feedback_ledger.jsonl 尚不存在——起服务问几题后即有数据）")
        lines.append("")

    report = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"已写入 {args.out}")
    print(report)


if __name__ == "__main__":
    main()
