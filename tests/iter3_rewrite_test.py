# -*- coding: utf-8 -*-
"""迭代3（两阶段检索改写）真实 LLM 端到端验证。

覆盖：
- C 组口语题：验证弱命中触发 LLM 改写后重检，最终回答命中预期文档
- B 组库外题：验证「未找到」兜底不编造
- done.notice：改写发生时应有 notice 事件提示（如有实现）

运行前置：本地服务已启动（127.0.0.1:9000，加载新版两阶段检索代码）。
"""
import io
import json
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:9000"

CASES = [
    # (组, 问题, 预期文档前缀, 期望回答方式)
    ("C1", "工地上挖坑底下干活有啥危险要注意的？", "0069", "answer"),
    ("C3", "震完了房子咋评估谁能去评？", "0011", "answer"),
    ("C4", "密目网着火了怎么办", "0072", "answer"),
    ("B1", "工地食堂需要办理什么证照？", None, "no_answer_or_honest"),
    ("B5", "住建部现任部长是谁？", None, "no_answer_or_honest"),
]

results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))

for tag, q, expect_doc, mode in CASES:
    frames = []
    with httpx.stream("POST", f"{BASE}/api/chat", json={"question": q}, timeout=120) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            if "done" in buf or "error" in buf:
                # 再读一点确保拿全 done 帧
                try:
                    for extra in r.iter_text():
                        buf += extra
                except Exception:
                    pass
                break
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

    seq = [ev for ev, _ in frames]
    sources = next((d["sources"] for ev, d in frames if ev == "sources"), [])
    done = next((d for ev, d in frames if ev == "done"), {})
    answer = "".join(d.get("text", "") for ev, d in frames if ev == "delta")
    notice = next((d.get("message", "") for ev, d in frames if ev == "notice"), "")

    doc_ids = [s["docId"] for s in sources]
    hit = any(d.startswith(expect_doc) for d in doc_ids) if expect_doc else None
    honest_fallback = ("未找到" in answer or "知识" in answer or done.get("backend") == "no_answer"
                       or "仅提供" in answer or "超出" in answer or "无法" in answer
                       or not answer)

    if mode == "answer":
        check(f"{tag} 回答命中预期文档 {expect_doc}", hit, f"docs={doc_ids[:4]}")
        check(f"{tag} 回答非空且 done 正常", bool(answer) and done.get("backend") in ("llm", "retrieval"),
              f"backend={done.get('backend')} len={len(answer)}")
    else:
        check(f"{tag} 兜底诚实（未找到/不编造）", honest_fallback,
              f"backend={done.get('backend')} answer[:60]={answer[:60]!r}")
    if notice:
        print(f"     [{tag}] notice: {notice[:80]}")

print()
n_pass = sum(1 for _, ok in results if ok)
print(f"RESULT: {n_pass}/{len(results)} PASS")
sys.exit(0 if n_pass == len(results) else 1)
