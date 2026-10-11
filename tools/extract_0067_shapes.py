# -*- coding: utf-8 -*-
"""提取 0067（开工一件事办理流程图）中形状/文本框/画布内的文字"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SRC = r"D:\wdagent\2026-09-19-17-37-04\knowledge_base\docs\0067_E881602E1F43E30FF348A8F0AF5EDAB1.docx"
OUT = r"D:\wdagent\2026-09-19-17-37-04\kb\text\0067.txt"

import pythoncom
from win32com import client as win32_client

pieces = []


def walk_shapes(shapes, prefix=""):
    for i in range(1, shapes.Count + 1):
        shp = shapes.Item(i)
        try:
            if shp.Type == 6:  # msoGroup
                walk_shapes(shp.GroupItems, prefix + f"G{i}/")
                continue
            if shp.Type == 20 or shp.Type == 7:  # canvas / embedded
                try:
                    walk_shapes(shp.CanvasItems, prefix + f"C{i}/")
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if shp.TextFrame.HasText:
                t = shp.TextFrame.TextRange.Text.strip()
                if t:
                    pieces.append(f"[{prefix}shape{i}]\n{t}")
        except Exception:
            pass


pythoncom.CoInitialize()
word = win32_client.DispatchEx("Word.Application")
word.Visible = False
word.DisplayAlerts = 0
try:
    doc = word.Documents.Open(SRC, ReadOnly=True, AddToRecentFiles=False, Visible=False)
    try:
        walk_shapes(doc.Shapes)
        for i in range(1, doc.InlineShapes.Count + 1):
            try:
                t = doc.InlineShapes.Item(i).TextFrame.TextRange.Text.strip()
                if t:
                    pieces.append(f"[inline{i}]\n{t}")
            except Exception:
                pass
    finally:
        doc.Close(False)
finally:
    word.Quit()

text = "\n\n".join(pieces)
open(OUT, "w", encoding="utf-8").write(text)
print(f"shapes_text_chars={len(text)} pieces={len(pieces)}")
print(text[:800])
