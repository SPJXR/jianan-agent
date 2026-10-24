# -*- coding: utf-8 -*-
"""对 0067（docx 内嵌流程图 jpeg）与 0003/0004（扫描 PDF）做 OCR，
写入 kb/text/ 下对应 txt。"""
import io
import os
import subprocess
import sys
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = r"D:\wdagent\2026-09-19-17-37-04"
PS = os.path.join(BASE, "tools", "ocr_image.ps1")
IMG_DIR = os.path.join(BASE, "kb", "ocr_imgs")
TEXT_DIR = os.path.join(BASE, "kb", "text")
os.makedirs(IMG_DIR, exist_ok=True)


def ocr(img_path, out_txt):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS,
         "-Image", img_path, "-OutText", out_txt],
        capture_output=True, text=True, timeout=300, encoding="gbk", errors="replace")
    tail = (r.stdout or "").strip().splitlines()
    tail = tail[-1] if tail else ""
    return tail


# ---- 0067: docx 里的 image1.jpeg ----
# 注意：0067.docx 本体只有标题行（流程图是内嵌图片）。extract_docs.py 每次重跑都会
# 把 kb/text/0067.txt 覆盖回空壳（2026-10-24 教训：覆盖后 0067 从索引消失、A9 回归）。
# 因此标题头部必须在此固化——凡重跑 extract_docs 后，必须重跑本脚本。
HEADER_0067 = (
    "附件3\n建设项目开工“一件事”办理流程（示例）\n"
    "流程说明：建设单位可通过线上（政务服务平台工程建设项目审批管理系统）"
    "或线下（政务服务中心工程建设项目审批综合服务窗口）申请，"
    "综合窗口受理并联审批以下事项。\n"
)
docx = os.path.join(BASE, "knowledge_base", "docs", "0067_E881602E1F43E30FF348A8F0AF5EDAB1.docx")
img = os.path.join(IMG_DIR, "0067.jpeg")
with zipfile.ZipFile(docx) as z:
    open(img, "wb").write(z.read("word/media/image1.jpeg"))
print("0067:", ocr(img, os.path.join(TEXT_DIR, "0067.txt")))
_ocr67 = open(os.path.join(TEXT_DIR, "0067.txt"), encoding="utf-8").read()
open(os.path.join(TEXT_DIR, "0067.txt"), "w", encoding="utf-8").write(HEADER_0067 + _ocr67)

# ---- 0003 / 0004: PDF 内嵌图 ----
from pypdf import PdfReader

for doc_id in ("0003", "0004"):
    pdfs = [f for f in os.listdir(os.path.join(BASE, "knowledge_base", "docs")) if f.startswith(doc_id + "_")]
    pdf = os.path.join(BASE, "knowledge_base", "docs", pdfs[0])
    r = PdfReader(pdf)
    parts = []
    for pi, page in enumerate(r.pages, 1):
        try:
            for ii, imf in enumerate(page.images):
                ext = os.path.splitext(imf.name)[1] or ".png"
                ip = os.path.join(IMG_DIR, f"{doc_id}_p{pi}_{ii}{ext}")
                with open(ip, "wb") as f:
                    f.write(imf.data)
                res = ocr(ip, ip + ".ocr.txt")
                print(f"{doc_id} p{pi} img{ii}: size={os.path.getsize(ip)} {res}")
                txt = open(ip + ".ocr.txt", encoding="utf-8").read() if os.path.exists(ip + ".ocr.txt") else ""
                parts.append(f"【第{pi}页】\n{txt}")
        except Exception as e:
            print(f"{doc_id} p{pi} ERR {type(e).__name__}: {e}")
    full = "\n\n".join(parts).strip()
    open(os.path.join(TEXT_DIR, doc_id + ".txt"), "w", encoding="utf-8").write(full)
    print(f"{doc_id} total chars={len(full)}")
