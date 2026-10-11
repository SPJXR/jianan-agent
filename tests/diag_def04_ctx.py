# -*- coding: utf-8 -*-
"""DEF-04 上下文诊断：调 /api/chat 收集 sources 事件，看答案块排名与周边噪音。"""
import io
import json
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:9100"
Q = "有限空间内氧气浓度多少算合格？"

frames = []
with httpx.stream("POST", f"{BASE}/api/chat", json={"question": Q}, timeout=90) as r:
    buf = ""
    for chunk in r.iter_text():
        buf += chunk
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            ev, data = "", ""
            for ln in frame.splitlines():
                if ln.startswith("event:"):
                    ev = ln[6:].strip()
                elif ln.startswith("data:"):
                    data += ln[5:].strip()
            if data:
                frames.append((ev, json.loads(data)))

sources = next(d["sources"] for ev, d in frames if ev == "sources")
done = next(d for ev, d in frames if ev == "done")
answer = "".join(d.get("delta", "") for ev, d in frames if ev == "delta")

print(f"sources 共 {len(sources)} 条：")
for i, s in enumerate(sources):
    mark = " <<<< 答案块" if ("19.5" in s.get("full", "") or "23.5" in s.get("full", "")) else ""
    print(f"  [{i+1}] {s.get('docId')} {s.get('clause', '')[:12]} "
          f"{(s.get('excerpt') or '')[:40]!r}{mark}")
print()
print("done:", {k: v for k, v in done.items() if k != "answer"})
print()
print("ANSWER:", answer[:150])
