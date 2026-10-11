# -*- coding: utf-8 -*-
"""Mock OpenAI 兼容 SSE 服务：验证 LLM 流式链路（无真实 Key 时的联调用）"""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.endswith("/chat/completions"):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            auth = self.headers.get("Authorization", "")
            if auth != "Bearer test-key":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"Invalid API key"}}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            pieces = [
                "有限空间作业前必须先通风并检测气体，",
                "合格后方可进入 [1]。",
                "\\n\\n依据条款：\\n",
                "1. 作业前必须采取通风措施，且保持空气流通 30min 以上 [1]；",
                "经通风后气体检测结果仍不合格的，不得进入作业 [2]。",
            ]
            for i, p in enumerate(pieces):
                chunk = {
                    "choices": [{"delta": {"content": p.replace("\\n", "\n")}, "index": i}]
                }
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.15)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 18765), Handler).serve_forever()
