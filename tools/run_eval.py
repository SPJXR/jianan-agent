# -*- coding: utf-8 -*-
"""评测集 v2 自动打分工具（迭代6）：消费 docs/eval/eval_set_v2.json，对指定服务跑
端到端量化评测，产出 docs/eval/results/eval_<tag>_<date>.json 与同名 .md 报告。

用法：
    .venv/Scripts/python.exe tools/run_eval.py --base http://127.0.0.1:9001 --tag local
    .venv/Scripts/python.exe tools/run_eval.py --base http://8.137.11.193:9000 --tag online
    可选：--ids DEF-01,DEF-04 只跑指定题；--limit N 只跑前 N 题；--sleep 题间隔秒

指标口径（与 docs/eval/评测集-v2-角色化62题.md §二一致）：
    检索分      top3 命中 expected_docs 任一文档（doc 级 hit@3）
    上下文覆盖  sources 全文命中的关键词组占比（ADR-004 教训：检测「对的文档、
                错的块」——答案块是否真正进入 LLM 上下文）
    回答覆盖    回答文本命中的关键词组占比（全部命中=达标，过半=部分）
    引用分      回答含 [n] 样式编号
    refusal     出现「未找到」或「本助手仅提供建安法规知识问答」
    boundary    明确说明未收录/仅有名称判 PASS，否则标 REVIEW 待人工复核
    综合合格    检索命中 AND 回答全覆盖 AND 引用规范
角色风味不做自动打分（人工抽样对照见评测集附录 A）。
"""
import argparse
import io
import json
import os
import re
import statistics
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
EVAL_SET = os.path.join(BASE_DIR, "docs", "eval", "eval_set_v2.json")
OUT_DIR = os.path.join(BASE_DIR, "docs", "eval", "results")

from app.feedback import classify_answer  # noqa: E402  # RECOMP 错误复制率（ADR-011 增补）

CITE_RE = re.compile(r"\[\d+\]")
REFUSAL_OK = ("未找到", "本助手仅提供建安法规知识问答")
BOUNDARY_OK = ("未找到", "未收录", "无该标准", "未随文本入库")


def norm(s: str) -> str:
    """去空白后子串匹配（归一『3 年』『30 分钟』等排版差异）。"""
    return re.sub(r"\s+", "", s or "")


def hit_groups(text: str, groups) -> set:
    t = norm(text)
    return {i for i, g in enumerate(groups) if any(norm(w) in t for w in g)}


def ask(base: str, question: str, role: str, timeout: float, history=None) -> dict:
    """POST /api/chat 并解析 SSE（事件类型在 event: 行，勿从 JSON 里找，0923 经验）。
    history：多轮评测组（--set eval_set_mt.json）的题面历史，None 时不发该字段。"""
    import httpx
    client = httpx.Client(trust_env=False, timeout=timeout)  # 绕开系统代理（本机 502 坑）
    t0 = time.time()
    t_first = None
    buf = ""
    body = {"question": question, "role": role}
    if history:
        body["history"] = history
    try:
        with client.stream("POST", base.rstrip("/") + "/api/chat", json=body) as r:
            if r.status_code != 200:
                return {"http": r.status_code, "t_total": round(time.time() - t0, 2)}
            for chunk in r.iter_text():
                if t_first is None and "event: delta" in chunk:
                    t_first = time.time()
                buf += chunk
    finally:
        client.close()
    frames = []
    for frame in buf.split("\n\n"):
        ev, data = "", ""
        for ln in frame.splitlines():
            if ln.startswith("event:"):
                ev = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        if data:
            try:
                frames.append((ev, json.loads(data)))
            except Exception:
                pass
    return {
        "http": 200,
        "sources": next((d["sources"] for ev, d in frames if ev == "sources"), []),
        "done": next((d for ev, d in frames if ev == "done"), None),
        "answer": "".join(d.get("text", "") for ev, d in frames if ev == "delta"),
        "retrieved": next((d for ev, d in frames
                           if ev == "status" and d.get("stage") == "retrieved"), {}),
        "t_first": round(t_first - t0, 2) if t_first else None,
        "t_total": round(time.time() - t0, 2),
    }


def score_fact(q: dict, res: dict) -> dict:
    exp = set(q["expected_docs"])
    groups = q.get("keywords") or []
    top3 = {s["docId"] for s in res["sources"][:3]}
    # ctx_hit（路线图 B-1）：预期文档是否真正进入 LLM 上下文（sources = top-8 主证据
    # + 同文档补位，即服务端的 context_hits）。ret_hit 只看 top-3；二者组合可区分
    # 「检索没召回」（ret_hit=N, ctx_hit=N）与「召回了但被截断/排位靠后」
    # （ret_hit=N, ctx_hit=Y），让「未找到」类失败归因更准。
    all_docs = {s["docId"] for s in res["sources"]}
    ctx = set()
    for s in res["sources"]:
        ctx |= hit_groups(s.get("full", ""), groups)
    ans = hit_groups(res["answer"], groups)
    n = len(groups) or 1
    miss = [" / ".join(groups[i]) for i in sorted(set(range(len(groups))) - ans)]
    # ---- 上下文利用率三指标（上下文改进计划第1期，2026-11-03）----
    # cite_util：答案实际引用的 [n] 编号数 / 进上下文的块数——装配 14 块平均被
    #            引用几块，衡量上下文装配的信噪比
    # cite_pos：被引用块在上下文中的位次列表（no 即位次）——位次分布用于检验
    #            「长上下文中段沉底」（lost in the middle）：若被引用块集中于
    #            头部而中后段块几乎不被引用，说明装配策略在浪费预算
    cites = sorted({int(m[1:-1]) for m in CITE_RE.findall(res["answer"])})
    n_src = len(res["sources"])
    valid_pos = [c for c in cites if 1 <= c <= n_src]
    return {
        "ret_hit": bool(top3 & exp),
        "ctx_hit": bool(all_docs & exp),
        "top3": sorted(top3),
        "ctx_cov": round(len(ctx) / n, 2),
        "ans_cov": round(len(ans) / n, 2),
        "citation": bool(CITE_RE.search(res["answer"])),
        "cite_util": round(len(valid_pos) / n_src, 2) if n_src else 0.0,
        "cite_pos": valid_pos,
        "miss_kw": miss,
    }


def pos_bucket_ok(facts: list) -> dict:
    """位置偏差分桶通过率（LongLLMLingua 实证口径，2026-11-13）。

    按答案所引块的最高位次（cite_pos 最大值）分桶统计综合通过率：
    9+ 位桶 = 同文档补位区，是位置偏差的靶区（论文：原始 prompt 中间位置
    损失 20+ 分；本项目实证 ctx-24 该桶 6/9，恰为 PM-06/PM-11 miss 集中区）。
    每次跑 62 题免费产出——位置偏差监测器，与 cite_pos_dist（次数分布）互补。
    """
    buckets = {"1-3": [], "4-8": [], "9+": []}
    for r in facts:
        ps = r.get("cite_pos") or []
        if not ps:
            continue
        k = "1-3" if max(ps) <= 3 else ("4-8" if max(ps) <= 8 else "9+")
        buckets[k].append(1 if r.get("ok") else 0)
    return {k: (f"{sum(v)}/{len(v)}" if v else "-") for k, v in buckets.items()}


def score_edge(q: dict, res: dict) -> dict:
    a = res["answer"]
    # RECOMP 指标（2026-11-13）：copy=证据不含答案却仍带引用复制断言；
    # 该标记只在拒答/边界组有意义，fact 题不解读。
    cls = classify_answer(a)
    out = {"copy": cls["copy"], "refusal": cls["refusal"], "cited": cls["cited"],
           "copy_review": cls["review"]}
    if q["type"] == "refusal":
        out["pass"] = any(p in a for p in REFUSAL_OK)
        return out
    ack = any(p in a for p in BOUNDARY_OK) or \
        ("仅" in a and any(w in a for w in ("名称", "目录", "前言")))
    out["pass"] = ack  # 未明确说明 -> REVIEW 人工复核（是否编造需人工判断）
    return out


def run(args):
    eval_set = args.set if args.set else os.path.basename(EVAL_SET)
    spec = json.load(open(os.path.join(BASE_DIR, "docs", "eval", eval_set),
                          encoding="utf-8"))
    qs = spec["questions"]
    if args.ids:
        want = {x.strip().upper() for x in args.ids.split(",")}
        qs = [q for q in qs if q["id"] in want]
    qs = qs[:args.limit] if args.limit else qs
    roles = {r["id"]: r["label"] for r in spec.get("roles", [])}
    print(f"评测目标: {args.base}  题数: {len(qs)}  tag: {args.tag}")

    rows, t_costs = [], []
    for i, q in enumerate(qs, 1):
        try:
            res = ask(args.base, q["question"], q.get("role", "default"),
                      args.timeout, history=q.get("history"))
        except Exception as e:
            res = {"http": 0, "err": f"{type(e).__name__}: {str(e)[:120]}"}
        if res.get("http") != 200:
            rows.append({"id": q["id"], "group": q["group"], "type": q["type"],
                         "error": res.get("err") or f"HTTP {res['http']}"})
            print(f"  [{i:2}/{len(qs)}] {q['id']:<7} 请求失败 {res.get('err') or res['http']}")
            continue
        t_costs.append(res["t_total"])
        if q["type"] == "fact":
            sc = score_fact(q, res)
            ok = sc["ret_hit"] and sc["ans_cov"] >= 0.999 and sc["citation"]
            sc.update({"id": q["id"], "group": q["group"], "role": q["role"],
                       "type": "fact",
                       "ok": ok, "t": res["t_total"], "t_first": res["t_first"],
                       "backend": (res.get("done") or {}).get("backend"),
                       "answer": res["answer"]})
        else:
            sc = score_edge(q, res)
            sc.update({"id": q["id"], "group": q["group"], "role": q["role"],
                       "type": q["type"],
                       "t": res["t_total"], "t_first": res["t_first"],
                       "answer": res["answer"]})
        rows.append(sc)
        if q["type"] == "fact":
            print(f"  [{i:2}/{len(qs)}] {q['id']:<7} ret={'Y' if sc['ret_hit'] else 'N'} "
                  f"ctxH={'Y' if sc['ctx_hit'] else 'N'} "
                  f"ctx={sc['ctx_cov']:.0%} ans={sc['ans_cov']:.0%} cite={'Y' if sc['citation'] else 'N'} "
                  f"citeU={sc['cite_util']:.0%} "
                  f"{'OK' if sc['ok'] else 'MISS ' + ','.join(sc['miss_kw'][:3])} ({sc['t']}s)")
        else:
            print(f"  [{i:2}/{len(qs)}] {q['id']:<7} {'PASS' if sc['pass'] else 'REVIEW/FAIL'} ({sc['t']}s)")

    # ---- 汇总 ----
    facts = [r for r in rows if r["type"] == "fact"]
    edges = [r for r in rows if r["type"] != "fact"]
    refus = [r for r in edges if r["type"] == "refusal"]
    bounds = [r for r in edges if r["type"] == "boundary"]
    ret_hits = [r for r in facts if r.get("ret_hit")]
    ctx_hits = [r for r in facts if r.get("ctx_hit")]
    full_ans = [r for r in facts if r.get("ans_cov", 0) >= 0.999]
    full_ok = [r for r in facts if r.get("ok")]
    cite_ok = [r for r in facts if r.get("citation")]
    ctx_full = [r for r in facts if r.get("ctx_cov", 0) >= 0.999]
    tt = [r["t"] for r in rows if "t" in r]
    tt.sort()
    p = lambda x: (tt[min(len(tt) - 1, int(len(tt) * x))] if tt else 0)

    # ---- 上下文利用率汇总（第1期指标）----
    utils = [r.get("cite_util", 0.0) for r in facts]
    pos_pool = [p_ for r in facts for p_ in r.get("cite_pos", [])]
    pos_h1 = sum(1 for x in pos_pool if x <= 3)        # 头部：主证据 top-3
    pos_h2 = sum(1 for x in pos_pool if 4 <= x <= 8)   # 中段：主证据 4-8
    pos_h3 = sum(1 for x in pos_pool if x >= 9)        # 尾部：同文档补位块
    pb = pos_bucket_ok(facts)

    summary = {
        "base": args.base, "tag": args.tag, "date": time.strftime("%Y-%m-%d %H:%M"),
        "n_total": len(rows), "n_fact": len(facts), "n_edge": len(edges),
        "retrieval_hit3": f"{len(ret_hits)}/{len(facts)}",
        "ctx_hit": f"{len(ctx_hits)}/{len(facts)}",
        "ctx_block_hit": f"{len(ctx_full)}/{len(facts)}",
        "answer_full_cov": f"{len(full_ans)}/{len(facts)}",
        "citation_rate": f"{len(cite_ok)}/{len(facts)}",
        "fact_all_ok": f"{len(full_ok)}/{len(facts)}",
        "refusal_pass": f"{sum(1 for r in refus if r['pass'])}/{len(refus)}",
        "boundary_pass": f"{sum(1 for r in bounds if r['pass'])}/{len(bounds)}",
        "copy_rate": f"{sum(1 for r in edges if r.get('copy'))}/{len(edges)}",
        "copy_review": f"{sum(1 for r in edges if r.get('copy_review'))}/{len(edges)}",
        "refusal_with_cite": f"{sum(1 for r in edges if r.get('refusal') and r.get('cited'))}/{len(edges)}",
        "cite_util_avg": round(statistics.mean(utils), 2) if utils else 0.0,
        "cite_pos_dist": f"1-3位:{pos_h1}次 4-8位:{pos_h2}次 9+位:{pos_h3}次",
        "pos_bucket_ok": f"1-3位:{pb['1-3']} 4-8位:{pb['4-8']} 9+位:{pb['9+']}",
        "t_med": round(statistics.median(tt), 2) if tt else 0,
        "t_p95": round(p(0.95), 2),
    }
    print("\n==== 汇总 ====")
    for k, v in summary.items():
        if k not in ("base", "tag", "date"):
            print(f"  {k:16} {v}")

    os.makedirs(OUT_DIR, exist_ok=True)
    tag = re.sub(r"[^\w-]", "", args.tag)
    jpath = os.path.join(OUT_DIR, f"eval_{tag}_{time.strftime('%Y%m%d')}.json")
    json.dump({"summary": summary, "rows": rows}, open(jpath, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n明细已写入: {jpath}")
    return 0 if not [r for r in rows if "error" in r] else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="服务地址，如 http://127.0.0.1:9001")
    ap.add_argument("--tag", default="run", help="报告标识，如 local / online-v5")
    ap.add_argument("--set", default="", dest="set",
                    help="评测集文件名（docs/eval/ 下，如 eval_set_mt.json 多轮组）；默认 62 题主集")
    ap.add_argument("--ids", default="", help="只跑指定题，逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--sleep", type=float, default=0.3, help="题间隔秒（限流友好）")
    args = ap.parse_args()
    if args.sleep > 0:
        _ask_orig = ask
        def ask(b, q, r, t, history=None):  # noqa: F811
            time.sleep(args.sleep)
            return _ask_orig(b, q, r, t, history=history)
    sys.exit(run(args))
