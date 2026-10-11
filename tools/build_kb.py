# -*- coding: utf-8 -*-
"""把 kb/text/*.txt 分块并建立 SQLite FTS5（trigram）检索索引 -> kb/kb.sqlite

分块策略（ADR-005 表格感知分块，迭代6 R2）：
1. OCR 文档先去掉字符间空白（扁平文本 → 滑窗兜底）
2. 条款感知切分：第X条 / X.Y.Z 条款号 / 一、二、三 章节号 / （一）小节号
3. 表格感知（R2 核心，解「语义撕裂」）：
   - pipe 表格行（"A | B | C"）整行为单元，不再被 700 字窗口腰斩；
   - 连续同类别的行（键列在全表块内重复>=3 次）聚为「类别组」，
     不同类别绝不混块（0071 严重缺陷清单：基坑工程/起重吊装各自成块）；
   - 类别/章节标题行（"四、工程质量安全检查（129项）"、"4.5 通风"、
     "一、XXX"）开启新组，标题行粘附其后续内容成块（不孤行）；
   - 标题行同时作为「锚点」写入 chunks.anchor（"文档标题 › 最近类别/章节"），
     并跨页继承（0069 的 4.5.4 答案块在【第16页】，锚点来自第 15 页标题）。
4. 兜底：600 字滑窗、100 字重叠（无结构长文本）
5. 每块记录条款范围标签与 PDF 页码范围（引用溯源用）

anchor 契约（引用红线）：anchor 只进 FTS 索引/向量编码/覆盖率等检索加权面，
text 列保持逐字原文；构建时逐块做 substring 校验（AC1.2 逐字契约）。
"""
import io
import json
import os
import re
import sqlite3
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_DIR = os.path.join(BASE, "kb", "text")
META_PATH = os.path.join(BASE, "kb", "docs_meta.json")
EXTRACT_META = os.path.join(BASE, "kb", "extract_meta.json")
DB_PATH = os.path.join(BASE, "kb", "kb.sqlite")

MAX_CHUNK = 700
MIN_CHUNK_TEXT = 30

CLAUSE_RE = re.compile(r"^(第[一二三四五六七八九十百千零〇\d]+条|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+(?:\.\d+){0,3}[\s、．.])")
PAGE_RE = re.compile(r"【第(\d+)页】")

# ---- R2 表格感知：标题/类别行与表格行识别 ----
# 类别统计行："四、工程质量安全检查（129项）" / "房地产开发企业监督检查（3项）"
CAT_COUNT_RE = re.compile(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）)?\S{2,28}（\d+项）$")
# 中文序号短标题："一、总体要求" / "五、注册造价工程师监督检查"
CN_HEAD_RE = re.compile(r"^[一二三四五六七八九十]+、\S{1,24}$")
# 数字章节标题："4.5 通风" / "1 总则与基本规定"（编号<=2级、短尾、无句读、非目录）
NUM_HEAD_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,1})\s+(\S{1,16})$")
# 章标题："第三章 XXX"
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百\d]+章\s*\S+")

# 标题行禁止包含句读（正文条款被误判为标题的根因防线）；
# 注意（）、数字编号里的 "." 必须放行 —— 句读集不含它们。
_HEAD_FORBID = "。，；：、！？…？！,;:"
_TOC_DOTS = re.compile(r"\.{2,}|…{1,}")


def clean_ocr(text):
    """OCR 文本去掉全部空白（中文不需要空格）"""
    return re.sub(r"\s+", "", text)


def normalize(text):
    text = text.replace("\u3000", " ").replace("\x0c", "\n")
    # 合并表格行内多余空格，但保留换行
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def split_by_pages(text):
    """把 PDF 文本按页标记切开，返回 [(page_no, text)]，无标记时 [(None, text)]"""
    parts = PAGE_RE.split(text)
    if len(parts) <= 1:
        return [(None, text)]
    out = []
    # parts: [pre, p1, body1, p2, body2, ...]
    if parts[0].strip():
        out.append((None, parts[0]))
    for i in range(1, len(parts), 2):
        out.append((int(parts[i]), parts[i + 1]))
    return out


def section_title(ln: str):
    """类别/章节标题行判定：返回锚点文本（短标题原文），非标题行返回 None。

    三类：①（N项）类别统计行（0001 检查事项清单）
          ② 中文序号/章短标题（无句读、<=34 字）
          ③ 数字章节标题 "4.5 通风"（编号<=2级，排除目录点线行）
    """
    s = ln.strip()
    if not s or len(s) > 34 or _TOC_DOTS.search(s):
        return None
    if any(ch in s for ch in _HEAD_FORBID):
        return None
    if CAT_COUNT_RE.match(s) or CN_HEAD_RE.match(s) or CHAPTER_RE.match(s):
        return s
    if NUM_HEAD_RE.match(s):
        return s
    return None


def split_pipe_row(ln: str):
    """pipe 表格行 -> 去尾空后的单元格列表；非表格行返回 None。

    判定：含 " | "（或首尾紧贴 |），且 >=2 列、>=2 个非空单元格 ——
    避免正文中孤立的 "A|B" 误入表格通道。
    """
    if "|" not in ln:
        return None
    s = ln.strip()
    if " | " not in s and not s.startswith("|") and not s.endswith("|"):
        return None
    cells = [c.strip() for c in s.split("|")]
    while cells and not cells[-1]:
        cells.pop()
    if len(cells) < 2 or sum(1 for c in cells if c) < 2:
        return None
    return cells


def _row_key(cells):
    """表格行的类别键 = 除末列（内容列）外的非空单元格元组"""
    return tuple(c for c in cells[:-1] if c)


def _row_cat_text(cells):
    """类别组的锚点文本：>=3 列取中间列（类别列），2 列取首列"""
    mid = [c for c in cells[1:-1] if c]
    if mid:
        return " ".join(mid)
    return cells[0] if cells else ""


def build_units(body: str, state: dict) -> list[dict]:
    """把一页正文切成单元序列（表格感知 + 条款感知 + 章节锚点）。

    state 跨页携带：section=当前锚点章节（如 "4.5 通风"）；
    pending=[(line, clause_label)] 待粘附到下一组的标题行（孤行防线）。
    单元：{labels: [条款标签], lines: [原文行], section: 锚点章节, cat: 类别键, table: bool}
    """
    # 页边界的空串行（PAGE_RE.split 的产物）必须过滤：源文本经 normalize 已无空行，
    # 空串一旦经 pending 粘附/tiny 吸收进入块中部会产生 "\n\n"，破坏逐字子串性质。
    lines = [ln for ln in body.splitlines() if ln.strip()]
    units: list[dict] = []
    cur: dict | None = None
    tbl: list[tuple[str, list[str]]] | None = None  # 连续 pipe 行 (原行, cells)

    def take_pending(u: dict) -> dict:
        for ln, lab in state["pending"]:
            u["lines"].append(ln)
            if lab:
                u["labels"].append(lab)
        state["pending"] = []
        return u

    def flush_text():
        nonlocal cur
        if cur and cur["lines"]:
            units.append(cur)
        cur = None

    def open_text(line: str, label: str):
        nonlocal cur
        flush_text()
        u = {"labels": [], "lines": [], "section": state["section"], "cat": None, "table": False}
        take_pending(u)
        u["lines"].append(line)
        if label:
            u["labels"].append(label)
        cur = u

    def add_plain(line: str):
        if cur is None:
            open_text(line, "")
        else:
            cur["lines"].append(line)

    def flush_table():
        nonlocal tbl
        if not tbl:
            tbl = None
            return
        rows, tbl = tbl, None
        keys = [_row_key(c) for _, c in rows]
        cnt = Counter(keys)
        if not any(v >= 3 for v in cnt.values()):
            # 条目表（键全唯一）：整块一个中性单元，行对齐打包，不再腰斩
            u = {"labels": [], "lines": [], "section": state["section"], "cat": None, "table": True}
            take_pending(u)
            u["lines"].extend(ln for ln, _ in rows)
            units.append(u)
            return
        # 类别表：连续同键行聚组；重复键(>=3)为类别组（锚点=类别列，不与异类别合并），
        # 唯一键行（表头等）为中性单元（随后可粘附进相邻类别组）
        i = 0
        while i < len(rows):
            j = i
            while j < len(rows) and _row_key(rows[j][1]) == keys[i]:
                j += 1
            key = keys[i]
            is_cat = cnt[key] >= 3
            u = {"labels": [], "lines": [ln for ln, _ in rows[i:j]],
                 "section": _row_cat_text(rows[i][1]) if is_cat else state["section"],
                 "cat": key if is_cat else None, "table": True}
            if i == 0:
                take_pending(u)
            units.append(u)
            i = j

    for ln in lines:
        cells = split_pipe_row(ln)
        if cells is not None:
            flush_text()
            if tbl is None:
                tbl = []
            tbl.append((ln, cells))
            continue
        if tbl is not None:
            flush_table()
        sec = section_title(ln)
        if sec is not None:
            # 标题行：开启新组（粘附后续内容），推进锚点章节
            flush_text()
            m = CLAUSE_RE.match(ln)
            state["pending"].append((ln, m.group(1).strip() if m else ""))
            state["section"] = sec
            continue
        m = CLAUSE_RE.match(ln)
        if m:
            open_text(ln, m.group(1).strip())
        else:
            add_plain(ln)

    flush_text()
    if tbl is not None:
        flush_table()
    # 页尾残留的 pending 标题行不跨页（跨页粘附会跳过页标记、破坏逐字子串性质）；
    # 就地成微小单元，由 _absorb_tiny 并回本页末块。锚点章节字符串仍跨页继承。
    if state["pending"]:
        u = {"labels": [], "lines": [], "section": state["section"], "cat": None, "table": False}
        for ln, lab in state["pending"]:
            u["lines"].append(ln)
            if lab:
                u["labels"].append(lab)
        state["pending"] = []
        units.append(u)
    return units


def _slide(text: str):
    """超长无结构文本的兜底滑窗（步长 MAX_CHUNK-100）"""
    step = MAX_CHUNK - 100
    out = []
    for start in range(0, max(len(text), 1), step):
        piece = text[start:start + MAX_CHUNK]
        if piece.strip():
            out.append(piece)
        if start + MAX_CHUNK >= len(text):
            break
    return out


def _split_oversized(u: dict) -> list[dict]:
    """超长单元内部分块：表格组按行打包（不腰斩行），文本组滑窗（旧行为）"""
    text = "\n".join(u["lines"])
    if len(text) <= MAX_CHUNK:
        return [u]
    if u["table"]:
        out, cur, n = [], [], 0
        for ln in u["lines"]:
            if cur and n + len(ln) + 1 > MAX_CHUNK:
                out.append({**u, "lines": cur})
                cur, n = [], 0
            cur.append(ln)
            n += len(ln) + 1
        if cur:
            out.append({**u, "lines": cur})
        return out
    return [{"labels": u["labels"] if i == 0 else [], "lines": [piece],
             "section": u["section"], "cat": None, "table": False}
            for i, piece in enumerate(_slide(text))]


def _absorb_tiny(units: list[dict]) -> list[dict]:
    """微小单元（<MIN_CHUNK_TEXT，如表头行/页码残行）向后粘附（无后继则向前）。

    表头行/标题残行的正确去向是「跟住后面的内容」——这是 0001 表头行、
    0071 表头行不孤行、不丢行的关键。微小单元粘附时失去类别属性（仅作填充）。
    """
    out: list[dict] = []
    i, n = 0, len(units)
    while i < n:
        u = units[i]
        if len("\n".join(u["lines"])) >= MIN_CHUNK_TEXT or u["cat"]:
            out.append(u)
            i += 1
            continue
        u = {**u, "cat": None}
        if i + 1 < n:
            nxt = units[i + 1]
            units[i + 1] = {**nxt, "lines": u["lines"] + nxt["lines"],
                            "labels": u["labels"] + nxt["labels"]}
        elif out:
            out[-1]["lines"].extend(u["lines"])
            out[-1]["labels"].extend(u["labels"])
        # 既无后继也无前邻（整页只有微小单元）：丢弃（与旧 MIN_CHUNK_TEXT 行为一致）
        i += 1
    return out


def merge_units(units: list[dict]) -> list[dict]:
    """单元 -> 块。规则：
    - 相邻单元打包 <= MAX_CHUNK（与旧 clause_merge 等价）
    - 类别组互不混块（cat 键不同即切割）—— 0071 表格类别的核心诉求
    - 块的锚点章节 = 块内按字符贡献量最大的 section（0069 的 4.5.4-4.6.1
      混排块：4.5 通风内容占大头，锚点不得被块尾的 "4.6 检测" 标题抢走）
    """
    units = _absorb_tiny(units)
    chunks: list[dict] = []
    buf: dict | None = None
    buf_len = 0
    sec_w: dict[str, int] = {}

    def flush():
        nonlocal buf, buf_len, sec_w
        if buf and buf["lines"]:
            if sec_w:
                buf["section"] = max(sec_w.items(), key=lambda kv: kv[1])[0]
            chunks.append(buf)
        buf, buf_len, sec_w = None, 0, {}

    for u in units:
        for piece in _split_oversized(u):
            add = sum(len(ln) + 1 for ln in piece["lines"])
            if buf is not None:
                clash = bool(buf["cat"] and piece["cat"] and buf["cat"] != piece["cat"])
                if clash or buf_len + add > MAX_CHUNK + 20:
                    flush()
            if buf is None:
                buf = {"labels": list(piece["labels"]), "lines": list(piece["lines"]),
                       "section": piece["section"], "cat": piece["cat"]}
                buf_len = add
                sec_w = {piece["section"]: add} if piece["section"] else {}
                continue
            buf["labels"].extend(piece["labels"])
            buf["lines"].extend(piece["lines"])
            if piece["section"]:
                sec_w[piece["section"]] = sec_w.get(piece["section"], 0) + add
                buf["section"] = piece["section"]
            if piece["cat"]:
                buf["cat"] = piece["cat"]
            buf_len += add
    flush()
    return chunks


MEANINGFUL_LABEL_RE = re.compile(
    r"^(第[一二三四五六七八九十百千零〇\d]+条|\d+(?:\.\d+)+|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|附录\w*)$")


def tidy_label(label):
    """只保留有意义的条款号；过滤纯数字行号（PDF 版式噪声）"""
    parts = [p for p in label.split("-") if p.strip()]
    keep = [p.strip() for p in parts if MEANINGFUL_LABEL_RE.match(p.strip())]
    keep = keep[:4]
    return "-".join(keep)


def chunk_doc(text: str, state: dict | None = None):
    """返回 [(pages_label, clause_label, chunk_text, section)]，state 跨页携带锚点"""
    if state is None:
        state = {"section": "", "pending": []}
    out = []
    for page, body in split_by_pages(text):
        if not body.strip():
            continue
        for ch in merge_units(build_units(body, state)):
            pages = f"第{page}页" if page else ""
            out.append((pages, "-".join(dict.fromkeys(ch["labels"])),
                        "\n".join(ch["lines"]).strip(), ch["section"]))
    return out


def main(out_path: str | None = None):
    db_path = out_path or DB_PATH
    meta = json.load(open(META_PATH, encoding="utf-8"))["docs"]
    extract = json.load(open(EXTRACT_META, encoding="utf-8"))
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    con.executescript("""
    CREATE TABLE docs(
        doc_id TEXT PRIMARY KEY, filename TEXT, title TEXT, category TEXT,
        status TEXT, note TEXT, ocr INTEGER, pages INTEGER, chars INTEGER,
        valid_status TEXT DEFAULT 'unknown', version_date TEXT);
    CREATE TABLE chunks(
        chunk_id INTEGER PRIMARY KEY, doc_id TEXT REFERENCES docs(doc_id),
        seq INTEGER, clause TEXT, pages TEXT, text TEXT, anchor TEXT);
    CREATE VIRTUAL TABLE chunks_fts USING fts5(
        anchor, text, content='chunks', content_rowid='chunk_id', tokenize='trigram');
    CREATE INDEX idx_chunks_doc ON chunks(doc_id);
    """)

    n_docs, n_chunks, n_anchored, n_verbatim = 0, 0, 0, 0
    for doc_id, m in sorted(meta.items()):
        txt_path = os.path.join(TEXT_DIR, doc_id + ".txt")
        ext = extract.get(doc_id, {})
        if not os.path.exists(txt_path):
            print(f"[{doc_id}] no text file, skip")
            continue
        raw = open(txt_path, encoding="utf-8-sig").read()
        raw = normalize(raw)
        if m.get("ocr"):
            raw = clean_ocr(raw)
        chars = len(raw)
        status = m["status"]
        title = m["title"]
        con.execute(
            "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, m.get("_filename", ext.get("filename", "")), title, m["category"],
             status, m.get("note", ""), 1 if m.get("ocr") else 0,
             ext.get("pages"), chars,
             m.get("valid_status", "unknown"), m.get("version_date", "")))
        if status in ("scan",) or chars < 100:
            # 图片版/无有效文本：不切块
            print(f"[{doc_id}] {status}: chars={chars}, not chunked")
            continue
        state = {"section": "", "pending": []}
        seq = 0
        for pages, clause, piece, section in chunk_doc(raw, state):
            if len(piece) < MIN_CHUNK_TEXT:
                continue
            anchor = title if not section else f"{title} › {section}"
            if piece not in raw:
                raise AssertionError(f"[{doc_id}] 逐字契约破坏: {piece[:40]!r}")
            n_verbatim += 1
            con.execute(
                "INSERT INTO chunks(doc_id, seq, clause, pages, text, anchor) VALUES (?,?,?,?,?,?)",
                (doc_id, seq, tidy_label(clause), pages, piece, anchor))
            seq += 1
            if section:
                n_anchored += 1
        n_docs += 1
        n_chunks += seq
        print(f"[{doc_id}] {title[:30]}: chunks={seq}")

    # 同步 fts 外部内容表（anchor+text 双列，未限定列的 MATCH 自动搜全部列）
    con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    con.commit()
    cnt = con.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    print(f"\ndocs indexed: {n_docs}, chunks: {n_chunks} (fts rows: {cnt}) -> {db_path}")
    print(f"anchored chunks: {n_anchored} ({n_anchored / max(n_chunks, 1):.0%}) | "
          f"verbatim-checked: {n_verbatim}/{n_chunks}")
    con.close()


if __name__ == "__main__":
    _out = None
    if "--out" in sys.argv:
        _out = sys.argv[sys.argv.index("--out") + 1]
    main(_out)
