# -*- coding: utf-8 -*-
"""LLM 调用封装：OpenAI 兼容 /chat/completions 流式接口（httpx 实现）"""
import asyncio
import json
import typing

import httpx

from . import config, prompts


class LLMError(Exception):
    """带用户可读分类的 LLM 异常，code 用于前端错误文案分类"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def classify_http_error(status: int) -> LLMError:
    if status == 401:
        return LLMError("auth", "模型服务鉴权失败，请联系管理员检查 API Key 配置")
    if status == 429:
        return LLMError("rate", "当前提问人数较多，请稍后重试")
    if status in (500, 502, 503, 504):
        return LLMError("server", "模型服务暂时不可用，请稍后重试")
    return LLMError("server", "模型服务返回异常（%d），请稍后重试" % status)


_TERMINAL = ("。", "！", "？", "；", "：", "”", "）", "】", "%", "°")
_CJK = lambda ch: "\u4e00" <= ch <= "\u9fff"


def _flow(text: str) -> str:
    """合并 PDF/OCR 抽取文本的固定列宽硬换行，让片段成为连贯段落。

    仅改变空白与换行位置，不改动任何字符（引用逐字性不受影响）。"""
    out: list[str] = []
    for raw in (text or "").splitlines():
        ln = raw.strip()
        if not ln:
            continue
        prev = out[-1] if out else ""
        if (
            prev and len(prev) >= 6
            and not prev.startswith("—")
            and not prev.endswith(_TERMINAL)
            and prev.count("|") < 2 and ln.count("|") < 2
            and not (ln[:1].isdigit() or ln[:1] in "（(-—·|")
            and not (len(ln) >= 2 and ln[:2] in ("第",))
        ):
            sep = "" if (_CJK(prev[-1]) or _CJK(ln[0])) else " "
            out[-1] = prev + sep + ln
        else:
            out.append(ln)
    return "\n".join(out)


async def rewrite_query(
    question: str,
    history: typing.Optional[list[dict]] = None,
) -> typing.Optional[str]:
    """弱命中路径的「口语 -> 法规术语」查询改写（两阶段检索）。

    仅在首次检索结果不达标时调用，用于跨过口语化表述与法规术语之间的词汇鸿沟
    （如：挖坑底下干活 -> 有限空间作业；房子/震完 -> 房屋建筑/震后；着火 -> 阻燃防火）。
    非流式、8 秒超时；任何异常返回 None，不阻塞主流程（调用方应降级为原结果）。
    只输出一行查询词，不回答用户问题。
    """
    if not config.llm_configured():
        return None

    system = (
        "你是法规库检索查询改写器。把用户的口语化问题改写成适合检索建筑安全法规库的规范术语查询，规则：\n"
        "1. 口语词替换为行业/法规标准术语，例如：房子/楼房 -> 房屋建筑；震完/地震后 -> 震后；"
        "着火/容易烧 -> 阻燃 防火；塔吊 -> 建筑起重机械；挖坑底下干活/井下作业 -> 有限空间作业 或 基坑作业；"
        "考证 -> 考核发证；密目网 -> 密目式安全网。\n"
        "2. 保留用户原意与对象，不得引入问题之外的新主题、不得臆造条款。\n"
        "3. 当前问题含指代（那/它/第X条/上述/前面提到/某项）时，必须结合对话历史把指代解析为明确对象，"
        "输出完整独立的查询（如「那检测的频次」且历史在谈有限空间 -> 有限空间作业 气体检测 频次）；"
        "历史与当前问题无关时忽略历史。\n"
        "4. 如果问题本身就是规范术语，原样输出即可。\n"
        "5. 只输出一行查询词，不超过 40 字；不要回答问题，不要解释，不要标点结尾。"
    )
    # 多轮改写（B-2，2026-10-24）：旧版只带上一问，指代类追问（那第三条呢）无法解析。
    # 现带最近 2 个用户问题 + 最后一条助手回答摘录（150 字；_clean_history 已保证 ≤500）。
    user = question
    if history:
        prev_qs = [h["content"] for h in history if h.get("role") == "user"][-2:]
        last_a = next((h["content"][:150] for h in reversed(history)
                       if h.get("role") == "assistant"), "")
        parts = []
        for i, pq in enumerate(prev_qs, 1):
            parts.append(f"对话用户问{i}：{pq[:100]}")
        if last_a:
            parts.append(f"助手上一答（摘录）：{last_a}")
        parts.append(f"当前问题：{question}")
        user = "\n".join(parts)

    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # 查询改写要的是最可能的规范术语串，不是创作，故取贪心解码。
        # 注意：这只能压低翻转频率，DeepSeek 服务端本身仍非确定（实测同一口语题
        # 在「危险」/「危险因素」两种改写间仍会跳），所以检索侧不能假设改写稳定。
        "temperature": 0.0,
        "max_tokens": 100,
    }
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            if resp.status_code != 200:
                return None
            obj = resp.json()
            content = ((obj.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            text = (content.strip().strip('"“”《》 \n\t') or "")
            if not text:
                return None
            return text.splitlines()[0].strip()[:40] or None
    except Exception:
        return None


# ---- 时效状态进上下文（上下文改进计划 3.3，2026-11-04，ADR-006 生成侧对齐）----
# ADR-006 的时效核定此前只作用于检索侧（降权/分区）与前端徽章；LLM 看到的片段
# 头只有《标题》条款，无从区分现行/试行/未生效/已废止——实测状态类问题
# （"指南生效了吗""两版本以哪个为准"）要么拒答要么答"无法判断"（基线
# eval_val-before_20261104）。此处把 docs 表的核定结论以〔状态〕行注入片段头，
# 与 ADR-006 词表及前端徽章同口径：
#   effective     现行有效
#   trial         试行，已印发施行，现行有效（检索侧不降权，生成侧也不含糊）
#   consultation  征求意见稿，未生效，不得作为现行施工依据
#   repealed      已废止，不得作为现行依据
# 未核定（na / unknown / 空）不标注——与 ADR-006「未核定不动作」同哲学：
# 11 份 unknown 若标注「时效待确认」会诱发 LLM 对其内容 hedge/拒答，
# 而 A7/A8/C3 的依据文档恰在其中，属无实证的回归风险，不做。
_VALIDITY_NOTE = {
    "effective": "〔状态：现行有效〕",
    "trial": "〔状态：试行，已印发施行，现行有效〕",
    "consultation": "〔状态：征求意见稿，未生效，不得作为现行施工依据〕",
    "repealed": "〔状态：已废止，不得作为现行依据〕",
}

# 有〔状态〕标注时的说明行（置于片段块之前），让 LLM 把〔状态〕当作元数据
# 而非条款原文；措辞与 ADR-006「未标注=未核定=与现行同权」的检索侧口径一致。
_VALIDITY_LEAD = (
    "（〔状态〕为该文件的人工核定时效状态，属于片段内容，可据此回答文件时效与"
    "版本取舍问题：未生效或已废止的不得作为现行依据，回答涉及时须明示其状态；"
    "同一文件多版本并存时，以标注现行有效或试行有效的版本为准；"
    "未标注的按普通现行文本对待。）"
)


def validity_note(status: str) -> str:
    """valid_status -> 片段头〔状态〕标注；未核定（na/unknown/空）返回空串。"""
    return _VALIDITY_NOTE.get((status or "").strip().lower(), "")


def _snippet_status(s: dict) -> str:
    """sources 载荷（camelCase）与检索命中（snake_case）两种键名都兼容。"""
    return s.get("validStatus") or s.get("valid_status") or ""


def build_context(snippets: list[dict]) -> str:
    """把 sources 片段装配为用户消息里的「法规片段」块（纯函数，便于单测）。

    未核定语料（无〔状态〕）且无相邻注入时输出与历史版本逐字节一致——
    零标注零改动，保证 62 题基线在该路径上的回归红线。

    相邻条款注入（3.1，2026-11-06）：片段携带 adjacent_next（源块块尾断裂时
    由 main.py 装配的下一块逐字全文）时，附在源块之后并显式标注。相邻块
    不进 sources 编号体系（引用卡片无对应块），引用归源块编号——幻觉红线。
    """
    ctx_lines = []
    for s in snippets:
        loc = f"《{s['title']}》"
        if s.get("clause"):
            loc += s["clause"]
        if s.get("pages"):
            loc += f"（{s['pages']}）"
        head = f"[{s['no']}] {loc}"
        note = validity_note(_snippet_status(s))
        if note:
            head += note
        body = _flow(s["full"])
        nxt = s.get("adjacent_next")
        if nxt:
            body += (
                "\n〔接本片段之后的相邻条款，供衔接；引用此部分内容时仍标注"
                f"编号 [{s['no']}]〕\n{_flow(nxt)}"
            )
        ctx_lines.append(f"{head}\n{body}")
    context = "\n\n".join(ctx_lines)
    if any(validity_note(_snippet_status(s)) for s in snippets):
        context = _VALIDITY_LEAD + "\n\n" + context
    return context


async def stream_chat(
    snippets: list[dict],
    question: str,
    history: typing.Optional[list[dict]] = None,
    role: str = "default",
) -> typing.AsyncGenerator[str, None]:
    """调用 LLM 流式生成，逐段 yield 文本增量。

    snippets: 检索命中的条款片段（含 no/title/clause/pages/full[/validStatus]）
    history: 多轮上下文（[{role:"user"|"assistant", content:str}]），为空时与 v1 逐字节一致
    role: 角色化提示词（迭代5/ADR-003），default 与 V4 现网系统提示词逐字节一致
    出错抛 LLMError；调用方负责降级。
    """
    context = build_context(snippets)

    # 系统提示词按角色生成（prompts.system_prompt）：default 与 V4 逐字节一致，
    # 角色模板共享同一份契约规则（引用/拒答红线），只加角色设定与输出侧重。
    system = prompts.system_prompt(role)
    user = f"法规片段：\n{context}\n\n用户问题：{question}"

    messages = [{"role": "system", "content": system}]
    # 多轮上下文（纯文本轮次），history 为空时与 v1 逐字节一致（AC-F6-2 回归红线）
    if history:
        for turn in history:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user})

    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=None) as client:
        try:
            async with client.stream(
                "POST",
                f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code != 200:
                    raise classify_http_error(resp.status_code)
                agen = resp.aiter_lines()
                # 首 token 超时（PRD：60 秒无首字符按失败处理）
                try:
                    line = await asyncio.wait_for(agen.__anext__(), timeout=config.LLM_TIMEOUT_FIRST)
                except StopAsyncIteration:
                    return
                except asyncio.TimeoutError:
                    raise LLMError("timeout", "模型服务长时间未响应，请稍后重试")
                start = asyncio.get_running_loop().time()
                while True:
                    remaining = config.LLM_TIMEOUT_TOTAL - (asyncio.get_running_loop().time() - start)
                    if remaining <= 0:
                        raise LLMError("timeout", "模型服务响应超时，请稍后重试")
                    try:
                        if line is not None:
                            cur = line
                            line = None
                        else:
                            cur = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
                    except StopAsyncIteration:
                        break
                    if not cur.startswith("data:"):
                        continue
                    data = cur[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
        except httpx.TimeoutException:
            raise LLMError("timeout", "模型服务响应超时，请稍后重试")
        except httpx.HTTPError as e:
            raise LLMError("network", f"无法连接模型服务：{type(e).__name__}")
