# -*- coding: utf-8 -*-
"""检查 0067 docx 内部结构：图形类型与文本框内容"""
import io
import sys
import zipfile
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
SRC = r"D:\wdagent\2026-09-19-17-37-04\knowledge_base\docs\0067_E881602E1F43E30FF348A8F0AF5EDAB1.docx"

z = zipfile.ZipFile(SRC)
for n in z.namelist():
    print(n, z.getinfo(n).file_size)

xml = z.read("word/document.xml").decode("utf-8", "ignore")
print("drawing:", xml.count("<w:drawing"), "pic:", xml.count("<pic:pic"),
      "smartart(dgm):", xml.count(":dgm"), "txbxContent:", xml.count("txbxContent"),
      "vml:", xml.count("<v:"))

# 提取所有文本框 txbxContent 内的文字
boxes = re.findall(r"<w:txbxContent>(.*?)</w:txbxContent>", xml, re.S)
print("textbox count:", len(boxes))
out = []
for b in boxes:
    ts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", b)
    t = "".join(ts).strip()
    if t:
        out.append(t)
open(r"D:\wdagent\2026-09-19-17-37-04\kb\text\0067.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE 0067.txt chars:", sum(len(t) for t in out))
for t in out[:40]:
    print(" |", t[:80])
