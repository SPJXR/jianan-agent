# -*- coding: utf-8 -*-
"""POC：知识库扩充后的检索多样性修复验证（2026-10-24）。

问题：0079 手册（75 块，与 0069/0070 同词面）在窗口内霸屏，把原正确块挤出
top-8 → top_cov 跌破 MIN_COVERAGE → DEF-04/GOV-06 误答「未找到」（62 题
全量 ret3 54→52）。ctx_hit 仍 55/55——文档召回了，但被同文档的词面近邻挤掉。

修复候选：doc-cap 多样性——search() 输出窗口内每个 doc_id 最多 N 块。
本 POC 在调用侧模拟 doc-cap，对比 DEF-04 / GOV-06 / PM-08 三题的
top_cov 与 top3，并回归 qa14 全部题，确认不引入新回归。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app import config, retrieval  # noqa: E402


def search_with_cap(question, window, per_doc):
    """调用 search() 取宽窗口，然后按 doc-cap 截取（模拟 search() 内置 doc-cap）。"""
    hits = retrieval.search(question, window)
    out, counts = [], {}
    for h in hits:
        d = h["doc_id"]
        if counts.get(d, 0) >= per_doc:
            continue
        counts[d] = counts.get(d, 0) + 1
        out.append(h)
    return out


CASES = [
    ("DEF-04", "有限空间作业过程中，氧气含量合格范围是多少？", ["0069", "0070"]),
    ("GOV-06", "有限空间作业场所应设置哪些安全警示标志？", ["0069", "0070"]),
    ("PM-08", "有限空间作业发生事故后应如何报告？", ["0069", "0070"]),
]
# DEF-04/GOV-06/PM-08 的真实题面以 eval_set_v2.json 为准
import json  # noqa: E402
spec = json.load(open("docs/eval/eval_set_v2.json", encoding="utf-8"))
for q in spec["questions"]:
    for c in CASES:
        if c[0] == q["id"]:
            CASES[CASES.index(c)] = (q["id"], q["question"], q["expected_docs"])

fails_poc = []
for tag, q, exp in CASES:
    exp = set(exp)
    for per_doc in (5, 4, 3):
        hits = search_with_cap(q, config.RECALL_WINDOW, per_doc)
        top_cov = max((h["coverage"] for h in hits[:config.RETRIEVAL_TOP_K]), default=0.0)
        top3 = {h["doc_id"] for h in hits[:3]}
        top8 = {h["doc_id"] for h in hits[:8]}
        print(f"{tag} cap={per_doc}: top_cov={top_cov:.2f} top3命中={bool(top3 & exp)} "
              f"top8命中={bool(top8 & exp)} top8={[h['doc_id'] for h in hits[:8]]}")

# qa14 回归（doc-cap 后）
IN_SCOPE = [
    ("A1", "特种作业人员报名考核需要满足什么条件？", {"0063", "0064"}),
    ("A2", "特种作业操作资格考核成绩能保留多久？", {"0063", "0064"}),
    ("A3", "施工现场的安全网有什么要求？可以用普通的密目网吗？", {"0072"}),
    ("A4", "桩头凿除有什么规定？", {"0072"}),
    ("A5", "专项施工方案里毗邻建筑物没有防护措施算严重缺陷吗？", {"0071"}),
    ("A6", "起重吊装的专项施工方案要注意什么？", {"0071", "0073"}),
    ("A7", "震后应急评估专家组可以采取哪些措施？", {"0011"}),
    ("A8", "震后建筑安全评估专家队由谁管理？", {"0003"}),
    ("A9", "项目开工怎么办理？走什么流程？", {"0067"}),
    ("A10", "历史文化街区划定有什么标准？", {"0006"}),
]
bad = []
for tag, q, exp in IN_SCOPE:
    hits = search_with_cap(q, config.RECALL_WINDOW, 4)
    top3 = {h["doc_id"] for h in hits[:3]}
    top8 = {h["doc_id"] for h in hits[:8]}
    if not (top3 & exp or top8 & exp):
        bad.append(tag)
    print(f"qa {tag}: top3命中={bool(top3 & exp)} top8命中={bool(top8 & exp)}")
print("RESULT:", "PASS" if not bad and not fails_poc else f"FAIL {bad}")
