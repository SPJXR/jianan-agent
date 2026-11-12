# -*- coding: utf-8 -*-
"""反馈台账（2026-11-12，ACE 启示落地：P2+ 在线自检反馈发生器 + P3+ 段计数数据源）。

动机（docs/research/论文精读-ACE-ICLR2026-20261111.md §3.2/§3.3）：
- GOV-06 跨日漂移 / VAL-02 拒答格式抖动此前靠人肉「复测 3 次」归因——本台账把
  每次问答的段特征与结果机械落盘，让「同一特征不同结果」的漂移自动显形；
- ACE 的核心结论：上下文演化必须依赖可靠的机械反馈。本系统的自然执行反馈 =
  引用编号白名单校验（零标注、规则可判），从「只给用户看」升级为「落台账供
  段计数与后续演化决策消费」。

设计约束（与 app/track.py / PRD §11 同口径）：
- 只存问题哈希与长度，**不存问题原文**、不存用户身份、不存 IP 明文；
- 落盘 best-effort：任何异常吞掉并打一行 stderr，**绝不影响问答主链路**；
- 校验纯函数与落盘分离，便于单测。

行结构（data/feedback_ledger.jsonl，一行一问，UTF-8 追加写）：
    {"ts": "...", "qhash": "...", "qlen": 42, "role": "pm", "backend": "llm",
     "coverage": 0.45, "n_sources": 14,
     "feats": {"validity": true, "adjacent": 1, "rewrite_attempted": false,
               "rewrite_merged": false},
     "citations": [1, 3], "cite_bad": [], "answer_chars": 831}

段口径（与 ADR-006/3.3、ADR-005 增补/3.1 同源，勿另起炉灶）：
- validity：上下文任一片段 valid_status 有〔状态〕标注（effective/trial/
  consultation/repealed；na/unknown/空不算）；
- adjacent：相邻注入块数（0~3）；
- rewrite：两阶段改写是否尝试 / 是否触发并集合并。
"""
import hashlib
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_PATH = os.path.join(BASE, "data", "feedback_ledger.jsonl")

# 与 tools/run_eval.py 的 CITE_RE 同口径（答案里 [n] 样式）
_CITE_RE = re.compile(r"\[(\d{1,3})\]")


def extract_citations(text: str) -> list[int]:
    """提取答案中全部 [n] 引用编号（按出现顺序，含重复）。"""
    return [int(m) for m in _CITE_RE.findall(text or "")]


def check_citations(text: str, n_sources: int) -> tuple[list[int], list[int]]:
    """机械白名单校验：返回 (全部编号, 越界编号)。

    越界 = 编号不在 1..n_sources——即答案引用了上下文里不存在的片段，
    这是逐字引用契约的第一层防线（在线轻量版；库内逐字比对仍是离线
    verify_verbatim.py 的职责，两者不互相替代）。
    """
    cites = extract_citations(text)
    bad = [n for n in cites if not (1 <= n <= n_sources)]
    return cites, bad


def qhash(question: str, width: int = 16) -> str:
    """问题指纹：SHA1 前 width 位。评测题可由 tools/segment_ledger.py 用
    题面文本哈希回连线上流量，普通用户问题不可逆推。"""
    return hashlib.sha1((question or "").strip().encode("utf-8")).hexdigest()[:width]


def log_feedback(question: str, role: str, backend: str, coverage, n_sources: int,
                 feats: dict, answer_text: str | None = None) -> bool:
    """追加一行台账。best-effort：失败只打日志返回 False，绝不抛出。

    answer_text 仅用于就地提取引用编号做机械校验，编号与字符数落盘，
    原文不落盘（同 track.py 合规口径）。
    """
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "qhash": qhash(question),
        "qlen": len(question or ""),
        "role": role,
        "backend": backend,
        "coverage": None if coverage is None else round(float(coverage), 4),
        "n_sources": int(n_sources),
        "feats": {
            "validity": bool(feats.get("validity")),
            "adjacent": int(feats.get("adjacent") or 0),
            "rewrite_attempted": bool(feats.get("rewrite_attempted")),
            "rewrite_merged": bool(feats.get("rewrite_merged")),
        },
        "citations": [],
        "cite_bad": [],
        "answer_chars": len(answer_text or ""),
    }
    if answer_text:
        cites, bad = check_citations(answer_text, n_sources)
        row["citations"] = sorted(set(cites))
        row["cite_bad"] = sorted(set(bad))
    try:
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # pragma: no cover - 环境性故障
        print(f"[feedback] 台账落盘失败（忽略）: {exc}", file=sys.stderr)
        return False
