# -*- coding: utf-8 -*-
"""端到端接口测试：/api/chat SSE 两条路径 + sources + examples"""
import io
import json
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:9000"


def sse_chat(question, out_limit=1600):
    frames = []
    with httpx.stream("POST", f"{BASE}/api/chat", json={"question": question}, timeout=90) as r:
        print("HTTP", r.status_code)
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
    text = "".join(d.get("text", "") for ev, d in frames if ev == "delta")
    sources = next((d["sources"] for ev, d in frames if ev == "sources"), [])
    done = next((d for ev, d in frames if ev == "done"), {})
    statuses = [d for ev, d in frames if ev == "status"]
    print("statuses:", [(s.get("stage"), s.get("hits"), s.get("docs")) for s in statuses])
    print("done:", done)
    print("sources:", [(s["no"], s["docId"], s["title"][:16], s["clause"][:12]) for s in sources])
    print("answer:", text[:out_limit].replace("\n", " ⏎ "))
    return frames


print("=" * 30, "CASE 1 可答问题（降级模式，无 API Key）")
sse_chat("有限空间作业前需要检测哪些气体？")

print("=" * 30, "CASE 2 库外问题（应走未找到兜底）")
sse_chat("美国OSHA对脚手架有什么要求？")

print("=" * 30, "CASE 3 空问题")
r = httpx.post(f"{BASE}/api/chat", json={"question": "   "})
print(r.status_code, r.json())

print("=" * 30, "CASE 4 sources")
r = httpx.get(f"{BASE}/api/sources")
d = r.json()
print("totalDocs:", d["totalDocs"], "indexedDocs:", d["indexedDocs"], "totalChunks:", d["totalChunks"])
print("categories:", d["categories"])
