# -*- coding: utf-8 -*-
"""3.3 时效状态进上下文 · 单元守卫（上下文改进计划第 3 期第 1 项，2026-11-04）。

守卫性质（纯标准库，python -m unittest tests.validity_ctx_test -v）：
1. 〔状态〕词表与 ADR-006 增补版逐键一致（effective/trial/consultation/repealed）；
2. 未核定（na/unknown/空）不标注——与「未核定不动作」哲学对齐；
3. build_context：consultation 片段头带〔状态〕且说明行存在；
4. build_context：全部未核定时输出与历史版本逐字节一致（零标注零改动红线）；
5. build_context 兼容检索命中的 snake_case 键；
6. live 守卫：当前索引的 valid_status 取值均在词表∪{na,unknown}内，
   且 consultation 恰好 1 份（0070）——防数据漂移把生成侧标注打穿。
"""
import io
import os
import sqlite3
import sys
import unittest

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.llm import _VALIDITY_NOTE, build_context, validity_note  # noqa: E402

DB = os.path.join(BASE, "kb", "kb.sqlite")


def _snip(no, title, clause, text, status=None):
    s = {"no": no, "title": title, "clause": clause, "pages": "", "full": text}
    if status is not None:
        s["validStatus"] = status
    return s


class TestWordTable(unittest.TestCase):
    def test_keys_match_adr006(self):
        self.assertEqual(set(_VALIDITY_NOTE), {"effective", "trial", "consultation", "repealed"})

    def test_unverified_get_no_note(self):
        for v in ("na", "unknown", "", None, "  ", "NA", "Unknown"):
            self.assertEqual(validity_note(v), "", repr(v))

    def test_notes_are_self_explanatory(self):
        # 标注文本必须自带语义（未生效/已废止/现行有效），LLM 无需额外规则即可理解
        self.assertIn("未生效", _VALIDITY_NOTE["consultation"])
        self.assertIn("已废止", _VALIDITY_NOTE["repealed"])
        self.assertIn("现行有效", _VALIDITY_NOTE["trial"])
        self.assertIn("现行有效", _VALIDITY_NOTE["effective"])


class TestBuildContext(unittest.TestCase):
    TEXT = "测试条款原文第一行。\n第二行内容。"

    def test_consultation_annotated_with_lead(self):
        ctx = build_context([_snip(1, "某指南（征求意见稿）", "1.1", self.TEXT, "consultation")])
        self.assertIn("〔状态：征求意见稿，未生效", ctx)
        self.assertTrue(ctx.startswith("（〔状态〕为该文件的人工核定时效状态"))

    def test_all_unverified_byte_identical(self):
        """零标注零改动：全未核定时输出与历史版本格式逐字节一致。"""
        snips = [_snip(1, "文档甲", "第一条", self.TEXT, "unknown"),
                 _snip(2, "文档乙", "", self.TEXT)]
        expected = (
            "[1] 《文档甲》第一条\n测试条款原文第一行。\n第二行内容。\n\n"
            "[2] 《文档乙》\n测试条款原文第一行。\n第二行内容。"
        )
        self.assertEqual(build_context(snips), expected)

    def test_snake_case_hits_supported(self):
        s = _snip(1, "某规定", "第一条", self.TEXT, "trial")
        s["valid_status"] = s.pop("validStatus")
        ctx = build_context([s])
        self.assertIn("〔状态：试行，已印发施行，现行有效〕", ctx)

    def test_lead_absent_when_no_note(self):
        ctx = build_context([_snip(1, "文档甲", "", self.TEXT, "unknown")])
        self.assertNotIn("人工核定时效状态", ctx)


class TestLiveIndex(unittest.TestCase):
    """live 守卫：数据漂移防护（与 validity_test.py 的 live 用例同模式）。"""

    def test_status_values_in_vocab(self):
        con = sqlite3.connect(DB)
        rows = con.execute("select distinct valid_status from docs").fetchall()
        con.close()
        allowed = set(_VALIDITY_NOTE) | {"na", "unknown", ""}
        for (v,) in rows:
            self.assertIn((v or "").strip().lower(), allowed, repr(v))

    def test_exactly_one_consultation_doc(self):
        con = sqlite3.connect(DB)
        rows = con.execute(
            "select doc_id from docs where valid_status='consultation'").fetchall()
        con.close()
        self.assertEqual([r[0] for r in rows], ["0070"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
