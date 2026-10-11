# -*- coding: utf-8 -*-
"""导出每份已抽取文本的前 8 个非空行 + 尾 2 行，供人工核定标题用"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEXT_DIR = r"D:\wdagent\2026-09-19-17-37-04\kb\text"
OUT = r"D:\wdagent\2026-09-19-17-37-04\kb\heads_for_review.txt"

lines_out = []
for fn in sorted(os.listdir(TEXT_DIR)):
    if not fn.endswith(".txt"):
        continue
    text = open(os.path.join(TEXT_DIR, fn), encoding="utf-8").read()
    nonempty = [l.strip() for l in text.splitlines() if l.strip()]
    head = nonempty[:8]
    tail = nonempty[-2:]
    lines_out.append(f"===== {fn} =====")
    for l in head:
        lines_out.append("  " + l[:90])
    lines_out.append("  ......")
    for l in tail:
        lines_out.append("  " + l[:90])
    lines_out.append("")

open(OUT, "w", encoding="utf-8").write("\n".join(lines_out))
print("WROTE", OUT)
