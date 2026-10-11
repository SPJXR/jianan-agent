# -*- coding: utf-8 -*-
"""解析 knowledge_base/docs 下 34 份文档为纯文本（v2，采用 phase1 验证过的链路）。

- .doc  : Word COM 先转 .docx（FileFormat=16），再按 .docx 链路解析
- .docx : python-docx 按正文顺序抽取段落与表格
- .pdf  : pypdf 逐页抽取，页间插入 【第N页】 标记
输出：kb/text/{doc_id}.txt 与 kb/extract_meta.json
"""
import json
import os
import re
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(BASE, "knowledge_base", "docs")
TEXT_DIR = os.path.join(BASE, "kb", "text")
TMP_DOCX = os.path.join(BASE, "kb", "tmp_docx")
META_PATH = os.path.join(BASE, "kb", "extract_meta.json")

os.makedirs(TEXT_DIR, exist_ok=True)
os.makedirs(TMP_DOCX, exist_ok=True)


def docx_to_text(path):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    parts = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = Paragraph(child, doc).text.strip()
            if t:
                parts.append(t)
        elif tag == "tbl":
            tbl = Table(child, doc)
            for row in tbl.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
    return "\n".join(parts)


def pdf_to_text(path):
    from pypdf import PdfReader

    r = PdfReader(path)
    pages = []
    for i, page in enumerate(r.pages, 1):
        t = (page.extract_text() or "").strip()
        if t:
            pages.append(f"【第{i}页】\n{t}")
    return "\n".join(pages), len(r.pages)


def guess_title(filename, text):
    head = text[:800]
    m = re.findall(r"《([^《》]{4,60})》", head)
    if m:
        return m[0]
    kw = ("法", "条例", "规定", "办法", "细则", "标准", "规范", "导则", "指南",
          "手册", "大纲", "目录", "通知", "意见", "方案", "公告", "决定", "流程", "清单")
    for line in head.splitlines()[:15]:
        line = line.strip().strip("　").strip()
        line = re.sub(r"^【第\d+页】\s*", "", line)
        line = re.sub(r"^-\s*\d+\s*-\s*$", "", line)
        if 6 <= len(line) <= 60 and any(k in line for k in kw):
            return line
    return os.path.splitext(filename)[0]


def main():
    files = sorted(f for f in os.listdir(DOCS) if f.lower().endswith((".doc", ".docx", ".pdf")))
    meta = {}
    word = None
    doc_targets = [f for f in files if f.lower().endswith(".doc")]
    if doc_targets:
        import pythoncom
        from win32com import client as win32_client
        pythoncom.CoInitialize()
        word = win32_client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
    try:
        for fn in files:
            doc_id = fn[:4]
            src = os.path.join(DOCS, fn)
            out = os.path.join(TEXT_DIR, doc_id + ".txt")
            kind = fn.rsplit(".", 1)[-1].lower()
            entry = {"filename": fn, "kind": kind, "status": "ok", "pages": None, "chars": 0}
            try:
                if kind == "doc":
                    dst = os.path.join(TMP_DOCX, doc_id + ".docx")
                    doc = word.Documents.Open(os.path.abspath(src), ReadOnly=True,
                                              AddToRecentFiles=False, Visible=False)
                    doc.SaveAs2(os.path.abspath(dst), FileFormat=16)  # wdFormatDocumentDefault
                    doc.Close(False)
                    text = docx_to_text(dst)
                elif kind == "docx":
                    text = docx_to_text(src)
                elif kind == "pdf":
                    text, npages = pdf_to_text(src)
                    entry["pages"] = npages
                else:
                    continue
                text = text.replace("\r\n", "\n").replace("\x00", "").strip()
                entry["chars"] = len(text)
                open(out, "w", encoding="utf-8").write(text)
                if len(text) < 200:
                    entry["status"] = "low_text"
                entry["title"] = guess_title(fn, text)
            except Exception as e:
                entry["status"] = "error"
                entry["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            meta[doc_id] = entry
            print(f"[{doc_id}] {entry['status']:8s} chars={entry['chars']:7d} title={entry.get('title', '')}")
    finally:
        if word is not None:
            word.Quit()
    json.dump(meta, open(META_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    ok = sum(1 for v in meta.values() if v["status"] == "ok")
    print(f"\ndone: {ok}/{len(meta)} ok, meta -> {META_PATH}")


if __name__ == "__main__":
    main()
