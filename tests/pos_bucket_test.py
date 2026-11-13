# -*- coding: utf-8 -*-
"""pos_bucket_ok 单测（LongLLMLingua 位置偏差监测器，2026-11-13）。"""
import importlib.util
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

_spec = importlib.util.spec_from_file_location(
    "run_eval", os.path.join(BASE, "tools", "run_eval.py"))
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def _fact(qid, cite_pos, ok):
    return {"id": qid, "type": "fact", "cite_pos": cite_pos, "ok": ok}


class PosBucketOkTest(unittest.TestCase):
    def test_bucketing_by_max_pos(self):
        # 最高位次决定桶：[1,9] -> 9+；[2,3] -> 1-3；[4] -> 4-8
        rows = [_fact("A", [1, 9], True),      # 9+ 且 ok
                _fact("B", [2, 3], False),     # 1-3 未过
                _fact("C", [4], True),         # 4-8 过
                _fact("D", [], True)]          # 无引用不计
        out = run_eval.pos_bucket_ok(rows)
        self.assertEqual(out["1-3"], "0/1")
        self.assertEqual(out["4-8"], "1/1")
        self.assertEqual(out["9+"], "1/1")

    def test_empty(self):
        out = run_eval.pos_bucket_ok([_fact("D", [], False)])
        self.assertEqual(out["1-3"], "-")
        self.assertEqual(out["9+"], "-")


if __name__ == "__main__":
    unittest.main(verbosity=2)
