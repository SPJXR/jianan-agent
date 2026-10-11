# -*- coding: utf-8 -*-
"""线上 v3 部署验收：对 http://8.137.11.193:9000 跑测试问题集核心题。

覆盖：
- A 组 10 题（核心场景）：SSE 正常、sources 命中预期文档、回答非空
- C 组 3 题（口语题，两阶段改写主战场）：改写后命中预期文档
- B 组 2 题抽查（兜底诚实）：不编造
- 埋点联动：测试后 GET /api/track/stats 计数应增长

运行：env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe tests/online_v3_test.py
"""
import io
import json
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://8.137.11.193:9000"
TIMEOUT = 120

CASES = [
    # (组, 问题, 预期文档前缀 or None, 模式)
    ("A1", "特种作业人员报名考核需要满足什么条件？", "0063", "answer"),
    ("A2", "特种作业操作资格考核成绩能保留多久？", "0063", "answer"),
    ("A3", "施工现场的安全网有什么要求？可以用普通的密目网吗？", "0072", "answer"),
    ("A4", "桩头凿除有什么规定？", "0072", "answer"),
    ("A5", "专项施工方案里毗邻建筑物没有防护措施算严重缺陷吗？", "0071", "answer"),
    ("A6", "起重吊装的专项施工方案要注意什么？", "0071", "answer"),
    ("A7", "震后应急评估专家组可以采取哪些措施？", "0011", "answer"),
    ("A8", "震后建筑安全评估专家队由谁管理？", "0003", "answer"),
    ("A9", "项目开工怎么办理？走什么流程？", "0067", "answer"),
    ("A10", "历史文化街区划定有什么标准？", "0006", "answer"),
    ("C1", "工地上挖坑底下干活有啥危险要注意的？", "0069", "answer"),
    ("C3", "震完了房子咋评估谁能去评？", "0011", "answer"),
    ("C4", "密目网着火了怎么办", "0072", "answer"),
    ("B1", "工地食堂需要办理什么证照？", None, "honest"),
    ("B5", "住建部现任部长是谁？", None, "honest"),
]

results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""), flush=True)

def ask(q):
    frames = []
    with httpx.stream("POST", f"{BASE}/api/chat", json={"question": q}, timeout=TIMEOUT) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
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
    sources = next((d["sources"] for ev, d in frames if ev == "sources"), [])
    done = next((d for ev, d in frames if ev == "done"), {})
    answer = "".join(d.get("text", "") for ev, d in frames if ev == "delta")
    return seq_done(frames), sources, done, answer

def seq_done(frames):
    return any(ev == "done" for ev, _ in frames)

# 先取基线埋点计数
try:
    base_stats = httpx.get(f"{BASE}/api/track/stats", timeout=10).json().get("counts", {})
except Exception:
    base_stats = {}

for tag, q, expect_doc, mode in CASES:
    try:
        has_done, sources, done, answer = ask(q)
        doc_ids = [s["docId"] for s in sources]
        if mode == "answer":
            hit = any(d.startswith(expect_doc) for d in doc_ids)
            check(f"{tag} 命中 {expect_doc}", hit, f"docs={doc_ids[:4]}")
            check(f"{tag} 回答完整", has_done and bool(answer) and done.get("backend") in ("llm", "retrieval"),
                  f"backend={done.get('backend')} len={len(answer)}")
        else:
            honest = ("未找到" in answer or "知识库" in answer or not answer)
            check(f"{tag} 兜底诚实不编造", honest,
                  f"answer[:50]={answer[:50]!r}")
    except Exception as e:
        check(f"{tag} 请求异常", False, f"{type(e).__name__}: {str(e)[:80]}")

# 埋点联动
try:
    after = httpx.get(f"{BASE}/api/track/stats", timeout=10).json().get("counts", {})
    grew = after.get("question_sent", 0) >= base_stats.get("question_sent", 0) + len(CASES)
    check("埋点计数随测试增长", grew, f"question_sent: {base_stats.get('question_sent', 0)} -> {after.get('question_sent', 0)}")
except Exception as e:
    check("埋点计数随测试增长", False, str(e)[:80])

print()
n_pass = sum(1 for _, ok in results if ok)
print(f"RESULT: {n_pass}/{len(results)} PASS")
sys.exit(0 if n_pass == len(results) else 1)
