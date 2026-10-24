# -*- coding: utf-8 -*-
"""政府网页正文入库工具（B-4 扩充流水线补充通道）。

适用：来源是政府网站 HTML 转载页（无 doc/docx/pdf 原件可下载）时，
提取正文存 kb/text/{doc_id}.txt，并在 kb/web_sources.json 登记来源 URL，
供来源页展示与半年度时效复查。原 doc/docx/pdf 渠道仍走 extract_docs.py。

用法：
    .venv/Scripts/python.exe tools/ingest_web.py --url <URL> --id 0077 \
        --title "标题" --category 分类 --valid effective \
        --note "来源说明" [--file saved.html]

规则：
- 正文提取：去 script/style/nav，取含正文的容器（按最长文本块启发式）
- 落库前人工核对：打印前 300 字 + 字符数，正文 <500 字拒绝入库
- 登记写入 kb/docs_meta.json（不覆盖已有键）与 kb/web_sources.json（追加）
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_DIR = os.path.join(BASE, "kb", "text")
META_PATH = os.path.join(BASE, "kb", "docs_meta.json")
WEB_SRC_PATH = os.path.join(BASE, "kb", "web_sources.json")


def strip_html(html: str) -> str:
    html = re.sub(r"<(script|style|head|nav|footer)[^>]*>.*?</\1>", " ", html,
                  flags=re.S | re.I)
    # 块级标签转换行，便于段落划分
    html = re.sub(r"</(p|div|li|h[1-6]|tr|td)>", "\n", html, flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", html)
    import html as h
    text = h.unescape(text)
    lines = [re.sub(r"[ \t\u3000]+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def main_body(text: str) -> str:
    """取最长的连续正文块：政府转载页正文通常在 800 字以上且含"第X条/一、二、"。"""
    paras = text.splitlines()
    best_start, best_len, cur_start, cur_len = 0, 0, 0, 0
    for i, p in enumerate(paras):
        if len(p) >= 15 or re.match(r"^[一二三四五六七八九十]+、|^（[一二三四五六七八九十]+）|^第[一二三四五六七八九十百千\d]+条", p):
            if cur_len == 0:
                cur_start = i
            cur_len += len(p)
        else:
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
            cur_start, cur_len = 0, 0
    if cur_len > best_len:
        best_start, best_len = cur_start, cur_len
    return "\n".join(paras[best_start:best_start + (4000 if best_len else 0)]).strip()


def truncate_tail(text: str, end_re: str) -> str:
    """截掉正文之后的"相关推荐/上一篇"等页面尾部内容（2026-10-24 0077 教训：
    云南厅页面正文后挂着《内河运输船舶重大事故隐患判定标准》全文，整页入库
    导致跨行业语料污染——检索会把交通部标准当住建答案的引用来源）。"""
    if not end_re:
        return text
    m = re.search(end_re, text)
    if m and m.start() > 300:  # 防误伤：截断点必须离开头足够远
        return text[:m.start()].rstrip()
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--id", required=True, help="4 位文档编号，如 0077")
    ap.add_argument("--title", required=True)
    ap.add_argument("--category", required=True)
    ap.add_argument("--valid", default="effective",
                    choices=["effective", "trial", "consultation", "repealed", "unknown", "na"])
    ap.add_argument("--note", default="")
    ap.add_argument("--file", help="已保存的 HTML 文件（不传则现场抓取）")
    ap.add_argument("--end-re", default="",
                    help="正文结束标记的正则（命中处截断，防页面尾部相关推荐栏污染）")
    args = ap.parse_args()

    if args.file:
        html = open(args.file, encoding="utf-8", errors="replace").read()
    else:
        import httpx
        r = httpx.get(args.url, timeout=30, follow_redirects=True, trust_env=False,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.raise_for_status()
        html = r.text

    text = strip_html(html)
    text = truncate_tail(text, args.end_re)
    body = main_body(text)
    if len(body) < 500:
        sys.exit(f"正文提取不足 500 字（{len(body)}），拒绝入库——请人工检查页面结构后用 --file 提供本地 HTML。")
    out_path = os.path.join(TEXT_DIR, args.id + ".txt")
    open(out_path, "w", encoding="utf-8").write(body)

    # 登记 docs_meta（不覆盖已有）
    meta = json.load(open(META_PATH, encoding="utf-8"))
    existed = args.id in meta["docs"]
    meta["docs"][args.id] = {
        "title": args.title, "category": args.category, "status": "ok",
        "note": args.note, "valid_status": args.valid,
    }
    json.dump(meta, open(META_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 登记 web 来源
    srcs = {}
    if os.path.exists(WEB_SRC_PATH):
        try:
            srcs = json.load(open(WEB_SRC_PATH, encoding="utf-8"))
        except Exception:
            srcs = {}
    srcs[args.id] = {"url": args.url, "ingested": args.id and __import__("time").strftime("%Y-%m-%d"),
                     "fetch": "ingest_web"}
    json.dump(srcs, open(WEB_SRC_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"已写入 {out_path}（{len(body)} 字，正文预览：）")
    print(body[:300])
    print(f"docs_meta 登记：{'覆盖更新' if existed else '新增'}；web_sources：{args.url}")


if __name__ == "__main__":
    main()
