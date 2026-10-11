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
EVAL_SET = os.path.join(BASE_DIR, "docs", "eval", "eval_set_v2.json")
OUT_DIR = os.path.join(BASE_DIR, "docs", "eval", "results")

CITE_RE = re.compile(r"\[\d+\]")
REFUSAL_OK = ("未找到", "本助手仅提供建安法规知识问答")
BOUNDARY_OK = ("未找到", "未收录", "无该标准", "未随文本入库")


def norm(s: str) -> str:
    """去空白后子串匹配（归一『3 年』『30 分钟』等排版差异）。"""
    return re.sub(r"\s+", "", s or "")


def hit_groups(text: str, groups) -> set:
    t = norm(text)
    return {i for i, g in enumerate(groups) if any(norm(w) in t for w in g)}


def ask(base: str, question: str, role: str, timeout: float) -> dict:
    """POST /api/chat 并解析 SSE（事件类型在 event: 行，勿从 JSON 里找，0923 经验）。"""
    import httpx
    client = httpx.Client(trust_env=False, timeout=timeout)  # 绕开系统代理（本机 502 坑）
    t0 = time.time()
    t_first = None
    buf = ""
    try:
        with client.stream("POST", base.rstrip("/") + "/api/chat",
                            json={"question": question, "role": role}) as r:
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
    ctx = set()
    for s in res["sources"]:
        ctx |= hit_groups(s.get("full", ""), groups)
    ans = hit_groups(res["answer"], groups)
    n = len(groups) or 1
    miss = [" / ".join(groups[i]) for i in sorted(set(range(len(groups))) - ans)]
    return {
        "ret_hit": bool(top3 & exp),
        "top3": sorted(top3),
        "ctx_cov": round(len(ctx) / n, 2),
        "ans_cov": round(len(ans) / n, 2),
        "citation": bool(CITE_RE.search(res["answer"])),
        "miss_kw": miss,
    }


def score_edge(q: dict, res: dict) -> dict:
    a = res["answer"]
    if q["type"] == "refusal":
        return {"pass": any(p in a for p in REFUSAL_OK)}
    ack = any(p in a for p in BOUNDARY_OK) or \
        ("仅" in a and any(w in a for w in ("名称", "目录", "前言")))
    return {"pass": ack}  # 未明确说明 -> REVIEW 人工复核（是否编造需人工判断）


def run(args):
    spec = json.load(open(EVAL_SET, encoding="utf-8"))
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
            res = ask(args.base, q["question"], q.get("role", "default"), args.timeout)
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
                  f"ctx={sc['ctx_cov']:.0%} ans={sc['ans_cov']:.0%} cite={'Y' if sc['citation'] else 'N'} "
                  f"{'OK' if sc['ok'] else 'MISS ' + ','.join(sc['miss_kw'][:3])} ({sc['t']}s)")
        else:
            print(f"  [{i:2}/{len(qs)}] {q['id']:<7} {'PASS' if sc['pass'] else 'REVIEW/FAIL'} ({sc['t']}s)")

    # ---- 汇总 ----
    facts = [r for r in rows if r["type"] == "fact"]
    edges = [r for r in rows if r["type"] != "fact"]
    refus = [r for r in edges if r["type"] == "refusal"]
    bounds = [r for r in edges if r["type"] == "boundary"]
    ret_hits = [r for r in facts if r.get("ret_hit")]
    full_ans = [r for r in facts if r.get("ans_cov", 0) >= 0.999]
    full_ok = [r for r in facts if r.get("ok")]
    cite_ok = [r for r in facts if r.get("citation")]
    ctx_full = [r for r in facts if r.get("ctx_cov", 0) >= 0.999]
    tt = [r["t"] for r in rows if "t" in r]
    tt.sort()
    p = lambda x: (tt[min(len(tt) - 1, int(len(tt) * x))] if tt else 0)

    summary = {
        "base": args.base, "tag": args.tag, "date": time.strftime("%Y-%m-%d %H:%M"),
        "n_total": len(rows), "n_fact": len(facts), "n_edge": len(edges),
        "retrieval_hit3": f"{len(ret_hits)}/{len(facts)}",
        "ctx_block_hit": f"{len(ctx_full)}/{len(facts)}",
        "answer_full_cov": f"{len(full_ans)}/{len(facts)}",
        "citation_rate": f"{len(cite_ok)}/{len(facts)}",
        "fact_all_ok": f"{len(full_ok)}/{len(facts)}",
        "refusal_pass": f"{sum(1 for r in refus if r['pass'])}/{len(refus)}",
        "boundary_pass": f"{sum(1 for r in bounds if r['pass'])}/{len(bounds)}",
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
    ap.add_argument("--ids", default="", help="只跑指定题，逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--sleep", type=float, default=0.3, help="题间隔秒（限流友好）")
    args = ap.parse_args()
    if args.sleep > 0:
        _ask_orig = ask
        def ask(b, q, r, t):  # noqa: F811
            time.sleep(args.sleep)
            return _ask_orig(b, q, r, t)
    sys.exit(run(args))
