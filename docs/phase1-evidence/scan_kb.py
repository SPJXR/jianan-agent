# -*- coding: utf-8 -*-
"""快速摸底 knowledge_base/docs 下所有文档的主题与文本量"""
import os, re, sys, zipfile
import warnings
warnings.filterwarnings("ignore")

KB = r"C:\Users\30832\WorkBuddy\2026-09-19-17-37-04\knowledge_base\docs"

def docx_head(path, n=120):
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)
        return " ".join(t for t in texts if t.strip())[:n], len("".join(texts))
    except Exception as e:
        return f"<docx err {e}>", 0

def doc_head(path, n=120):
    try:
        raw = open(path, "rb").read()
        # .doc OLE: try UTF-16LE runs then GBK runs
        cand = []
        u = re.findall(rb"(?:[\x20-\x7e\x80-\xff][\x00]){6,}", raw)
        for m in u[:400]:
            try:
                s = m.decode("utf-16-le", "ignore")
                s2 = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9，。、；：（）()《》\-]", "", s)
                if len(s2) >= 4:
                    cand.append(s2)
            except Exception:
                pass
        if cand:
            return " ".join(cand)[:n], sum(len(c) for c in cand)
        g = re.findall(rb"[\x20-\x7e\xb0-\xf7]{8,}", raw)
        cand = [m.decode("gbk", "ignore") for m in g[:200]]
        return " ".join(cand)[:n], sum(len(c) for c in cand)
    except Exception as e:
        return f"<doc err {e}>", 0

def pdf_head(path, n=120):
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        pages = len(r.pages)
        txt = ""
        for p in r.pages[:2]:
            txt += (p.extract_text() or "")
        clean = re.sub(r"\s+", " ", txt)[:n]
        return f"[{pages}页] {clean}", pages
    except Exception as e:
        return f"<pdf err {e}>", 0

rows = []
for fn in sorted(os.listdir(KB)):
    p = os.path.join(KB, fn)
    if fn.endswith(".docx"):
        head, amt = docx_head(p)
        kind = "docx"
    elif fn.endswith(".doc"):
        head, amt = doc_head(p)
        kind = "doc"
    elif fn.endswith(".pdf"):
        head, amt = pdf_head(p)
        kind = "pdf"
    else:
        continue
    head = re.sub(r"\s+", " ", head).strip()
    rows.append((kind, fn, head[:100]))

print(f"total files: {len(rows)}")
for kind, fn, head in rows:
    print(f"[{kind}] {fn}")
    print(f"    {head}")
