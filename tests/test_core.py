import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402


def work(title="A study of truck drone routing", year=2024, cited=10,
         issn="0968-090X", venue="Transportation Research Part C",
         abstract="We propose a mixed-integer model and a heuristic for truck drone routing.",
         doi="10.1000/test", oa=True, tags=("openalex",),
         url="https://example.org/x", oa_url="", score_hint=0.0):
    return {
        "title": title,
        "abstract": abstract,
        "year": year,
        "cited": cited,
        "venue": venue,
        "issn": issn,
        "is_top": issn in core.TOP_NAME,
        "is_oa": oa,
        "oa_url": oa_url,
        "score_hint": score_hint,
        "authors": ["Alice Zhang", "Bob Li"],
        "doi": doi,
        "url": url,
        "source_tags": list(tags),
    }


class TextTest(unittest.TestCase):
    def test_tokenize_english(self):
        toks = core.tokenize("Truck-drone collaborative delivery routing")
        self.assertIn("truck", toks)
        self.assertIn("routing", toks)
        self.assertNotIn("the", toks)

    def test_tokenize_chinese(self):
        toks = core.tokenize("无人机路径规划")
        self.assertIn("无人", toks)
        self.assertIn("路径", toks)

    def test_abstract_from_inverted(self):
        inv = {"hello": [0], "world": [1], "again": [2]}
        self.assertEqual(core.abstract_from_inverted(inv), "hello world again")
        self.assertEqual(core.abstract_from_inverted(None), "")


class FilterTest(unittest.TestCase):
    def test_filter_contains_expected(self):
        f = core.build_filter(365, 5, True, True)
        self.assertIn("type:article", f)
        self.assertIn("cited_by_count:>5", f)
        self.assertIn("is_oa:true", f)
        self.assertIn("primary_location.source.issn:", f)

    def test_no_window(self):
        f = core.build_filter(0, 0, False, False)
        self.assertEqual(f, "type:article")


class NormalizeTest(unittest.TestCase):
    def test_openalex_normalize(self):
        raw = {
            "title": "Drone routing",
            "publication_year": 2025,
            "cited_by_count": 7,
            "doi": "https://doi.org/10.1/ABC",
            "open_access": {"is_oa": True},
            "primary_location": {
                "source": {"issn_l": "0968-090X", "issn": ["0968-090X"],
                           "display_name": "TR Part C"},
                "landing_page_url": "https://example.org/a",
            },
            "authorships": [{"author": {"display_name": "A. Zhang"}}],
            "abstract_inverted_index": {"drone": [0], "routing": [1]},
        }
        row = core.normalize_openalex_work(raw)
        self.assertEqual(row["doi"], "10.1/abc")
        self.assertTrue(row["is_top"])
        self.assertEqual(row["abstract"], "drone routing")
        self.assertEqual(row["authors"], ["A. Zhang"])


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.items = core.score_all([
            work(),
            work(title="Unrelated paper on fish", abstract="", cited=0,
                 issn="", venue="", doi=""),
        ], "truck drone routing")

    def test_bounds(self):
        for it in self.items:
            for v in it["dims"].values():
                self.assertGreaterEqual(v, 0)
                self.assertLessEqual(v, 100)
            self.assertGreaterEqual(it["total"], 0)
            self.assertLessEqual(it["total"], 100)

    def test_relevant_first(self):
        self.assertEqual(self.items[0]["title"], "A study of truck drone routing")

    def test_threshold_effect(self):
        low = core.score_all([work()], "truck drone routing", threshold=10)
        high = core.score_all([work()], "truck drone routing", threshold=99)
        self.assertTrue(low[0]["rec"])
        self.assertFalse(high[0]["rec"])

    def test_evidence_gate(self):
        rows = core.score_all([work(title="Only title", year=2024, issn="", venue="",
                                    doi="", abstract="", cited=0, url="")],
                              "truck drone", threshold=1)
        self.assertFalse(rows[0]["evid_ok"])
        self.assertFalse(rows[0]["rec"])

    def test_reason_and_summary(self):
        for it in self.items:
            self.assertTrue(it["why"])
        s = core.summarize(self.items, 2)
        self.assertEqual(s["page"], 2)
        self.assertEqual(s["top"], 1)

    def test_pick(self):
        picked = core.pick(self.items)
        self.assertTrue(all(x["sel"] for x in picked))
        self.assertTrue(any(x["sel"] for x in self.items))


class InsightTest(unittest.TestCase):
    def test_insights_and_summary(self):
        items = core.score_all([work(), work(title="Survey of routing", year=2026,
                                             cited=0, issn="", venue="Drones",
                                             doi="10.1/b")], "truck drone routing")
        stats = core.summarize(items, 2)
        ins = core.build_insights(items, "truck drone routing", stats)
        self.assertTrue(ins)
        self.assertTrue(all({"tag", "title", "text", "evidence"} <= set(i) for i in ins))
        summary = core.executive_summary(items, "truck drone routing", stats, ins)
        self.assertIn("truck drone routing", summary)

    def test_report_sections(self):
        items = core.score_all([work()], "truck drone routing")
        stats = core.summarize(items, 1)
        md = core.build_report(items, "卡车无人机", stats, {
            "query_en": "truck drone routing",
            "tags": ["无人机"],
            "sources": ["OpenAlex", "Crossref"],
            "insights": core.build_insights(items, "卡车无人机", stats),
        })
        for section in ("## 一、概览", "## 四、推荐精读", "## 五、选题线索",
                        "## 七、逐篇评分明细", "## 九、方法与局限"):
            self.assertIn(section, md)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.items = core.score_all([work()], "truck drone routing")

    def test_bibtex(self):
        bib = core.to_bibtex(self.items)
        self.assertIn("@article{", bib)
        self.assertIn("title", bib)
        self.assertIn("doi", bib)

    def test_ris(self):
        ris = core.to_ris(self.items)
        self.assertIn("TY  - JOUR", ris)
        self.assertIn("ER  - ", ris)

    def test_csv(self):
        csv_text = core.to_csv(self.items)
        self.assertTrue(csv_text.startswith("rank,title,venue"))
        self.assertIn("A study of truck drone routing", csv_text)

    def test_json(self):
        data = json.loads(core.to_json(self.items))
        self.assertEqual(len(data), 1)
        self.assertIn("dims", data[0])

    def test_citation(self):
        text = core.citation_text(self.items[0])
        self.assertIn("2024", text)
        self.assertIn("https://doi.org/", text)


class DomainMatrixTest(unittest.TestCase):
    def test_domains(self):
        self.assertIn("物流配送", core._domains("truck drone delivery logistics"))
        self.assertIn("医疗健康", core._domains("hospital patient healthcare"))
        self.assertEqual(core._domains("something unknown"), ["其他"])

    def test_oa_url_propagates(self):
        rows = core.score_all([work(oa_url="https://example.org/a.pdf")], "truck drone")
        self.assertEqual(rows[0]["oa_url"], "https://example.org/a.pdf")

    def test_matrices(self):
        items = core.score_all([
            work(title="Truck drone delivery with machine learning", year=2024),
            work(title="Hospital scheduling with optimization", year=2025, doi="10.1/b"),
        ], "truck drone scheduling")
        dm = core.method_domain_matrix(items)
        self.assertTrue(any(r["count"] > 0 for r in dm))
        ym = core.method_year_matrix(items)
        self.assertTrue(any(r["year"] == 2025 for r in ym))
        self.assertTrue(all({"domain", "method", "count"} <= set(r) for r in dm))
        self.assertTrue(all({"year", "method", "count"} <= set(r) for r in ym))


if __name__ == "__main__":
    unittest.main()
