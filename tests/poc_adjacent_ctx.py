# -*- coding: utf-8 -*-
"""3.1 相邻条款定向注入 · POC（上下文改进计划第 3 期第 1 项，2026-11-06）。

验证假设：块尾断裂（，、；：）的块，其 next 块含答案关键词时，注入相邻条款
可让 LLM 补全跨块语义（PM-06 一类高层在 id=202，源块 id=201 尾「；」断裂）。

A/B：同检索结果，加/不加相邻注入，各调一次 llm.stream_chat 对比。

用法：.venv/Scripts/python.exe tests/poc_adjacent_ctx.py [out_path]
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))

from app import config, llm, retrieval  # noqa: E402

BROKEN_TAIL = ("，", "、", "；", "：", "（")

CASES = [
    ("PM-06", "哪些工程属于特殊建设工程，需要办理消防设计审查？", ["一类高层"]),
    ("SAF-08", "有限空间内作业使用行灯照明电压有什么限制？", ["36V", "36 V"]),
]


def assemble(question: str):
    """复刻 main.py 装配：primary + supplement，返回 context_hits。"""
    hits, _top = retrieval.hybrid_search(question, config.RECALL_WINDOW)
    primary = hits[:config.RETRIEVAL_TOP_K]
    docs = {h["doc_id"] for h in primary}
    supp = [h for h in hits[config.RETRIEVAL_TOP_K:] if h["doc_id"] in docs][:6]
    return primary + supp


def sources_payload(hits):
    out = []
    for i, h in enumerate(hits, 1):
        text = h["text"].strip()
        out.append({
            "no": i, "docId": h["doc_id"], "chunkId": h["chunk_id"],
            "title": h["title"], "clause": (h.get("clause") or "").strip(),
            "pages": h.get("pages") or "",
            "validStatus": (h.get("valid_status") or "").strip(),
            "full": text, "_raw": h,
        })
    return out


def with_adjacent(sources):
    """给块尾断裂的源块挂上 next 文本（去重：next 已在上下文则不挂）。"""
    in_ctx = {s["chunkId"] for s in sources}
    n = 0
    for s in sources:
        tail = s["full"].rstrip()[-1:] if s["full"].rstrip() else ""
        if tail not in BROKEN_TAIL:
            continue
        ctx = retrieval.get_chunk_context(s["chunkId"])
        nxt = (ctx or {}).get("next")
        if not nxt or nxt is None:
            continue
        # 取 next 块全文需要 chunk_id——get_chunk_context 只给了 seq/clause/text，
        # 直接用其返回的 text（即相邻块全文，逐字）。
        s["adjacent_next"] = nxt["text"].strip()
        n += 1
    return n


async def ask(question, sources):
    buf = ""
    async for delta in llm.stream_chat([s for s in sources], question, role="default"):
        buf += delta
    return buf


async def main():
    for tag, q, want in CASES:
        hits = assemble(q)
        base = sources_payload(hits)
        n = with_adjacent(base)
        # 对照组：去掉 adjacent
        ctrl = [{k: v for k, v in s.items() if k != "adjacent_next"} for s in base]
        print("=" * 20, tag, q)
        print("  断裂注入块数:", n, [s["chunkId"] for s in base if "adjacent_next" in s])
        a = await ask(q, ctrl)
        print("  [对照·无相邻] 关键词命中:", {w: (w in a) for w in want})
        b = await ask(q, base)
        print("  [注入·相邻]   关键词命中:", {w: (w in b) for w in want})
        print("  [对照] 答案前200:", a[:200].replace("\n", " "))
        print("  [注入] 答案前200:", b[:200].replace("\n", " "))
        print()


if __name__ == "__main__":
    if not config.llm_configured():
        print("LLM 未配置")
        sys.exit(2)
    asyncio.run(main())
