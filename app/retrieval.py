# -*- coding: utf-8 -*-
"""知识库检索模块：jieba 分词 + FTS5 trigram (BM25，anchor+text 双列) + 覆盖率重排"""
import os
import re
import sqlite3
from functools import lru_cache

import jieba

from . import config

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "kb", "kb.sqlite")

STOPWORDS = {
    "的", "了", "是", "在", "和", "有", "与", "及", "或", "对", "为", "中", "等",
    "应", "要", "需", "如何", "怎么", "什么", "哪些", "多少", "要求", "规定",
    "进行", "可以", "需要", "应当", "相关", "请问", "关于", "按照", "根据",
}

for w in ("有限空间", "脚手架", "临边防护", "特种作业", "危大工程", "专项施工方案",
          "安全生产", "监理", "开工一件事", "一件事", "办理流程", "材料清单",
          "电子证照", "防火", "事故", "应急预案",
          "洞口", "防护栏杆", "监督人员", "考核", "资格证书", "禁忌"):
    jieba.add_word(w, freq=1000)

SQL_CAND = """
SELECT c.chunk_id, c.doc_id, d.title, d.category, d.note, d.valid_status,
       c.clause, c.pages, c.anchor, c.text,
       bm25(chunks_fts) AS rank
FROM chunks_fts f
JOIN chunks c ON c.chunk_id = f.rowid
JOIN docs d ON d.doc_id = c.doc_id
WHERE chunks_fts MATCH ?
ORDER BY rank
LIMIT 60
"""

# 时效降权系数（ADR-006）。
# 关键取舍：unknown / 空值 **一律不降权**。当前 34 份文档的 valid_status 尚未逐份核定，
# 若把 unknown 也压分，等于让"还没查"变成"检索变差"，会整体推翻 ADR-002 的强命中零回归
# 结论。时效处理只在**已明确核定为草案或已废止**时生效，未核定的走原排序。
VALIDITY_PENALTY = {
    "repealed": 0.35,   # 已废止：仍可被检索到，但显式标注并压到末位区间
    "draft": 0.60,      # 征求意见稿/试行：草案不宜作为第一依据
}


def _validity_factor(status) -> float:
    return VALIDITY_PENALTY.get((status or "").strip().lower(), 1.0)


def _validity_partition(items: list[dict]) -> list[dict]:
    """稳定分区：已核定为草案/已废止的排到最后，其余相对次序不变。

    用于向量路——向量命中被直接置前，会绕过 search() 里的乘性降权，
    必须补一道，否则征求意见稿仍能靠向量路抢到第一依据位。
    unknown 与 effective 一律不动，保持 ADR-002 的强命中零回归性质。
    """
    keep, demoted = [], []
    for it in items:
        if _validity_factor(it.get("valid_status")) != 1.0:
            it["validity_demoted"] = True
            demoted.append(it)
        else:
            keep.append(it)
    return keep + demoted


@lru_cache(maxsize=256)
def _terms_cached(question: str):
    words = jieba.cut_for_search(question)
    out = []
    for w in words:
        w = w.strip()
        if len(w) < 2 or w in STOPWORDS or re.fullmatch(r"[\d\W]+", w):
            continue
        if w not in out:
            out.append(w)
    return tuple(out[:12])


def _shingles(term: str, n=3):
    """长词的 n 字滑片，防止词内标点/空格打断 trigram 短语匹配"""
    if len(term) <= n:
        return []
    return [term[i:i + n] for i in range(len(term) - n + 1)]


_PUNCT_RE = re.compile(r"[“”\"'‘’（）()《》〈〉【】\[\]〔〕·・、，,。.：:；;！!？?\s\u3000]")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _bare(s: str) -> str:
    """去标点后的文本，用于覆盖率匹配"""
    return _PUNCT_RE.sub("", s or "")


def search(question: str, k: int = 8, context_query: str = ""):
    """返回 top-k 命中块列表。无命中返回空列表。

    context_query：多轮场景的上下文补充（F6 上一问）。仅用于扩大召回面，
    覆盖率只按 question 自身的词计算——避免上一问的词稀释相关度导致误兜底
    （2026-09-21 线上 A4/A9 反馈根因）。"""
    recall_text = _norm(question + " " + context_query) if context_query else _norm(question)
    terms = list(_terms_cached(recall_text))          # 召回词（含上下文）
    q_terms = list(_terms_cached(_norm(question)))    # 相关度词（仅当前问题）
    if not q_terms:
        q_terms = terms
    if not terms:
        return []
    tri = [t for t in terms if len(t) >= 3]
    shingles = []
    for t in tri:
        shingles.extend(_shingles(t))
    two = [t for t in terms if len(t) == 2]
    hits = {}
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        if tri or shingles:
            q = " OR ".join('"%s"' % t for t in tri + shingles)
            for r in con.execute(SQL_CAND, (q,)):
                hits[r["chunk_id"]] = dict(r)
        # trigram 无法命中 <3 字词，用 LIKE 召回。
        # 必须逐词查询：若写成 OR 合并 + LIMIT，泛词（如"施工"）会填满结果集，
        # 把罕见词（如"桩头"）的块挤出候选，导致带上下文时反而 0 命中。
        for t in two:
            for r in con.execute(
                """SELECT c.chunk_id, c.doc_id, d.title, d.category, d.note, d.valid_status,
                          c.clause, c.pages, c.anchor, c.text
                   FROM chunks c JOIN docs d ON d.doc_id = c.doc_id
                   WHERE (COALESCE(c.anchor, '') || c.text) LIKE ? LIMIT 60""", (f"%{t}%",)):
                hits.setdefault(r["chunk_id"], dict(r))
    finally:
        con.close()

    if not hits:
        return []
    # 文档标题命中的块加权（如问"电子证照标准"直接命中标题）
    title_docs = set()
    if tri or two:
        con = sqlite3.connect(DB_PATH)
        try:
            conds = " OR ".join("title LIKE ?" for _ in (tri + two))
            args = [f"%{t}%" for t in (tri + two)]
            for (doc_id,) in con.execute(f"SELECT doc_id FROM docs WHERE {conds}", args):
                title_docs.add(doc_id)
        finally:
            con.close()

    qnorm = _norm(question)
    n_terms = max(1, len(q_terms))
    # bm25 归一化 bonus：FTS 匹配越强（|rank| 越大，rank 为负）bonus 越接近 1；
    # LIKE 泛词召回（无 rank）是弱证据，给固定低值 0.25，不得压过 FTS 强匹配。
    # 旧公式 1/(1+|rank|) 方向相反（匹配越强分越低），导致无关块系统性压过正确块，
    # 进而诱发 LLM 对库内问题误答「未找到」（2026-09-21 线上 A/C/D 组反馈）。
    fts_ranks = [abs(h["rank"]) for h in hits.values() if h.get("rank") is not None]
    max_rank = max(fts_ranks) if fts_ranks else 0.0
    scored = []
    for h in hits.values():
        bare = _bare(h["text"])
        # 覆盖率匹配面含 anchor 锚点（ADR-005）：表格明细块的语义锚点
        # （文档标题/类别/章节）与问句词面的重叠计入覆盖率，把「对的文档、
        # 错的块」从 15~30 位拉回窗口内；整句命中仍按纯正文（严格口径，
        # 防止锚点+正文拼出假整句）。
        cov_bare = _bare((h.get("anchor") or "") + h["text"])
        # 覆盖率只按当前问题的词统计（上下文词仅用于扩召回，不得计入）
        covered = sum(1 for t in q_terms if _bare(t) in cov_bare)
        coverage = covered / n_terms
        r = h.get("rank")
        if r is None:
            bonus = 0.25
        elif max_rank > 0:
            bonus = abs(r) / max_rank
        else:
            bonus = 1.0
        score = coverage * 2.0 + bonus
        qbare = _bare(question)
        if len(qbare) >= 6 and qbare in bare:  # 整句命中强加权
            score += 2.0
        if h["doc_id"] in title_docs:
            score += 0.6
        # 时效降权放在所有加分之后：草案/已废止仍可被检索到，但不能顶替正式稿成为
        # 第一依据。unknown 不降权（见 VALIDITY_PENALTY 注释）。
        factor = _validity_factor(h.get("valid_status"))
        if factor != 1.0:
            score *= factor
            h["validity_demoted"] = True
        scored.append((score, coverage, h))
    # 必须先按覆盖率过滤、再截断：否则扩召回带来的高分无关块（bm25/标题加分高但
    # 覆盖率 0）会占满 top-k 名额，把真正相关的块挤出候选集（2026-09-21 C3 复现）。
    scored = [s for s in scored if s[1] >= 0.2]  # 命中词太少视为弱相关
    scored.sort(key=lambda x: (-x[0], -x[1]))
    out = []
    for score, coverage, h in scored[:k]:
        h["score"] = round(score, 3)
        h["coverage"] = round(coverage, 2)
        out.append(h)
    return out


def hybrid_search(question: str, k: int = 8, context_query: str = ""):
    """条件补充混合检索（ADR-002，POC 验证：tests/poc_conditional.py）。

    规则（与 POC 逐字一致，不得偏离）：
    - BM25 无命中：返回空（向量不救零命中，兜底链路不变）
    - 强命中（max coverage >= REWRITE_MIN_COVERAGE）：BM25 原排序，向量不参与
    - 弱命中（< REWRITE_MIN_COVERAGE，原改写场景）：
      向量 top-VECTOR_TOP_K 置前 + BM25 top-VECTOR_BM25_KEEP 去重追加

    返回 (hits, top_cov)：top_cov 始终是 BM25 路径的 max coverage——
    兜底（MIN_COVERAGE）与改写触发的判据维持 BM25 主判据，不因向量命中而改变
    （库内外相似度重叠，向量阈值不可作兜底依据，见 POC 报告 §3.1）。
    HYBRID=off 或向量路不可用时，本函数等价于 search()。
    """
    hits = search(question, k, context_query)
    top_cov = max((h["coverage"] for h in hits), default=0.0)
    if not hits or top_cov >= config.REWRITE_MIN_COVERAGE:
        return hits, top_cov
    try:
        from . import vector_search
        if not vector_search.available():
            return hits, top_cov
        vec_hits = vector_search.top_k(question, config.VECTOR_TOP_K)
    except Exception:  # 向量路任何异常都不影响 BM25 主链路
        return hits, top_cov
    if not vec_hits:
        return hits, top_cov
    for h in hits:
        h.setdefault("via", "bm25")
    fused = list(vec_hits)
    for h in hits[:config.VECTOR_BM25_KEEP]:
        if h["chunk_id"] not in {v["chunk_id"] for v in fused}:
            fused.append(h)
    fused = _validity_partition(fused)
    return fused[:k], top_cov

def get_chunk_context(chunk_id: int) -> dict | None:
    """返回某 chunk 的逐字全文 + 同文档相邻 seq 的 prev/next 块。

    返回结构（SPEC §1）：chunkId/docId/title/category/clause/pages/seq/text
    以及 prev/next（各自含 seq/clause/pages/text，不存在为 None）。
    不存在该 chunk 返回 None。文本与 kb.sqlite 逐字一致，不做改写。
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """SELECT c.chunk_id, c.doc_id, d.title, d.category,
                      c.seq, c.clause, c.pages, c.text
               FROM chunks c JOIN docs d ON d.doc_id = c.doc_id
               WHERE c.chunk_id = ?""", (chunk_id,)).fetchone()
        if not row:
            return None
        cur = dict(row)
        prev = con.execute(
            """SELECT c.seq, c.clause, c.pages, c.text
               FROM chunks c
               WHERE c.doc_id = ? AND c.seq = ?""",
            (cur["doc_id"], cur["seq"] - 1)).fetchone()
        nxt = con.execute(
            """SELECT c.seq, c.clause, c.pages, c.text
               FROM chunks c
               WHERE c.doc_id = ? AND c.seq = ?""",
            (cur["doc_id"], cur["seq"] + 1)).fetchone()
    finally:
        con.close()

    def _blk(r):
        if not r:
            return None
        return {
            "seq": r["seq"],
            "clause": (r["clause"] or "").strip(),
            "pages": r["pages"] or "",
            "text": r["text"],
        }

    return {
        "chunkId": cur["chunk_id"],
        "docId": cur["doc_id"],
        "title": cur["title"],
        "category": cur["category"] or "",
        "clause": (cur["clause"] or "").strip(),
        "pages": cur["pages"] or "",
        "seq": cur["seq"],
        "text": cur["text"],
        "prev": _blk(prev),
        "next": _blk(nxt),
    }


def doc_stats():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("""
            SELECT d.doc_id, d.title, d.category, d.status, d.note, d.pages, d.chars,
                   d.valid_status, d.version_date,
                   count(c.chunk_id) AS n_chunks
            FROM docs d LEFT JOIN chunks c ON c.doc_id = d.doc_id
            GROUP BY d.doc_id ORDER BY d.doc_id""").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    tests = [
        "有限空间作业前需要检测哪些气体",
        "洞口作业有哪些防护要求",
        "特种作业人员上岗需要什么证书",
        "哪些施工工艺是禁止使用的",
        "建设项目开工一件事需要提交哪些材料",
        "专项施工方案存在哪些严重缺陷会被判定为重大事故隐患",
        "临时用电的配电箱应该怎么设置",
        "美国OSHA对脚手架的要求",  # 应无命中
    ]
    for q in tests:
        print(f"\n=== {q} ===")
        for h in search(q, k=3):
            print(f"  [{h['doc_id']} {h['title'][:22]} | {h['clause'][:14]} | cov={h['coverage']}] {_norm(h['text'])[:80]}")
