# -*- coding: utf-8 -*-
"""长会话截断 POC（2026-11-15，Mem0 启示：会话摘要候选⑥的前置实测）。

背景：F6 前端 buildHistory 只发最近 3 轮（turns.slice(-3)），服务端
_clean_history raw[:6] 双保险——截断方向正确（无「留最早丢最新」bug）。
真实风险：主题被挤出窗口后，末轮指代问题失去上下文。

POC 设计（先证明有病再吃药，ADR-002 纪律）：
- 3 个场景（MT-01/02/05 改造）：第 1 轮主题铺垫 + 4 轮**无关话题**（真实
  服务端问答生成 history）+ 末轮指代问题——history 窗口只剩无关话题；
- 对照组：短 history（1 轮铺垫 + 同一末轮）；
- 判定：末轮答案的关键词组命中（归一化子串）+ 是否拒答。
若长组失败、短组成功 → 实测失败成立 → 会话摘要候选⑥升级施工；
否则关闭候选，登记证据。

用法：先起 9001 服务，再
    .venv/Scripts/python.exe tools/poc_history_overflow.py [--base ...]
"""
import argparse
import io
import json
import re
import sys
import time

import httpx

BASE = sys.stdout  # stdout 包装只在 CLI 入口做（import 时不得动流）

# 场景：(主题铺垫, [无关铺垫×4], 末轮指代, 关键词组)
SCENARIOS = [
    {
        "id": "A-MT05",
        "topic": "哪些施工工艺是禁止使用的？",
        "filler": ["安全帽的有效期一般是多久？",
                   "有限空间作业前需要检测哪些气体？",
                   "深基坑支护有哪些常见形式？",
                   "脚手架搭设需要注意什么？"],
        "final": "钢筋那个有什么替代做法？",
        "kw": [["冷弯"]],
    },
    {
        "id": "B-MT02",
        "topic": "建筑施工特种作业人员如何取得资格证书？",
        "filler": ["有限空间作业前需要检测哪些气体？",
                   "哪些工程需要办理消防设计审查？",
                   "施工现场临时用电有哪些要求？",
                   "塔式起重机安装需要什么资质？"],
        "final": "年龄上限是多少？超了怎么办？",
        "kw": [["60", "六十"], ["体检"]],
    },
    {
        "id": "C-MT01",
        "topic": "有限空间作业前需要检测哪些气体？",
        "filler": ["哪些工程属于要办消防设计审查的特殊建设工程？",
                   "安全帽的有效期一般是多久？",
                   "建筑施工特种作业人员如何取得资格证书？",
                   "哪些施工工艺是禁止使用的？"],
        "final": "那检测的频次有什么要求？",
        "kw": [["30min", "30 分钟"], ["重新", "再次进入"]],
    },
]

REFUSAL_MARKERS = ("未找到", "未收录")


def norm(s):
    return re.sub(r"\s+", "", s or "")


def ask(client, base, question, history):
    body = {"question": question}
    if history:
        body["history"] = history
    with client.stream("POST", f"{base}/api/chat", json=body) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
    frames = []
    for f in buf.split("\n\n"):
        ev, data = "", ""
        for ln in f.splitlines():
            if ln.startswith("event:"):
                ev = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        if data:
            try:
                frames.append((ev, json.loads(data)))
            except Exception:
                pass
    text = "".join(d.get("text", "") for ev, d in frames if ev == "delta")
    done = next((d for ev, d in frames if ev == "done"), {})
    return text, done


def ask_checked(client, base, question, history):
    """带重试的问答：区分「POC 请求故障」（空响应/无 done）与系统真实表现。
    首轮实测 C 短组曾出现一次空响应，若不重试会被误判为「两组均失败」。"""
    last = ("", {})
    for attempt in range(2):
        t, d = ask(client, base, question, history)
        last = (t, d)
        if d.get("backend") == "llm" and t.strip():
            return t, d
        time.sleep(1)
    return last


def main():
    # stdout 包装只在 CLI 入口做（importlib 加载做单测时不碰流）
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:9001")
    args = ap.parse_args()
    client = httpx.Client(trust_env=False, timeout=90)

    print("# 长会话截断 POC（Mem0 会话摘要候选⑥的前置实测）\n")
    print("> 长组 = 主题铺垫 + 4 轮无关话题 + 指代末轮（主题挤出 6 条窗口）")
    print("> 短组 = 1 轮铺垫 + 同一末轮（对照）\n")

    any_failure = False
    for sc in SCENARIOS:
        print(f"===== 场景 {sc['id']} =====")
        # --- 长组：真实多轮（铺垫 + 4 无关 + 末轮）---
        history = []
        a_topic, _ = ask_checked(client, args.base, sc["topic"], [])
        history.append({"role": "user", "content": sc["topic"]})
        history.append({"role": "assistant", "content": a_topic[:500]})
        for fq in sc["filler"]:
            a_fill, _ = ask_checked(client, args.base, fq, history)
            history.append({"role": "user", "content": fq})
            history.append({"role": "assistant", "content": a_fill[:500]})
        # 前端口径：只带最近 3 轮（6 条）——主题已不在其中
        long_hist = history[-6:]
        a_long, d_long = ask_checked(client, args.base, sc["final"], long_hist)
        # --- 短组对照：同铺垫 + 末轮 ---
        a_short, d_short = ask_checked(client, args.base, sc["final"], history[:2])

        def judge(ans):
            n = norm(ans)
            hits = [any(norm(w) in n for w in g) for g in sc["kw"]]
            refused = any(m in ans for m in REFUSAL_MARKERS)
            return hits, refused
        hl, rl = judge(a_long)
        hs, rs = judge(a_short)
        print(f"  长组：backend={d_long.get('backend')} kw={hl} 拒答={rl} "
              f"答案头={a_long[:90]!r}")
        print(f"  短组：backend={d_short.get('backend')} kw={hs} 拒答={rs} "
              f"答案头={a_short[:90]!r}")
        poc_error = (d_long.get("backend") != "llm" or
                     d_short.get("backend") != "llm")
        if poc_error:
            print("  → POC 请求故障（重试后仍无有效响应），不计入结论")
            continue
        long_ok = all(hl) and not rl
        short_ok = all(hs) and not rs
        if not long_ok and short_ok:
            any_failure = True
            print("  → **实测失败**：短组成功而长组失败（主题挤出窗口导致）")
        elif not long_ok and not short_ok:
            print("  → 两组均失败（非截断问题，另查）")
        else:
            print("  → 长组仍成功（截断未致失败）")
        print()

    print("===== 结论 =====")
    if any_failure:
        print("存在实测失败 → 会话摘要候选⑥具备施工依据（溢出主题行方案）。")
    else:
        print("无实测失败 → 会话摘要候选⑥关闭/维持登记，登记本 POC 证据。")


if __name__ == "__main__":
    main()
