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


# 与 tools/run_eval.py 的 REFUSAL_OK ∪ BOUNDARY_OK 同口径（勿各自维护词表）
REFUSAL_MARKERS = ("未找到", "本助手仅提供建安法规知识问答",
                   "未收录", "无该标准", "未随文本入库")

# 缺席承认措辞（2026-11-13 增补）：模型明说「证据不足/未列出」并引用佐证，
# 是**合理行为**而非错误复制——EDGE-05 案例（「未列出具体技术指标数值」
# 并引用 [9][3] 佐证）证明：只用拒答词表会把好答案误判为 copy。
ABSENCE_ACK = ("未列出", "未包含", "未规定", "未明确", "并未", "未直接",
               "无相关", "无具体", "不涉及", "不足以", "无法据以")


def classify_answer(text: str) -> dict:
    """答案形态分类（RECOMP 启示，2026-11-13）：拒答/缺席承认/引用/复制判定。

    copy=True 的语义仅在「证据不含答案」的拒答/边界题上成立：本应答
    「未找到/未收录」，却仍带 [n] 引用给出断言——RECOMP 的「证据无关时
    错误复制」（NQ 完整 Top-5 高达 81%）。
    review=True：带引用但含缺席承认措辞——疑似合理佐证，需人工复核，
    不计入 copy（防止把好答案误报，EDGE-05 即此桶）。
    对正常 fact 题，cited∧¬refusal 是正常作答，调用方不得据此判 copy。
    """
    cites = extract_citations(text)
    refusal = any(m in (text or "") for m in REFUSAL_MARKERS)
    ack = any(m in (text or "") for m in ABSENCE_ACK)
    return {"refusal": refusal, "cited": bool(cites), "ack": ack,
            "copy": bool(cites) and not refusal and not ack,
            "review": bool(cites) and not refusal and ack}


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
        "refusal": False,
    }
    if answer_text:
        cites, bad = check_citations(answer_text, n_sources)
        row["citations"] = sorted(set(cites))
        row["cite_bad"] = sorted(set(bad))
        row["refusal"] = classify_answer(answer_text)["refusal"]
    try:
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # pragma: no cover - 环境性故障
        print(f"[feedback] 台账落盘失败（忽略）: {exc}", file=sys.stderr)
        return False
