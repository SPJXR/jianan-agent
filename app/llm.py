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
        "3. 如果问题本身就是规范术语，原样输出即可。\n"
        "4. 只输出一行查询词，不超过 40 字；不要回答问题，不要解释，不要标点结尾。"
    )
    user = question
    if history:
        prev = [h["content"] for h in history if h.get("role") == "user"]
        if prev:
            user = f"（对话上一问：{prev[-1][:100]}）\n当前问题：{question}"

    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": 0.1,
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


async def stream_chat(
    snippets: list[dict],
    question: str,
    history: typing.Optional[list[dict]] = None,
    role: str = "default",
) -> typing.AsyncGenerator[str, None]:
    """调用 LLM 流式生成，逐段 yield 文本增量。

    snippets: 检索命中的条款片段（含 no/title/clause/text）
    history: 多轮上下文（[{role:"user"|"assistant", content:str}]），为空时与 v1 逐字节一致
    role: 角色化提示词（迭代5/ADR-003），default 与 V4 现网系统提示词逐字节一致
    出错抛 LLMError；调用方负责降级。
    """
    ctx_lines = []
    for s in snippets:
        loc = f"《{s['title']}》"
        if s.get("clause"):
            loc += s["clause"]
        if s.get("pages"):
            loc += f"（{s['pages']}）"
        ctx_lines.append(f"[{s['no']}] {loc}\n{_flow(s['full'])}")
    context = "\n\n".join(ctx_lines)

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
