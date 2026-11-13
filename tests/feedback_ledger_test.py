# -*- coding: utf-8 -*-
"""反馈台账单测（ADR-011，ACE 启示落地）。

覆盖：
- 引用编号提取与白名单校验纯函数（含越界、重复、多位数）；
- qhash 稳定性与不可逆长度；
- log_feedback 落盘行结构（tmp 路径重定向）+ 原文不落盘合规口径；
- 落盘异常不影响主链路（抛错路径吞掉返回 False）。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import feedback  # noqa: E402


class CitationCheckTest(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(feedback.extract_citations("依据[1]和[3]，另见[1]"),
                         [1, 3, 1])

    def test_extract_none(self):
        self.assertEqual(feedback.extract_citations("无引用（一）"), [])
        self.assertEqual(feedback.extract_citations(""), [])

    def test_check_ok(self):
        cites, bad = feedback.check_citations("见[1]与[14]", 14)
        self.assertEqual(cites, [1, 14])
        self.assertEqual(bad, [])

    def test_check_bad(self):
        cites, bad = feedback.check_citations("见[15]与[0]", 14)
        self.assertEqual(cites, [15, 0])
        self.assertEqual(bad, [15, 0])  # 越界按出现顺序（含 0）

    def test_check_no_sources(self):
        # 兜底路径 n_sources=0：任何 [n] 都算越界
        cites, bad = feedback.check_citations("[3]", 0)
        self.assertEqual(bad, [3])

    def test_multi_digit(self):
        cites, bad = feedback.check_citations("[12]", 8)
        self.assertEqual(cites, [12])
        self.assertEqual(bad, [12])


class ClassifyAnswerTest(unittest.TestCase):
    def test_bare_refusal(self):
        cls = feedback.classify_answer("知识库中未找到与该问题直接相关的条款。")
        self.assertTrue(cls["refusal"])
        self.assertFalse(cls["cited"])
        self.assertFalse(cls["copy"])

    def test_copy_from_context(self):
        # 证据无关却仍带引用断言（RECOMP 错误复制形态）
        cls = feedback.classify_answer("根据[2]，检查时需提前三日书面告知[4]。")
        self.assertFalse(cls["refusal"])
        self.assertTrue(cls["cited"])
        self.assertTrue(cls["copy"])

    def test_refusal_with_citation(self):
        # 拒答但引用了片段说明（带说明形态，不是 copy）
        cls = feedback.classify_answer("未找到。说明：片段[10]仅为定义，并非判定条件。")
        self.assertTrue(cls["refusal"])
        self.assertTrue(cls["cited"])
        self.assertFalse(cls["copy"])

    def test_boundary_marker(self):
        cls = feedback.classify_answer("该标准未随文本入库，仅名称收录于目录。")
        self.assertTrue(cls["refusal"])

    def test_absence_ack_is_review_not_copy(self):
        # EDGE-05 真实答案（ctx-24）：承认未列出指标并引用佐证——合理行为，
        # 应进 review 桶而非 copy（误报防线，2026-11-13）
        cls = feedback.classify_answer(
            "知识库中可依据的条款只涉及应佩戴符合某国家标准的安全帽，"
            "未列出具体技术指标数值。依据条款：安全帽 [9]。")
        self.assertFalse(cls["refusal"])
        self.assertTrue(cls["cited"])
        self.assertTrue(cls["ack"])
        self.assertFalse(cls["copy"])
        self.assertTrue(cls["review"])


class QhashTest(unittest.TestCase):
    def test_stable_and_short(self):
        h1 = feedback.qhash("证书快到期了怎么办理延续")
        h2 = feedback.qhash("证书快到期了怎么办理延续")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_strip_semantics(self):
        # 前后空白不进指纹（与 log_feedback 落盘口径一致，是有意行为）
        self.assertEqual(feedback.qhash("abc"), feedback.qhash(" abc "))
        self.assertNotEqual(feedback.qhash("abc"), feedback.qhash("abd"))


class LogFeedbackTest(unittest.TestCase):
    def _tmp(self):
        d = tempfile.mkdtemp()
        return os.path.join(d, "ledger.jsonl")

    def test_row_shape_and_privacy(self):
        path = self._tmp()
        with mock.patch.object(feedback, "LEDGER_PATH", path):
            ok = feedback.log_feedback(
                "有限空间作业场景的判定条件原文是怎么规定的？",
                "gov", "llm", 0.5, 14,
                {"validity": True, "adjacent": 1,
                 "rewrite_attempted": False, "rewrite_merged": False},
                "依据[1]与[3]，另见[99]")
        self.assertTrue(ok)
        with open(path, encoding="utf-8") as f:
            row = json.loads(f.read().splitlines()[0])
        # 结构
        self.assertEqual(row["role"], "gov")
        self.assertEqual(row["backend"], "llm")
        self.assertEqual(row["n_sources"], 14)
        self.assertEqual(row["feats"]["adjacent"], 1)
        self.assertEqual(row["citations"], [1, 3, 99])
        self.assertEqual(row["cite_bad"], [99])  # 越界被机械自检抓住
        # 合规：不存问题原文
        self.assertNotIn("有限空间", json.dumps(row, ensure_ascii=False))
        self.assertEqual(row["qhash"],
                         feedback.qhash("有限空间作业场景的判定条件原文是怎么规定的？"))
        self.assertEqual(row["qlen"], 22)

    def test_no_answer_row(self):
        path = self._tmp()
        with mock.patch.object(feedback, "LEDGER_PATH", path):
            ok = feedback.log_feedback(
                "随便问", "default", "no_answer", 0.1, 3,
                {"validity": False, "adjacent": 0})
        self.assertTrue(ok)
        with open(path, encoding="utf-8") as f:
            row = json.loads(f.read().splitlines()[0])
        self.assertEqual(row["citations"], [])
        self.assertEqual(row["feats"]["rewrite_attempted"], False)

    def test_failure_never_raises(self):
        # 落到一个不可写路径：吞异常返回 False，不抛出（主链路红线）
        with mock.patch.object(feedback, "LEDGER_PATH",
                               os.path.join("Z:\\", "no", "such", "ledger.jsonl")):
            ok = feedback.log_feedback(
                "q", "default", "llm", None, 5, {})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
