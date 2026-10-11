# -*- coding: utf-8 -*-
"""Phase1 可行性实测：Word COM 转换 .doc -> .docx，再抽文本"""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path

DOCS = Path(r"C:/Users/30832/WorkBuddy/2026-09-19-17-37-04/knowledge_base/docs")
CONVERT_DIR = Path(r"C:/Users/30832/WorkBuddy/2026-09-19-17-37-04/tests/converted")
CONVERT_DIR.mkdir(parents=True, exist_ok=True)

targets = [
    "0001_D2A0AFEC10FC599BDE6F1677484C05EE.doc",
    "0005_W020210126100808.doc",
    "0074_39dd9349-1a20-4d98-bcee-3429373eaea3.doc",
]

import pythoncom
from win32com import client as win32_client

result = {}
pythoncom.CoInitialize()
try:
    word = win32_client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        for name in targets:
            src = DOCS / name
            dst = CONVERT_DIR / (Path(name).stem + ".docx")
            info = {}
            try:
                doc = word.Documents.Open(str(src), ReadOnly=True)
                doc.SaveAs2(str(dst), FileFormat=16)  # 16 = wdFormatDocumentDefault (docx)
                doc.Close(False)
                info["converted"] = str(dst.exists())
                # 转换后解析
                from docx import Document
                d = Document(str(dst))
                paras = [p.text for p in d.paragraphs if p.text.strip()]
                # 表格内容也抽出
                table_texts = []
                for t in d.tables:
                    for row in t.rows:
                        cells = [c.text.strip() for c in row.cells if c.text.strip()]
                        if cells:
                            table_texts.append(" | ".join(cells))
                full = "\n".join(paras)
                info["paragraphs"] = len(paras)
                info["tables"] = len(d.tables)
                info["para_chars"] = len(full)
                info["table_rows"] = len(table_texts)
                info["table_chars"] = len("\n".join(table_texts))
                info["sample"] = full.strip().replace("\n", " ")[:150]
            except Exception as e:
                info["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            result[name] = info
    finally:
        word.Quit()
finally:
    pythoncom.CoUninitialize()

out = Path(r"C:/Users/30832/WorkBuddy/2026-09-19-17-37-04/phase1_doc_com_test.json")
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("WROTE", out)
