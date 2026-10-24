# -*- coding: utf-8 -*-
"""口语 → 法规术语召回映射（ADR-008，路线图 B-1）。

设计契约（与两阶段检索的分工）：
1. 只扩召回：命中的映射词追加进检索召回词（recall terms），
   **不进覆盖率分母**——覆盖率仍按原问题的词计算，
   防止映射词把无关块的相关度虚高（同 context_query 的既定纪律）。
2. 词表外置：kb/synonyms.json（人工维护），不硬编码在检索代码里。
   词表与 app/llm.py 改写提示词的示例词保持同一套，保证两阶段行为一致。
3. 零成本前置：本模块命中即免掉一次 8 秒内的 LLM 改写调用；
   未命中的口语仍走原改写链路（映射是改写的快路径，不是替代）。
4. 任何加载失败（文件缺失/JSON 损坏）→ 返回空列表，不影响主链路。
"""
import json
import os
import re
from functools import lru_cache

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNONYMS_PATH = os.path.join(BASE, "kb", "synonyms.json")

_WS = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _load() -> dict[str, list[str]]:
    try:
        data = json.load(open(SYNONYMS_PATH, encoding="utf-8"))
        raw = data.get("map", {}) if isinstance(data, dict) else {}
        out = {}
        for k, v in raw.items():
            k = _WS.sub("", k)
            targets = [t for t in v if isinstance(t, str) and len(t.strip()) >= 2]
            if len(k) >= 2 and targets:
                out[k] = targets
        return out
    except Exception:
        return {}


def expand(question: str, limit: int = 6) -> list[str]:
    """返回问题命中的映射目标词（去重，最多 limit 个）。

    匹配面：去空白后的问题原文做子串匹配（含 context_query 的拼接
    由调用方决定——本模块只看当前问题，与覆盖率口径一致）。
    """
    q = _WS.sub("", question or "")
    if len(q) < 2:
        return []
    out: list[str] = []
    for key, targets in _load().items():
        if key in q:
            for t in targets:
                if t not in out:
                    out.append(t)
                if len(out) >= limit:
                    return out
    return out
