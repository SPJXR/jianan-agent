# -*- coding: utf-8 -*-
"""弃答路径审计单测（A-MEM 启示落地，2026-11-15）。"""
import importlib.util
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

_spec = importlib.util.spec_from_file_location(
    "abstention_audit", os.path.join(BASE, "tools", "abstention_audit.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class AbstentionAuditTest(unittest.TestCase):
    def test_abstained_by_backend(self):
        self.assertTrue(mod.is_abstained("", "no_answer"))

    def test_abstained_by_marker(self):
        self.assertTrue(mod.is_abstained("知识库中未找到与该问题直接相关的条款。", "llm"))
        self.assertTrue(mod.is_abstained("本助手仅提供建安法规知识问答。", "llm"))

    def test_hard_answer_detected(self):
        # 本应弃答却给出实质答案（A-MEM 式挤出答案）——硬答数应计数
        self.assertFalse(mod.is_abstained(
            "依据[1]，钢筋热弯应替代为冷弯工艺。", "llm"))

    def test_classify_edge_row_three_way(self):
        # 空响应单列，不得伪造硬答告警（长会话 POC 的判读教训）
        self.assertEqual(mod.classify_edge_row(
            {"answer": "", "backend": "llm"}), "no_response")
        self.assertEqual(mod.classify_edge_row(
            {"answer": "", "backend": "no_answer"}), "abstained")
        self.assertEqual(mod.classify_edge_row(
            {"answer": "未找到相关条款。", "backend": "llm"}), "abstained")
        self.assertEqual(mod.classify_edge_row(
            {"answer": "依据[1]，应采用冷弯工艺。", "backend": "llm"}), "hard")

    def test_boundary_ack_not_hard(self):
        # ctx-24 EDGE-05 真实答案：承认「未列出指标数值」+ 引用佐证不足，
        # 是合理边界说明，不是 A-MEM 式挤出答案（防误报，第 2 次遇到这题）
        ans = ("关于安全帽的具体技术指标，知识库中可依据的条款只涉及应佩戴"
               "符合某国家标准的安全帽，未列出具体技术指标数值。依据条款："
               "安全帽 [9]。")
        self.assertEqual(mod.classify_edge_row(
            {"answer": ans, "backend": "llm"}), "boundary_ack")

    def test_bucket(self):
        self.assertEqual(mod.evidence_bucket(0.8), "high")
        self.assertEqual(mod.evidence_bucket(0.5), "high")
        self.assertEqual(mod.evidence_bucket(0.49), "low")
        self.assertEqual(mod.evidence_bucket(0.0), "low")
        self.assertEqual(mod.evidence_bucket(0.3, cut=0.25), "high")


if __name__ == "__main__":
    unittest.main(verbosity=2)
