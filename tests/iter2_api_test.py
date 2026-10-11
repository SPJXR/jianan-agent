# -*- coding: utf-8 -*-
"""迭代2 API 级测试：埋点端点校验 / sources 时效列 / chat 无 history 回归 / 逐字契约回归

运行前置：服务已启动（127.0.0.1:9000）， kb/kb.sqlite 为迭代2.3 重建后的库。
"""
import hashlib
import io
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:9000"
ROOT = Path(__file__).resolve().parent.parent

results = []

def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))

# ---- 1. 埋点端点 ----
r = httpx.post(f"{BASE}/api/track", json={"events": []})
check("T7 空 events 400", r.status_code == 400, str(r.status_code))

r = httpx.post(f"{BASE}/api/track", json={"events": [{"event": "page_view"}] * 21})
check("T7 超 20 条 400", r.status_code == 400, str(r.status_code))

r = httpx.post(f"{BASE}/api/track", json={"events": [{"event": "EVIL NAME!", "x": 1}]})
check("T7 非法事件名 400", r.status_code == 400, str(r.status_code))

# 计数自 2026-10-11 起持久化（ADR-001 增补），固定事件名会跨次运行累加。
# 因此用带时间戳的唯一事件名，断言"本次上报的 2 条被计入"，而非"全局计数等于 2"。
marker = "iter2_api_evt_%s" % time.strftime("%H%M%S")
r = httpx.post(f"{BASE}/api/track", json={"events": [
    {"event": marker, "ts": 1758362400000, "device": "desktop", "page_version": "v2", "chars": 12},
    {"event": marker, "nested": {"drop": "me"}, "keep": 1.5, "flag": True},
]})
check("T1 合法上报 accepted=2", r.status_code == 200 and r.json().get("accepted") == 2, r.text)

r = httpx.get(f"{BASE}/api/track/stats")
d = r.json()
check("T8 stats 返回当日计数", d.get("day", "").isdigit() and d["counts"].get(marker) == 2,
      json.dumps(d.get("counts", {}).get(marker)))

# ---- 2. sources 时效性列（迭代2.3）----
r = httpx.get(f"{BASE}/api/sources")
d = r.json()
d0 = d["docs"][0]
has_cols = "valid_status" in d0 and "version_date" in d0
# 时效状态已于 2026-10-11 首批核定（见 docs/法规时效核查台账.md）。
# 原断言「缺省全部为待确认」描述的是回填前的状态，现改为校验取值词表合法与核定进度。
VALID_STATUSES = {"effective", "trial", "consultation", "repealed", "na", "unknown"}
statuses = {(doc.get("valid_status") or "unknown") for doc in d["docs"]}
n_unverified = sum(1 for doc in d["docs"]
                   if (doc.get("valid_status") or "unknown") == "unknown")
n_consultation = sum(1 for doc in d["docs"]
                     if doc.get("valid_status") == "consultation")
check("V1 /api/sources 含 valid_status/version_date", has_cols, str(sorted(d0.keys())))
check("V1 valid_status 取值均在词表内", statuses <= VALID_STATUSES,
      str(sorted(statuses - VALID_STATUSES)))
check("V1 时效核定已启动（unknown 少于全部文档）", 0 <= n_unverified < len(d["docs"]),
      f"{n_unverified}/{len(d['docs'])} 待确认")
check("V1 征求意见稿已标出", n_consultation == 1, f"consultation={n_consultation}")

# ---- 3. chunks 逐字契约回归（重建后哈希与快照一致）----
snap = json.load(open(ROOT / "tests" / "chunks_snapshot.json", encoding="utf-8"))
con = sqlite3.connect(ROOT / "kb" / "kb.sqlite")
rows = con.execute("SELECT chunk_id, doc_id, seq, clause, pages, text FROM chunks ORDER BY chunk_id").fetchall()
con.close()
h = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()
check("V1 chunks 逐字回归（哈希一致）", h == snap["chunks_hash"] and len(rows) == snap["n_chunks"],
      f"{len(rows)} chunks")

# ---- 4. chat 无 history 回归（AC-F6-2 红线，浅验证事件序列）----
frames = []
with httpx.stream("POST", f"{BASE}/api/chat",
                  json={"question": "有限空间作业前需要检测哪些气体？"}, timeout=90) as r:
    check("chat HTTP 200", r.status_code == 200, str(r.status_code))
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

seq = [ev for ev, _ in frames]
sources = next((d["sources"] for ev, d in frames if ev == "sources"), [])
done = next((d for ev, d in frames if ev == "done"), {})
ok_seq = seq[0] == "status" and "sources" in seq and "delta" in seq and seq[-1] == "done"
check("chat SSE 事件序列完整", ok_seq, " -> ".join(dict.fromkeys(seq)))
check("chat sources 含 chunkId 且逐字字段在位",
      all(("chunkId" in s and "excerpt" in s and "full" in s) for s in sources),
      f"{len(sources)} sources")
check("chat done backend 合法", done.get("backend") in ("llm", "retrieval", "no_answer"), str(done))

# ---- 5. 静态资源 ----
r = httpx.get(f"{BASE}/favicon.svg")
check("1.5 favicon 200", r.status_code == 200 and "svg" in r.headers.get("content-type", ""),
      f"{r.status_code} {r.headers.get('content-type', '')}")

print()
n_pass = sum(1 for _, ok in results if ok)
print(f"RESULT: {n_pass}/{len(results)} PASS")
sys.exit(0 if n_pass == len(results) else 1)
