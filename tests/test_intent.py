import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import intent  # noqa: E402


class IntentTest(unittest.TestCase):
    def test_urban_drone(self):
        r = intent.parse("城市物流无人机调度")
        self.assertEqual(r["query"], "urban logistics drone scheduling")
        self.assertIn("无人机", r["tags"])
        self.assertEqual(r["source"], "glossary")

    def test_truck_drone(self):
        r = intent.parse("卡车无人机协同配送路径规划")
        for word in ("truck", "drone", "collaborative", "delivery", "routing"):
            self.assertIn(word, r["query"])

    def test_english_passthrough(self):
        r = intent.parse("truck drone collaborative delivery routing")
        self.assertEqual(r["query"], "truck drone collaborative delivery routing")
        self.assertEqual(r["source"], "english")

    def test_english_expansion(self):
        r = intent.parse("VRP with time windows")
        self.assertIn("vehicle routing problem", r["query"])

    def test_unknown_chinese(self):
        r = intent.parse("玄学养生")
        self.assertEqual(r["source"], "fallback")
        self.assertTrue(r["unknown"])

    def test_empty(self):
        r = intent.parse("   ")
        self.assertEqual(r["source"], "empty")

    def test_mixed(self):
        r = intent.parse("用 LLM 做 供应链韧性 预测")
        self.assertIn("large language model", r["query"])
        self.assertIn("supply chain", r["query"])


if __name__ == "__main__":
    unittest.main()
