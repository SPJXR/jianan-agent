# -*- coding: utf-8 -*-
"""Phase1 可行性实测：PDF 文本层检测 + docx 解析"""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path

DOCS = ROOT / "knowledge_base/docs"
result = {}

# ---- 1. pypdf: 全部 6 份 PDF 提取 ----
from pypdf import PdfReader
for pdf_file in sorted(DOCS.glob("*.pdf")):
    info = {"size_mb": round(pdf_file.stat().st_size / 1048576, 2)}
    try:
        reader = PdfReader(str(pdf_file))
        info["pages"] = len(reader.pages)
        texts = []
        for page in reader.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception as e:
                texts.append(f"[PAGE_ERR:{type(e).__name__}]")
        full = "\n".join(texts)
        cjk = sum(1 for c in full if "\u4e00" <= c <= "\u9fff")
        info["total_chars"] = len(full.strip())
        info["cjk_chars"] = cjk
        sample = full.strip().replace("\n", " ")[:120]
        info["sample"] = sample
        info["verdict"] = "TEXT_OK" if cjk > 200 else "NO_TEXT_LAYER(SCAN?)"
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    result[pdf_file.name] = info

# ---- 2. python-docx: 抽查 2 份 docx ----
from docx import Document
ROOT = Path(__file__).resolve().parent.parent   # 仓库根：不写死任何人的本机路径
for docx_file in [DOCS / "0002_28e4f67b-d262-4020-bd50-142ef860bcee.docx",
                  DOCS / "0070_88ABAF4D94E6EE16C6F5CF1C5C4E1CC4.docx"]:
    info = {}
    try:
        d = Document(str(docx_file))
        paras = [p.text for p in d.paragraphs if p.text.strip()]
        tables = len(d.tables)
        full = "\n".join(paras)
        info["paragraphs"] = len(paras)
        info["tables"] = tables
        info["total_chars"] = len(full)
        info["sample"] = full.strip().replace("\n", " ")[:120]
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    result[docx_file.name] = info

# ---- 3. python-docx 尝试读 .doc（预期失败，验证必要性）----
doc_file = DOCS / "0001_D2A0AFEC10FC599BDE6F1677484C05EE.doc"
info = {}
try:
    d = Document(str(doc_file))
    info["unexpected_success"] = len(d.paragraphs)
except Exception as e:
    info["error"] = f"{type(e).__name__}: {str(e)[:150]}"
result[doc_file.name] = info

out = ROOT / "phase1_pdf_docx_test.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("WROTE", out)
