# -*- coding: utf-8 -*-
"""建安法规问答助手后端：SSE 流式问答 + 检索降级 + 知识库来源 + 限流"""
import asyncio
import collections
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, feedback, llm, prompts, retrieval, track

app = FastAPI(title="建安法规问答助手")
app.include_router(track.router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# ---- 简易 IP 限流（防 Key 盗刷，PRD P0）----
_rate: dict[str, collections.deque] = {}


def _rate_ok(ip: str) -> bool:
    now = time.time()
    dq = _rate.setdefault(ip, collections.deque())
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= config.RATE_LIMIT_PER_MIN:
        return False
    dq.append(now)
    return True


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _clean_history(raw) -> list[dict]:
    """清洗多轮 history（F6）：最多 6 条（3 轮）；role 合法；content 非空且 ≤2000 字；
    assistant content 截断至 500 字；非法条目直接丢弃。"""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        content = content.strip()
        if not content or len(content) > 2000:
            continue
        if role == "assistant":
            content = content[:500]
        out.append({"role": role, "content": content})
    return out


def _sources_payload(hits: list[dict]) -> list[dict]:
    """引用契约：{no, docId, title, clause, pages, excerpt(逐字), full(逐字全文), validStatus}"""
    out = []
    for i, h in enumerate(hits, 1):
        text = h["text"].strip()
        out.append({
            "no": i,
            "docId": h["doc_id"],
            "chunkId": h["chunk_id"],
            "title": h["title"],
            "category": h.get("category", ""),
            "clause": (h.get("clause") or "").strip(),
            "pages": h.get("pages") or "",
            "validStatus": (h.get("valid_status") or "").strip(),
            "excerpt": text[:220] + ("…" if len(text) > 220 else ""),
            "full": text,
        })
    return out


def _degraded_markdown(hits: list[dict], weak: bool = False) -> str:
    """降级模式的回答：直接逐字展示命中条款原文"""
    if weak:
        lines = [
            "**模型服务暂不可用，且未检索到与问题直接相关的条款。**",
            "",
            "以下仅为字面相似的内容片段，**请勿作为依据**；配置模型服务后可获得更准确的判定：",
            "",
        ]
        hits = hits[:3]
    else:
        lines = ["**以下为知识库检索到的原文片段，请直接核对：**", ""]
    for s in _sources_payload(hits):
        loc = f"《{s['title']}》{s['clause']}".strip()
        if s["pages"]:
            loc += f"（{s['pages']}）"
        lines.append(f"[{s['no']}] {loc}")
        lines.extend("> " + ln for ln in s["full"][:400].splitlines())
        lines.append("")
    return "\n".join(lines)


async def _chat_stream(question: str, history: list = None, role: str = "default"):
    yield _sse("status", {"stage": "retrieving", "message": "正在检索法规库"})

    # ---- 检索（F6）：上一问仅作扩召回补充，相关度只按当前问题计算 ----
    # 旧实现把上一问拼进 query 计算覆盖率，会稀释相关度（如 A9「开工流程」被上一问
    # 「震后专家队」带偏），2026-09-21 线上反馈根因之一。
    context_query = ""
    if history:
        for h in reversed(history):
            if h["role"] == "user":
                context_query = h["content"]
                break
    if context_query == question:
        context_query = ""

    try:
        hits, top_cov = await asyncio.to_thread(
            retrieval.hybrid_search, question, config.RECALL_WINDOW, context_query)
    except Exception:  # 检索库损坏等极端情况
        yield _sse("error", {"code": "retrieval", "message": "知识库检索异常，请联系管理员"})
        yield _sse("done", {"backend": "error", "role": role})
        return

    # ---- 两阶段检索：弱命中时用 LLM 把口语问题改写为规范术语后重检 ----
    # 跨过口语化表述与法规术语的词汇鸿沟（挖坑底下干活 -> 有限空间作业）。
    # 仅在弱命中路径付出一次 8 秒内的小查询代价；改写失败则沿用原结果。
    # 弱命中（覆盖率低于 REWRITE_MIN_COVERAGE）才改写：强命中问题无需多付一次 LLM 查询
    # feat_rewrite_*：反馈台账段特征（2026-11-12，ACE 启示落地），见 app/feedback.py
    feat_rewrite_attempted = False
    feat_rewrite_merged = False
    if (not hits or top_cov < config.REWRITE_MIN_COVERAGE) and config.llm_configured():
        yield _sse("status", {"stage": "rewriting", "message": "正在换一种方式检索"})
        rewritten = await llm.rewrite_query(question, history)
        feat_rewrite_attempted = bool(rewritten and rewritten != question)
        if rewritten and rewritten != question:
            try:
                hits2, top2 = await asyncio.to_thread(
                    retrieval.hybrid_search, rewritten, config.RECALL_WINDOW)
            except Exception:
                hits2, top2 = [], 0.0
            if top2 > top_cov:
                # 合并两路结果，而不是用改写路整份替换原路。
                # 改写只多认出一个词就能让整份原结果作废：实测「挖坑底下干活」
                # 改写成「…危险」时五路全是 0017，把原句已经捞到的 0069 直接丢掉，
                # 同一道题在 7/8 与 8/8 之间来回跳。并集＋同块取较高分，
                # 让改写只能加分、不能翻盘。弱命中路径之外不受影响。
                merged = {h["chunk_id"]: h for h in hits}
                for h in hits2:
                    cur = merged.get(h["chunk_id"])
                    if cur is None or h["score"] > cur["score"]:
                        merged[h["chunk_id"]] = h
                hits = sorted(merged.values(), key=lambda h: h["score"], reverse=True)
                top_cov = max(top_cov, top2)
                feat_rewrite_merged = True

    # ---- 上下文装配（迭代6）：top-8 主证据 + 同文档补位（≤6 条）----
    # 答案块可能排在 9~16 位（同文档表格碎片/邻近条款稀释，2026-09-23 线上反馈：
    # DEF-04 氧气 19.5%~23.5% 块排 11 / DEF-08 附件3 颜色块排 13 / PM-06 特殊
    # 建设工程清单块排 9）。只把与主证据同文档的窗口内块补进上下文，限制噪音规模。
    # ADR-005：窗口扩到 16 后补位仍按 ADR-004 契约截 ≤6 条——实测 16 条全量
    # 装配时 deepseek 对长上下文中排后的答案块拒答（DEF-04 复现两次），
    # 截回 14 条后答案块（supp[4]）保留、上下文长度回到 v5.1 水平。
    # PM-06 一类高层块（supp[6]）恰在截断线内，窗口 16 的排名收益不丢。
    primary = hits[:config.RETRIEVAL_TOP_K]
    primary_docs = {h["doc_id"] for h in primary}
    supplement = [h for h in hits[config.RETRIEVAL_TOP_K:]
                  if h["doc_id"] in primary_docs][:6]
    context_hits = primary + supplement
    # 兜底判据（2.4，2026-11-05，恢复 ADR-002 契约）：hybrid_search 返回的 top_cov
    # 是 BM25 主判据（弱命中改写路径含 max(top_cov, top2)），向量块 coverage 恒 0
    # （vector_search.py L153 设计如此）。旧实现用 primary 块字段无条件重算，在
    # 「向量语义救回正确块但改写未超越原覆盖率」的场景（PM-02「证书快到期怎么
    # 办理延续」：改写词 top2=0.45 == top_cov=0.45 合并不触发，5 块全是向量块）
    # 把 top_cov 归零 → sources 已展示完美答案块却回「未找到」——引用卡片与答案
    # 自相矛盾。取两判据较大值：强命中/改写合并路径两值相等零变化，仅向量独占
    # 路径恢复 BM25 判据；BM25 无命中仍兜底（向量不救零命中，ADR-002 不变）。
    top_cov = max(top_cov, max((h["coverage"] for h in primary), default=0.0))

    # ---- 相邻条款定向注入（3.1，2026-11-06）：块尾断裂（，、；：）→ 附 next ----
    # 计划原定「仅 top-3」，实测目标案例 PM-06 的断裂块（0065 清单（一）~（五），
    # 尾「；」）排第 9 在补位——按断裂信号检测（全库仅 10% 块命中）比按位次
    # 更准且预算更省。相邻块只进 LLM 上下文（build_context 消费 adjacent_next），
    # 不进 sources 编号体系（_sources_payload 只挑固定字段），引用归源块编号。
    # next 已在上下文内则不注入（去重）；注入上限 3 块控长（DEF-04 长上下文拒答
    # 教训）。prev 不注入：中文法规「下文承接上文」语义向前，前文缺失可由
    # 锚点+问题词面召回兜住，反向注入收益无实证。
    in_ctx_ids = {h["chunk_id"] for h in context_hits}
    _adj_count = 0
    for h in context_hits:
        if _adj_count >= 3:
            break
        tail = h["text"].rstrip()[-1:] if h["text"].rstrip() else ""
        if tail not in ("，", "、", "；", "："):
            continue
        try:
            ctx = retrieval.get_chunk_context(h["chunk_id"])
        except Exception:
            continue
        nxt = (ctx or {}).get("next")
        if not nxt:
            continue
        try:
            nxt_id = retrieval.get_chunk_id_by_seq(h["doc_id"], nxt["seq"])
        except Exception:
            nxt_id = None
        if nxt_id is not None and nxt_id in in_ctx_ids:
            continue  # 相邻块已被检索召回，无需注入
        h["adjacent_next"] = nxt["text"]
        _adj_count += 1

    # ---- 反馈台账段特征（2026-11-12，ACE 启示落地，ADR-011）----
    # validity 与 build_context 的〔状态〕标注同口径（ADR-006/3.3）：
    # 有标注才算该段「在场」，未核定（na/unknown/空）不算。
    feat_validity = any(
        llm.validity_note(h.get("valid_status") or "") for h in context_hits)
    _feats = {
        "validity": feat_validity,
        "adjacent": _adj_count,
        "rewrite_attempted": feat_rewrite_attempted,
        "rewrite_merged": feat_rewrite_merged,
    }

    yield _sse("status", {"stage": "retrieved", "hits": len(context_hits),
                          "docs": len({h["doc_id"] for h in context_hits})})

    # ---- 知识库无答案兜底（AC1.3）----
    if not context_hits or top_cov < config.MIN_COVERAGE:
        sources = _sources_payload(context_hits[:3])
        yield _sse("sources", {"sources": sources})
        text = (
            f"{config.NO_ANSWER_TEXT}\n\n"
            "可能的原因：\n"
            "- 问题涉及知识库收录的 34 份文档之外的内容\n"
            "- 表述过于口语化，可尝试使用规范术语\n\n"
            "建议换个问法，或点击顶部「知识库来源」查看本助手能回答的文档范围。"
        )
        yield _sse("delta", {"text": text})
        feedback.log_feedback(question, role, "no_answer", top_cov,
                               len(sources), _feats)
        yield _sse("done", {"backend": "no_answer", "coverage": top_cov, "role": role})
        return

    sources = _sources_payload(context_hits)

    # ---- 未配置 LLM：降级展示原文（非功能需求 / AC9.2）----
    if not config.llm_configured():
        weak = top_cov < 0.55  # 相关度不高时不误导用户
        if weak:
            sources = sources[:3]
        yield _sse("sources", {"sources": sources})
        yield _sse("notice", {"message": "管理员尚未配置模型服务" + ("" if weak else "，以下为检索到的原文片段")})
        degraded_text = _degraded_markdown(context_hits, weak=weak)
        yield _sse("delta", {"text": degraded_text})
        feedback.log_feedback(question, role, "retrieval", top_cov,
                               len(sources), _feats, degraded_text)
        yield _sse("done", {"backend": "retrieval", "citations": len(sources),
                            "coverage": top_cov, "role": role})
        return

    yield _sse("sources", {"sources": sources})

    # ---- LLM 流式生成（角色化提示词，迭代5/ADR-003）----
    # 3.1 相邻注入只进 LLM 上下文：_sources_payload 不透出 adjacent_next
    # （SSE 契约与前端卡片不变），此处按位序合回再交给 stream_chat。
    llm_sources = []
    for s, h in zip(sources, context_hits):
        if h.get("adjacent_next"):
            s2 = dict(s)
            s2["adjacent_next"] = h["adjacent_next"]
            llm_sources.append(s2)
        else:
            llm_sources.append(s)
    answer_started = False
    try:
        buf = ""
        async for delta in llm.stream_chat(llm_sources, question, history=history, role=role):
            answer_started = True
            buf += delta
            yield _sse("delta", {"text": delta})
        # 反馈台账（P2+）：答案完成后机械自检 [n] 引用白名单并落盘——
        # 自检结果不进 SSE（对外契约不变），只进 data/feedback_ledger.jsonl
        # 供段计数台账消费（GOV-06 类漂移自动显形，见 ADR-011）。
        feedback.log_feedback(question, role, "llm", top_cov,
                               len(sources), _feats, buf)
        yield _sse("done", {"backend": "llm", "citations": len(sources),
                            "answer_chars": len(buf), "role": role})
    except llm.LLMError as e:
        feedback.log_feedback(question, role, "error", top_cov,
                               len(sources), _feats)
        if not answer_started:
            # 一个字都没生成：降级为原文展示（PRD 可用性要求）
            yield _sse("notice", {"message": f"{e.message}，以下为检索到的原文片段"})
            yield _sse("delta", {"text": _degraded_markdown(hits)})
            yield _sse("done", {"backend": "retrieval", "citations": len(sources),
                                "role": role})
        else:
            yield _sse("error", {"code": e.code, "message": e.message})
            yield _sse("done", {"backend": "error", "role": role})


@app.post("/api/chat")
async def chat(request: Request):
    ip = request.client.host if request.client else "?"
    if not _rate_ok(ip):
        return JSONResponse(
            {"error": {"code": "rate_limited", "message": "当前提问人数较多，请稍后重试"}},
            status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": {"code": "bad_request", "message": "请求格式错误"}}, status_code=400)
    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": {"code": "empty", "message": "请输入问题"}}, status_code=400)
    if len(question) > 2000:
        return JSONResponse({"error": {"code": "too_long", "message": "问题过长，请精简到 2000 字以内"}}, status_code=400)

    history = _clean_history(body.get("history"))
    # 角色化提示词（迭代5/ADR-003）：非法/缺省一律回退 default，旧客户端零影响
    role = prompts.normalize_role(body.get("role"))

    return StreamingResponse(
        _chat_stream(question, history, role),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/roles")
async def roles():
    """角色清单（迭代5）：前端下拉数据源，default 恒在首位。"""
    return {"roles": prompts.available_roles(), "default": prompts.DEFAULT_ROLE}


@app.get("/api/sources")
async def sources():
    stats = retrieval.doc_stats()
    categories = sorted({s["category"] for s in stats if s["category"]})
    return {
        "docs": stats,
        "categories": categories,
        "totalDocs": len(stats),
        "indexedDocs": sum(1 for s in stats if s["n_chunks"] > 0),
        "totalChunks": sum(s["n_chunks"] for s in stats),
        "disclaimer": config.DISCLAIMER,
    }


# 示例问题：全部经检索验证可被知识库正确回答（AC3.3）
EXAMPLE_QUESTIONS = [
    {"q": "有限空间作业前需要检测哪些气体？", "tag": "有限空间"},
    {"q": "建筑施工特种作业人员如何取得资格证书？", "tag": "特种作业"},
    {"q": "建设项目开工“一件事”需要提交哪些材料？", "tag": "开工一件事"},
    {"q": "哪些施工工艺、设备、材料是禁止使用的？", "tag": "禁限用技术"},
    {"q": "专项施工方案有哪些严重缺陷会被判定为重大事故隐患？", "tag": "危大工程"},
    {"q": "震后房屋建筑安全应急评估结论分为哪几级？", "tag": "应急管理"},
]


@app.get("/api/examples")
async def examples():
    return {"examples": EXAMPLE_QUESTIONS, "disclaimer": config.DISCLAIMER}


def _hybrid_info() -> dict:
    """向量组件诊断信息（迭代5 修复：health 原直接引用 vector_search 但未 import，
    会 NameError 导致 status 恒为 degraded）。惰性导入，缺依赖只降级该字段。"""
    try:
        from . import vector_search
        return vector_search.backend_info()
    except Exception as e:
        return {"hybrid": False, "err": str(e)}


@app.get("/api/health")
async def health():
    try:
        stats = retrieval.doc_stats()
        return {
            "status": "ok",
            "llmConfigured": config.llm_configured(),
            "llmModel": config.LLM_MODEL if config.llm_configured() else "",
            "docs": len(stats),
            "chunks": sum(s["n_chunks"] for s in stats),
            "hybrid": _hybrid_info(),
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e),
                "llmConfigured": config.llm_configured(), "hybrid": _hybrid_info()}


@app.get("/api/config-status")
async def config_status():
    return {"llmConfigured": config.llm_configured(), "model": config.LLM_MODEL,
            "disclaimer": config.DISCLAIMER}


# ---- 静态前端 ----
@app.get("/api/chunk/{chunk_id}")
async def chunk(chunk_id: int):
    ctx = retrieval.get_chunk_context(chunk_id)
    if ctx is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "条款不存在"}},
            status_code=404)
    return ctx


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
