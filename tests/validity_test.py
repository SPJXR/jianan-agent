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
    def test_only_unborn_and_repealed_are_demoted(self):
        self.assertAlmostEqual(R._validity_factor("consultation"), 0.15)
        self.assertAlmostEqual(R._validity_factor("repealed"), 0.35)
        # 试行=已印发且现行有效，与征求意见稿效力相反，不得一并降权
        self.assertEqual(R._validity_factor("trial"), 1.0)
        # 未核定、附件类与现行有效一律不降权：这是 ADR-002 零回归性质的前提
        self.assertEqual(R._validity_factor("unknown"), 1.0)
        self.assertEqual(R._validity_factor("na"), 1.0)
        self.assertEqual(R._validity_factor("effective"), 1.0)
        self.assertEqual(R._validity_factor(None), 1.0)
        self.assertEqual(R._validity_factor(""), 1.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(R._validity_factor("CONSULTATION"), 0.15)
        self.assertAlmostEqual(R._validity_factor(" Repealed "), 0.35)


class TestValidityPartition(unittest.TestCase):
    def test_demoted_goes_last_and_order_is_stable(self):
        items = [{"chunk_id": 1, "valid_status": "consultation"},
                 {"chunk_id": 2, "valid_status": "unknown"},
                 {"chunk_id": 3, "valid_status": "repealed"},
                 {"chunk_id": 4, "valid_status": "trial"}]
        out = R._validity_partition(items)
        self.assertEqual([i["chunk_id"] for i in out], [2, 4, 1, 3])
        self.assertTrue(out[2].get("validity_demoted"))
        self.assertTrue(out[3].get("validity_demoted"))
        self.assertNotIn("validity_demoted", out[0])

    def test_noop_when_all_unverified(self):
        items = [{"chunk_id": i, "valid_status": "unknown"} for i in range(5)]
        self.assertEqual([i["chunk_id"] for i in R._validity_partition(items)], list(range(5)))

    def test_trial_is_never_reordered(self):
        items = [{"chunk_id": i, "valid_status": "trial"} for i in range(5)]
        self.assertEqual([i["chunk_id"] for i in R._validity_partition(items)], list(range(5)))


class TestZeroRegressionOnUnverifiedCorpus(unittest.TestCase):
    """前提：语料中没有任何已核定的草案/废止文档时，降权代码必须是恒等变换。

    这是 ADR-002「强命中零回归」性质的守卫。用例在临时库副本上把所有文档重置为
    unknown 来构造该前提，因此不依赖真实 docs_meta.json 的核定进度。
    """

    def _temp_db(self, status):
        tmp = os.path.join(tempfile.mkdtemp(), "kb.sqlite")
        shutil.copy(DB, tmp)
        con = sqlite3.connect(tmp)
        con.execute("UPDATE docs SET valid_status=?", (status,))
        con.commit()
        con.close()
        return tmp

    def test_ranking_identical_when_nothing_demoted(self):
        if not os.path.exists(DB):
            self.skipTest("kb/kb.sqlite 不存在")
        qs = ["有限空间作业前需要检测哪些气体", "洞口作业有哪些防护要求",
              "特种作业人员上岗需要什么证书", "哪些施工工艺是禁止使用的"]
        tmp = self._temp_db("unknown")
        saved = R.DB_PATH
        original = {k: v for k, v in R.VALIDITY_PENALTY.items()}
        try:
            R.DB_PATH = tmp
            with_penalty = [[h["chunk_id"] for h in R.search(q, 8)] for q in qs]
            R.VALIDITY_PENALTY.clear()
            without = [[h["chunk_id"] for h in R.search(q, 8)] for q in qs]
        finally:
            R.DB_PATH = saved
            R.VALIDITY_PENALTY.update(original)
            shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
        self.assertEqual(with_penalty, without, "全未核定的语料上降权改变了排序，违反零回归约束")

    def test_trial_only_corpus_also_unchanged(self):
        """试行文件同样不得被降权——它与征求意见稿效力相反。"""
        if not os.path.exists(DB):
            self.skipTest("kb/kb.sqlite 不存在")
        q = "有限空间作业前需要检测哪些气体"
        tmp = self._temp_db("trial")
        saved = R.DB_PATH
        original = {k: v for k, v in R.VALIDITY_PENALTY.items()}
        try:
            R.DB_PATH = tmp
            a = [h["chunk_id"] for h in R.search(q, 8)]
            R.VALIDITY_PENALTY.clear()
            b = [h["chunk_id"] for h in R.search(q, 8)]
        finally:
            R.DB_PATH = saved
            R.VALIDITY_PENALTY.update(original)
            shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
        self.assertEqual(a, b)


class TestDemotionTakesEffect(unittest.TestCase):
    """在临时库副本上自造基线：先全部 unknown，再把 0070 标为征求意见稿。"""

    def test_consultation_is_pushed_down(self):
        if not os.path.exists(DB):
            self.skipTest("kb/kb.sqlite 不存在")
        tmp = os.path.join(tempfile.mkdtemp(), "kb.sqlite")
        shutil.copy(DB, tmp)
        con = sqlite3.connect(tmp)
        con.execute("UPDATE docs SET valid_status='unknown'")
        con.commit()
        con.close()
        q = "有限空间作业前需要检测哪些气体"
        saved = R.DB_PATH
        try:
            R.DB_PATH = tmp
            before = [h["doc_id"] for h in R.search(q, 8)]
            con = sqlite3.connect(tmp)
            con.execute("UPDATE docs SET valid_status='consultation' WHERE doc_id='0070'")
            con.commit()
            con.close()
            after = [h["doc_id"] for h in R.search(q, 8)]
        finally:
            R.DB_PATH = saved
            shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
        self.assertIn("0070", before, "基线未命中 0070，用例前提不成立")
        # 降权足够强时 0070 会直接掉出 top-k；这算生效，但必须先确认 after 非空，
        # 否则"检索整体失败返回空表"会让本用例假绿。
        self.assertTrue(after, "降权后检索返回空结果，属异常而非降权生效")
        self.assertTrue(
            "0070" not in after or after.index("0070") > before.index("0070"),
            f"标为征求意见稿后 0070 未被压后：before={before} after={after}")

    def test_live_index_no_longer_leads_with_draft(self):
        """真实库已核定：征求意见稿不得出现在前 5 位依据中。

        2026-10-24 二次修订：知识库扩充后（0079 应急部手册 / 0078 部令 13 号均为
        effective 同主题官方文档），top5 已合法地不再包含 0069——本断言的被测对象
        是「征求意见稿的降权行为」（ADR-006），不是住建文档的排序。断言收敛为：
        ① 0070 不得出现在 top5；② top5 无任何 consultation 状态文档；
        ③ 试行版 0069 仍须留在 top8 上下文（住建场景的用户仍能看到它）。"""
        if not os.path.exists(DB):
            self.skipTest("kb/kb.sqlite 不存在")
        hits, _ = R.hybrid_search("有限空间作业前需要检测哪些气体？", 8)
        top5 = [h["doc_id"] for h in hits[:5]]
        top8 = [h["doc_id"] for h in hits[:8]]
        self.assertNotIn("0070", top5, "征求意见稿仍占据前 5 位依据")
        drafts = {h["doc_id"] for h in hits[:8]
                  if (h.get("valid_status") or "") == "consultation"}
        self.assertEqual(drafts, set(), f"征求意见稿状态文档占据前 8 位依据：{drafts}")
        self.assertIn("0069", top8, f"试行版 0069 未进入 top8 上下文，实际 {top8}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
