# -*- coding: utf-8 -*-
"""2.4 兜底判据对齐 · 守卫测试（上下文改进计划第 2 期第 4 项，2026-11-05）。

守卫性质（需 9001 本机服务 + .env 真实 Key）：
1. PM-02 口语延续题：旧实现「向量救回正确块但改写未超越原覆盖率」场景，
   sources 展示完美答案块却回「未找到」（引用卡片与答案自相矛盾）。修复后
   backend 必须为 llm，且答案含 30 个工作日/延期复核/3 年关键要素。
2. C1 口语弱命中改写题（合并路径）：不受影响，仍正常作答（回归）。
3. 库外弱命中题：不允许因修复而编造——答案必须含拒答/兜底话术。

用法：.venv/Scripts/python.exe tests/iter6_fallback_test.py [base_url]
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9001"


def ask(question: str) -> dict:
    import httpx
    client = httpx.Client(trust_env=False, timeout=60)
    try:
        with client.stream("POST", BASE_URL.rstrip("/") + "/api/chat",
                           json={"question": question}) as r:
            buf = ""
            for chunk in r.iter_text():
                buf += chunk
    finally:
        client.close()
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
    return {
        "answer": "".join(d.get("text", "") for ev, d in frames if ev == "delta"),
        "backend": (next((d for ev, d in frames if ev == "done"), {}) or {}).get("backend"),
    }


def main() -> int:
    ok_all = True

    # 1. PM-02：兜底判据修复（向量独占路径恢复 BM25 主判据）
    r = ask("特种作业人员的资格证书快到期了，怎么办理延续？")
    ok = r["backend"] == "llm" and "30" in r["answer"] and "延期复核" in r["answer"] and "3" in r["answer"]
    print(("PASS " if ok else "FAIL ") + "PM-02 向量独占兜底判据 | backend=%s" % r["backend"])
    if not ok:
        print("  答案:", r["answer"][:200])
        ok_all = False

    # 2. C1：弱命中改写合并路径回归（合并发生时 primary 是 BM25 版本，零变化）
    r = ask("工地上挖坑底下干活有啥危险要注意的？")
    ok = r["backend"] == "llm" and ("有限空间" in r["answer"] or "空间" in r["answer"])
    print(("PASS " if ok else "FAIL ") + "C1 弱命中改写合并回归 | backend=%s" % r["backend"])
    if not ok:
        print("  答案:", r["answer"][:200])
        ok_all = False

    # 3. 库外弱命中：不允许编造（契约规则 1/4 防线）
    r = ask("塔吊司机证怎么复审？")
    ok = ("未找到" in r["answer"]) or ("未收录" in r["answer"]) or r["backend"] == "no_answer"
    print(("PASS " if ok else "FAIL ") + "库外题拒答防线 | backend=%s" % r["backend"])
    if not ok:
        print("  答案:", r["answer"][:200])
        ok_all = False

    print("\nRESULT: %s" % ("PASS" if ok_all else "FAIL"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
