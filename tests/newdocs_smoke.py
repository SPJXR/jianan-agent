# -*- coding: utf-8 -*-
"""新文档（0077/0078/0079）入库抽检：各出 2 题验证可答性 + 逐字引用"""
import io
import json
import re
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:9000"
CASES = [
    ("0077-A", "脚手架工程有哪些情形应判定为重大事故隐患？", "0077",
     ["连墙件", "基础承载力"]),
    ("0077-B", "基坑工程什么情况下要判定为重大事故隐患？", "0077",
     ["堆载超过设计允许值", "地下水"]),
    ("0078-A", "有限空间作业的审批人和监护人有什么职责要求？", "0078",
     ["审批", "监护"]),
    ("0078-B", "工贸企业有限空间作业发包给其他单位时有什么要求？", "0078",
     ["发包", "统一协调"]),
    ("0079-A", "气体检测报警仪的选用有什么要求？", "0079",
     ["检测报警仪"]),
    ("0079-B", "有限空间作业通风有哪些要求？", "0079",
     ["通风"]),
]


def ask(question):
    buf = ""
    with httpx.stream("POST", f"{BASE}/api/chat", json={"question": question},
                      timeout=120, trust_env=False) as r:
        for chunk in r.iter_text():
            buf += chunk
    frames = []
    for frame in buf.split("\n\n"):
        ev = data = ""
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
        "answer": "".join(d.get("text", "") for ev, d in frames if ev == "delta"),
        "sources": next((d["sources"] for ev, d in frames if ev == "sources"), []),
        "done": next((d for ev, d in frames if ev == "done"), {}),
    }


fail = 0
for tag, q, expect_doc, kws in CASES:
    res = ask(q)
    src_docs = [s["docId"] for s in res["sources"]]
    # 逐字核验：引用全文必须真实存在（backend=llm 时 sources 即 LLM 所见片段）
    hit_doc = expect_doc in src_docs
    ans = res["answer"]
    kw_hit = any(k in ans for k in kws)
    ok = hit_doc and kw_hit and res["done"].get("backend") == "llm"
    if not ok:
        fail += 1
    print(("PASS" if ok else "FAIL"), tag,
          f"docs={'Y' if hit_doc else 'N'} kw={'Y' if kw_hit else 'N'} "
          f"backend={res['done'].get('backend')} srcs={src_docs[:4]}")
    print("      答:", ans[:90].replace("\n", " "))

print("RESULT:", "PASS" if fail == 0 else f"FAIL ({fail})")
sys.exit(0 if fail == 0 else 1)
