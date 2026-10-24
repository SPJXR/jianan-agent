# -*- coding: utf-8 -*-
"""0080（GB 55034-2022，openstd 在线阅读导出 PDF）拼贴切片 + 逐页 OCR。

该 PDF 是 openstd 阅读器的防盗版导出：每页正文被切成 6~8 张小图（XObj），
文本层是自定义编码乱码（ToUnicode 缺失），pypdf 直接抽文本不可用。
处理：解析每页内容流的 cm 矩阵，把各切片按位置拼回整页 → Windows OCR。

输出 kb/text/0080.txt（含【第N页】标记，样式与 extract_docs 的 PDF 路一致）。
"""
import io
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "knowledge_base", "docs", "0080_8a4cce0184d54010bea65c5296fc6ead.pdf")
OUT_TXT = os.path.join(BASE, "kb", "text", "0080.txt")
IMG_DIR = os.path.join(BASE, "kb", "ocr_imgs")
PS = os.path.join(BASE, "tools", "ocr_image.ps1")
os.makedirs(IMG_DIR, exist_ok=True)

from pypdf import PdfReader  # noqa: E402
from pypdf.generic import ContentStream  # noqa: E402
from PIL import Image  # noqa: E402
import io as _io  # noqa: E402

SCALE = 2.5  # PDF 点 → 像素（A4 595×842pt → ~1500×2100px，OCR 够用）


def stitch_page(page, index: int) -> str:
    """把一页的全部图片 XObj 按 cm 矩阵拼到画布，返回 PNG 路径。"""
    rect = page.mediabox
    W, H = float(rect.width), float(rect.height)
    canvas = Image.new("RGB", (int(W * SCALE), int(H * SCALE)), "white")

    xobjs = page.get("/Resources", {}).get("/XObject", {})
    cs = ContentStream(page.get_contents(), page.pdf)
    ctm = [1, 0, 0, 1, 0, 0]  # 单位阵
    stack = []
    drawn = 0
    for operands, op in cs.operations:
        # pypdf 操作符是 bytes（str(b'Do') != 'Do'，2026-10-24 踩坑），统一解码
        tag = op.decode("latin-1") if isinstance(op, bytes) else str(op)
        if tag == "q":
            stack.append(list(ctm))
        elif tag == "Q":
            if stack:
                ctm = stack.pop()
        elif tag == "cm" and len(operands) == 6:
            a, b, c, d, e, f = (float(x) for x in operands)
            # 新矩阵 = M × ctm（PDF 语义：先 cm 后 Do，坐标叠加）
            ctm = [
                ctm[0] * a + ctm[2] * b,
                ctm[1] * a + ctm[3] * b,
                ctm[0] * c + ctm[2] * d,
                ctm[1] * c + ctm[3] * d,
                ctm[0] * e + ctm[2] * f + ctm[4],
                ctm[1] * e + ctm[3] * f + ctm[5],
            ]
        elif tag == "Do" and operands:
            name = str(operands[0])
            xobj = xobjs.get(name)
            if xobj is None:
                continue
            xobj = xobj.get_object()
            if xobj.get("/Subtype") != "/Image":
                continue
            try:
                filt = xobj.get("/Filter")
                if filt == "/DCTDecode" or filt == "/JPXDecode":
                    img = Image.open(_io.BytesIO(xobj.get_data()))
                else:
                    # FlateDecode 等裸像素流：Image.open 识别不了（2026-10-24 踩坑：
                    # 每页 8 切片只有 2 张 JPEG，其余 6 张是 8 位灰度裸流被静默跳过），
                    # 按 Width/Height/ColorSpace 用 frombytes 重建
                    w, h = int(xobj["/Width"]), int(xobj["/Height"])
                    cs = xobj.get("/ColorSpace")
                    mode = {"/DeviceGray": "L", "/DeviceRGB": "RGB",
                            "/DeviceCMYK": "CMYK"}.get(str(cs), "L")
                    img = Image.frombytes(mode, (w, h), xobj.get_data())
            except Exception:
                continue
            # 图像单位方形 [0,1]² 经 ctm 映射：宽=|a,c| 高=|b,d|，原点=(e,f)
            a, b, c, d, e, f = ctm
            x0, y0 = e, f
            w_pt = (a ** 2 + b ** 2) ** 0.5 * (1 if a >= 0 else -1)
            h_pt = (c ** 2 + d ** 2) ** 0.5 * (1 if d >= 0 else -1)
            if w_pt <= 0 or h_pt <= 0:
                continue
            # y 轴翻转（PDF 原点在左下）
            x = int(x0 * SCALE)
            y = int((H - y0 - abs(h_pt)) * SCALE)
            w = int(abs(w_pt) * SCALE)
            h = int(abs(h_pt) * SCALE)
            if w <= 0 or h <= 0 or x < -50 or y < -50:
                continue
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img = img.resize((w, h))
            canvas.paste(img, (max(0, x), max(0, y)))
            drawn += 1
    out = os.path.join(IMG_DIR, f"0080_p{index}.png")
    canvas.save(out)
    return out + f" (tiles={drawn})"


def ocr(png: str) -> str:
    out_txt = png + ".ocr.txt"
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS,
         "-Image", png, "-OutText", out_txt],
        capture_output=True, timeout=300)
    if os.path.exists(out_txt):
        return open(out_txt, "rb").read().decode("utf-8", "replace")
    return ""


def main():
    r = PdfReader(SRC)
    print(f"页数: {len(r.pages)}")
    parts = []
    total = 0
    for i, page in enumerate(r.pages, 1):
        png = stitch_page(page, i)
        text = ocr(os.path.join(IMG_DIR, f"0080_p{i}.png"))
        total += len(text)
        print(f"  p{i}: OCR {len(text)} 字 | {png.split(os.sep)[-1]}")
        if text.strip():
            parts.append(f"【第{i}页】\n{text.strip()}")
    open(OUT_TXT, "w", encoding="utf-8").write("\n".join(parts))
    print(f"合计 {total} 字 → {OUT_TXT}")
    print("预览:", parts[0][:200] if parts else "(空)")


if __name__ == "__main__":
    main()
