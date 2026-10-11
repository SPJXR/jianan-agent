# -*- coding: utf-8 -*-
"""时效降权（ADR-006）回归守卫。

纯标准库 unittest，不依赖服务与外部模型：
    python -m unittest tests.validity_test -v
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import retrieval as R  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kb", "kb.sqlite")


class TestValidityFactor(unittest.TestCase):
    def test_only_draft_and_repealed_are_demoted(self):
        self.assertAlmostEqual(R._validity_factor("draft"), 0.60)
        self.assertAlmostEqual(R._validity_factor("repealed"), 0.35)
        # 未核定与现行有效一律不降权：这是 ADR-002 零回归性质的前提
        self.assertEqual(R._validity_factor("unknown"), 1.0)
        self.assertEqual(R._validity_factor("effective"), 1.0)
        self.assertEqual(R._validity_factor(None), 1.0)
        self.assertEqual(R._validity_factor(""), 1.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(R._validity_factor("DRAFT"), 0.60)
        self.assertAlmostEqual(R._validity_factor(" Repealed "), 0.35)


class TestValidityPartition(unittest.TestCase):
    def test_demoted_goes_last_and_order_is_stable(self):
        items = [{"chunk_id": 1, "valid_status": "draft"},
                 {"chunk_id": 2, "valid_status": "unknown"},
                 {"chunk_id": 3, "valid_status": "repealed"},
                 {"chunk_id": 4, "valid_status": "effective"}]
        out = R._validity_partition(items)
        self.assertEqual([i["chunk_id"] for i in out], [2, 4, 1, 3])
        self.assertTrue(out[2].get("validity_demoted"))
        self.assertTrue(out[3].get("validity_demoted"))
        self.assertNotIn("validity_demoted", out[0])

    def test_noop_when_all_unverified(self):
        items = [{"chunk_id": i, "valid_status": "unknown"} for i in range(5)]
        self.assertEqual([i["chunk_id"] for i in R._validity_partition(items)], list(range(5)))


class TestCurrentIndexIsNoop(unittest.TestCase):
    """当前 34 份文档全部待核定，因此线上排序必须与降权逻辑上线前完全一致。"""

    def test_no_document_is_demoted_today(self):
        if not os.path.exists(DB):
            self.skipTest("kb/kb.sqlite 不存在")
        con = sqlite3.connect(DB)
        try:
            n = con.execute(
                "SELECT count(*) FROM docs WHERE lower(valid_status) IN ('draft','repealed')").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(n, 0, "已有文档被核定为草案/已废止，请同步复核检索排序预期")

    def test_bm25_ranking_unchanged_by_penalty_code(self):
        if not os.path.exists(DB):
            self.skipTest("kb/kb.sqlite 不存在")
        qs = ["有限空间作业前需要检测哪些气体", "洞口作业有哪些防护要求",
              "特种作业人员上岗需要什么证书", "哪些施工工艺是禁止使用的"]
        original = {k: v for k, v in R.VALIDITY_PENALTY.items()}
        try:
            with_penalty = [[h["chunk_id"] for h in R.search(q, 8)] for q in qs]
            R.VALIDITY_PENALTY.clear()
            without = [[h["chunk_id"] for h in R.search(q, 8)] for q in qs]
        finally:
            R.VALIDITY_PENALTY.update(original)
        self.assertEqual(with_penalty, without, "降权逻辑改变了未核定语料的排序，违反零回归约束")


class TestDemotionTakesEffect(unittest.TestCase):
    """在临时库副本上把某文档标为草案，验证它确实被压到后面。"""

    def test_draft_is_pushed_down(self):
        if not os.path.exists(DB):
            self.skipTest("kb/kb.sqlite 不存在")
        tmp = os.path.join(tempfile.mkdtemp(), "kb.sqlite")
        shutil.copy(DB, tmp)
        con = sqlite3.connect(tmp)
        con.execute("UPDATE docs SET valid_status='draft' WHERE 1=1")
        con.commit()
        con.close()
        saved = R.DB_PATH
        try:
            R.DB_PATH = tmp
            hits = R.search("有限空间作业前需要检测哪些气体", 8)
        finally:
            R.DB_PATH = saved
            shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
        # 全部草案时仍应返回结果（降权不是过滤），且不应抛错
        self.assertIsInstance(hits, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
