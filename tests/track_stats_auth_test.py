# -*- coding: utf-8 -*-
"""统计端点鉴权回归（ADR-001 增补遗留项）。

    python -m unittest tests.track_stats_auth_test -v

用 fastapi TestClient 模拟非本机来源（client.host = "testclient"），
无需真实网络即可验证公网被拒。
"""
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

TOKEN = "unit-test-secret-42"


def _make_client(token: str, host: str = "testclient"):
    """按给定口令与来源 IP 重建应用（config 在导入期读环境变量，故需重载模块）。"""
    os.environ["TRACK_STATS_TOKEN"] = token
    for m in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    import app.config as config
    importlib.reload(config)
    import app.track as track
    importlib.reload(track)
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app, client=(host, 54321))


class TestStatsAuth(unittest.TestCase):
    def test_loopback_allowed_without_token(self):
        """未配置口令时本机可读——保证本地开发与既有 iter2 用例不被破坏。"""
        client = _make_client("", host="127.0.0.1")
        r = client.get("/api/track/stats")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("counts", r.json())

    def test_public_denied_without_token(self):
        client = _make_client("")  # client.host = "testclient"，模拟公网来源
        r = client.get("/api/track/stats")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "forbidden")

    def test_token_mode_denies_anonymous_even_from_loopback(self):
        client = _make_client(TOKEN, host="127.0.0.1")
        r = client.get("/api/track/stats")
        self.assertEqual(r.status_code, 403)

    def test_token_via_query(self):
        client = _make_client(TOKEN)
        r = client.get(f"/api/track/stats?token={TOKEN}")
        self.assertEqual(r.status_code, 200, r.text)

    def test_token_via_header(self):
        client = _make_client(TOKEN)
        r = client.get("/api/track/stats", headers={"X-Track-Token": TOKEN})
        self.assertEqual(r.status_code, 200, r.text)

    def test_wrong_token_rejected(self):
        client = _make_client(TOKEN)
        r = client.get("/api/track/stats?token=guessed")
        self.assertEqual(r.status_code, 403)

    def test_stats_not_leaking_question_text(self):
        """鉴权通过也不得带出问题原文。"""
        client = _make_client(TOKEN)
        probe = "深基坑支护变形监测限值"
        r = client.post("/api/track", json={"events": [{"event": "chat_submitted", "question": probe}]})
        self.assertEqual(r.status_code, 200, r.text)
        body = client.get(f"/api/track/stats?token={TOKEN}&history=1").text
        self.assertNotIn(probe, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
