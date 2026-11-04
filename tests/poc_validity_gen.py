# -*- coding: utf-8 -*-
"""3.3 时效状态进上下文 · A/B 探针（上下文改进计划第 3 期第 1 项，2026-11-04）。

目的：0070（征求意见稿）经 ADR-006 检索降权后通常进不了 top-8，端到端评测
难以自然复现「征求意见稿与试行版同处一个上下文」的场景。本脚本绕过检索，
手工把 0069（trial）/0070（consultation）/0078（effective）的块组装成 sources，
直接调 llm.stream_chat，观察生成侧对时效状态的表述。

改动前（无〔状态〕标注）：预期 LLM 把两个版本平等对待或含糊其辞；
改动后：预期明确「以 0069 试行版为准，0070 征求意见稿未生效」。

用法（改前/改后各跑一次，输出存 docs/eval/results/）：
    .venv/Scripts/python.exe tests/poc_validity_gen.py docs/eval/results/val_ab_probe_before.txt
    .venv/Scripts/python.exe tests/poc_validity_gen.py docs/eval/results/val_ab_probe_after.txt
"""
import asyncio
import io
import os
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app import config, llm  # noqa: E402

DB = os.path.join(BASE, "kb", "kb.sqlite")
QUESTION = ("有限空间作业安全指南现在有征求意见稿和试行版两个版本，"
            "施工应该以哪个为准？依据是什么？")


def pick_snippets() -> list:
    """0069/0070/0078 各取一个含「检测」的块（无则取首块），组装为 sources 载荷。"""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    out = []
    for i, doc_id in enumerate(("0069", "0070", "0078"), 1):
        doc = con.execute(
            "select title, valid_status from docs where doc_id=?", (doc_id,)).fetchone()
        row = con.execute(
            "select chunk_id, clause, pages, text from chunks where doc_id=? "
            "and text like '%检测%' order by seq limit 1", (doc_id,)).fetchone()
        if row is None:
            row = con.execute(
                "select chunk_id, clause, pages, text from chunks where doc_id=? "
                "order by seq limit 1", (doc_id,)).fetchone()
        out.append({
            "no": i,
            "docId": doc_id,
            "title": doc["title"],
            "clause": (row["clause"] or "").strip(),
            "pages": row["pages"] or "",
            "validStatus": (doc["valid_status"] or "").strip(),
            "full": row["text"].strip(),
        })
    con.close()
    return out


async def main(out_path: str) -> int:
    snippets = pick_snippets()
    lines = ["Q: " + QUESTION, "", "---- 上下文片段头（改前无〔状态〕/改后有〔状态〕）----"]
    for s in snippets:
        head = f"[{s['no']}] 《{s['title']}》{s['clause']}".strip()
        lines.append(f"  {head}")
    lines += ["", "---- LLM 回答 ----"]
    buf = ""
    try:
        async for delta in llm.stream_chat(snippets, QUESTION, role="default"):
            buf += delta
    except llm.LLMError as e:
        lines.append(f"[LLMError {e.code}] {e.message}")
    lines.append(buf if buf else "(空回答)")
    text = "\n".join(lines)
    print(text)
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\n已写入: {out_path}")
    return 0


if __name__ == "__main__":
    if not config.llm_configured():
        print("LLM 未配置（.env 缺 LLM_API_KEY），无法探针")
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "")))
