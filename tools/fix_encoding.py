# -*- coding: utf-8 -*-
"""修复 dev_doc_fulltext.txt 的二次编码错乱（UTF-8 文本曾被按 GBK 解码后再存为 UTF-8）"""
import sys

SRC = r"D:\wdagent\2026-09-19-17-37-04\dev_doc_fulltext.txt"
DST = r"D:\wdagent\2026-09-19-17-37-04\dev_doc_fulltext_utf8.txt"

raw = open(SRC, encoding="utf-8", errors="replace").read()
# 反向恢复：错乱字符 -> GBK 字节（即原始 UTF-8 字节）-> 按 UTF-8 解码
recovered = raw.encode("gbk", errors="replace").decode("utf-8", errors="replace")
open(DST, "w", encoding="utf-8").write(recovered)
print(f"src_chars={len(raw)} dst_chars={len(recovered)}")
print("preview:", recovered[:200])
