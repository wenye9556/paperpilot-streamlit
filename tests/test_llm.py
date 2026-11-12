import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import llm  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    status = 200
    content = "OK"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.status >= 400:
            body = json.dumps({"error": {"message": "mock failure"}}).encode()
        else:
            body = json.dumps({
                "choices": [{"message": {"content": self.content}}]
            }).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: D401
        pass


class LLMTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.cfg = llm.LLMConfig(
            base_url=f"http://127.0.0.1:{cls.port}/v1",
            api_key="test-key",
            model="mock-model",
            timeout=10,
        )

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def tearDown(self):
        _Handler.status = 200
        _Handler.content = "OK"

    def test_endpoint_normalization(self):
        self.assertEqual(llm.endpoint("https://api.deepseek.com"),
                         "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(llm.endpoint("https://api.openai.com/v1"),
                         "https://api.openai.com/v1/chat/completions")
        self.assertEqual(llm.endpoint("https://x.test/v1/chat/completions"),
                         "https://x.test/v1/chat/completions")
        self.assertEqual(llm.endpoint(""), "")

    def test_parse_intent(self):
        _Handler.content = "```json\n" + json.dumps({
            "query": "urban logistics drone scheduling",
            "tags": ["城市物流", "无人机"],
            "note": "已翻译",
        }, ensure_ascii=False) + "\n```"
        out = llm.parse_intent(self.cfg, "城市物流无人机调度")
        self.assertEqual(out["query"], "urban logistics drone scheduling")
        self.assertIn("无人机", out["tags"])

    def test_explain_items(self):
        _Handler.content = json.dumps([
            {"id": "doi:10.1/a", "why": "把卡车与无人机协同路径建模为混合整数规划。"},
        ], ensure_ascii=False)
        out = llm.explain_items(self.cfg, "drone", [{"key": "doi:10.1/a", "title": "T"}])
        self.assertIn("doi:10.1/a", out)

    def test_summarize(self):
        _Handler.content = "本批 50 篇，13 篇达到阈值，建议先读三篇。"
        text = llm.summarize(self.cfg, "drone", {"page": 50, "rec": 13}, [])
        self.assertIn("50", text)

    def test_http_error(self):
        _Handler.status = 500
        with self.assertRaises(llm.LLMError):
            llm.test_connection(self.cfg)

    def test_bad_json(self):
        _Handler.content = "这不是 JSON"
        with self.assertRaises(llm.LLMError):
            llm.parse_intent(self.cfg, "x")

    def test_extract_json_surrounding_text(self):
        data = llm._extract_json('说明文字 {"a": [1, 2]} 结束')
        self.assertEqual(data, {"a": [1, 2]})


if __name__ == "__main__":
    unittest.main()
