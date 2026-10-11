# -*- coding: utf-8 -*-
"""上线测试问题集回归（docs/上线测试问题集.md）。

用法（推荐用项目 venv，含 jieba）：
    .venv/Scripts/python.exe tests/qa_regression.py

检查内容：
1. 每条库内题（A 组 + C 组）的 top 命中覆盖率不得低于 MIN_COVERAGE（默认 0.25），
   低于阈值即视为「会走未找到兜底」，属于必须修的回归失败。
2. 打印 top 命中文档，便于人工核对是否命中预期文档。
3. 库外题（B 组）不设断言，仅打印命中情况供人工判断（兜底是预期行为）。

退出码：0 全通过 / 1 存在低于阈值的题。
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app import config, retrieval  # noqa: E402

# (题号, 问题, 预期文档) —— 预期文档来自 docs/上线测试问题集.md
IN_SCOPE = [
    ("A1", "特种作业人员报名考核需要满足什么条件？", "0063/0064"),
    ("A2", "特种作业操作资格考核成绩能保留多久？", "0063/0064"),
    ("A3", "施工现场的安全网有什么要求？可以用普通的密目网吗？", "0072"),
    ("A4", "桩头凿除有什么规定？", "0072"),
    ("A5", "专项施工方案里毗邻建筑物没有防护措施算严重缺陷吗？", "0071"),
    ("A6", "起重吊装的专项施工方案要注意什么？", "0071/0073"),
    ("A7", "震后应急评估专家组可以采取哪些措施？", "0011"),
    ("A8", "震后建筑安全评估专家队由谁管理？", "0003"),
    ("A9", "项目开工怎么办理？走什么流程？", "0067"),
    ("A10", "历史文化街区划定有什么标准？", "0006"),
    ("C1", "工地上挖坑底下干活有啥危险要注意的？", "0069/0070（口语，弱命中走 LLM 改写）"),
    ("C2", "考特种作业证有年龄限制没？", "0063/0064"),
    ("C3", "震完了房子咋评估谁能去评？", "0011/0003（口语，弱命中走 LLM 改写）"),
    ("C4", "密目网着火了怎么办", "0072（口语，弱命中走 LLM 改写）"),
]

OUT_OF_SCOPE = [
    ("B1", "工地食堂需要办理什么证照？"),
    ("B2", "高温天气工地几点到几点不允许室外作业？"),
    ("B3", "塔吊司机证怎么复审？"),
    ("B4", "帮我写一首关于安全的诗"),
    ("B5", "住建部现任部长是谁？"),
]


def main() -> int:
    threshold = config.MIN_COVERAGE
    rewrite_threshold = config.REWRITE_MIN_COVERAGE
    print("MIN_COVERAGE=%.2f  REWRITE_MIN_COVERAGE=%.2f" % (threshold, rewrite_threshold))
    print()
    print("--- 库内题（低于 %.2f 即 FAIL）---" % threshold)
    failures = []
    for tag, q, expect in IN_SCOPE:
        hits = retrieval.search(q, config.RETRIEVAL_TOP_K)
        top = hits[0] if hits else None
        cov = top["coverage"] if top else 0.0
        ok = cov >= threshold
        if not ok:
            failures.append(tag)
        flag = "PASS" if ok else "FAIL"
        note = ""
        if ok and cov < rewrite_threshold:
            note = "（弱命中，线上会触发 LLM 改写后重检）"
        print("  %s %-4s cov=%.2f [%s] %s | 预期 %s%s" % (
            flag, tag, cov, top["doc_id"] if top else "-", q[:20], expect, note))

    print()
    print("--- 库外题（仅打印，兜底为预期行为）---")
    for tag, q in OUT_OF_SCOPE:
        hits = retrieval.search(q, config.RETRIEVAL_TOP_K)
        top = hits[0] if hits else None
        print("  INFO %-4s cov=%s [%s] %s" % (
            tag, ("%.2f" % top["coverage"]) if top else "-",
            top["doc_id"] if top else "-", q[:22]))

    print()
    if failures:
        print("RESULT: FAIL — 以下题低于阈值，线上会走未找到兜底：%s" % ", ".join(failures))
        return 1
    print("RESULT: PASS — 全部 %d 道库内题通过阈值" % len(IN_SCOPE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
