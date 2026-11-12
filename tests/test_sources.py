import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import sources  # noqa: E402


class NormalizeCrossrefTest(unittest.TestCase):
    def test_normalize(self):
        raw = {
            "DOI": "10.1016/J.TRC.2025.100001",
            "title": ["Truck-drone routing"],
            "container-title": ["Transportation Research Part C"],
            "ISSN": ["0968-090X"],
            "issued": {"date-parts": [[2025, 3, 1]]},
            "is-referenced-by-count": 12,
            "author": [{"given": "Alice", "family": "Zhang"}],
            "abstract": "<jats:p>We study <jats:italic>routing</jats:italic>.</jats:p>",
            "URL": "https://example.org/a",
            "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
        }
        row = sources.normalize_crossref(raw)
        self.assertEqual(row["doi"], "10.1016/j.trc.2025.100001")
        self.assertEqual(row["year"], 2025)
        self.assertTrue(row["is_top"])
        self.assertTrue(row["is_oa"])
        self.assertEqual(row["authors"], ["Alice Zhang"])
        self.assertNotIn("<jats", row["abstract"])
        self.assertEqual(row["source_tags"], ["crossref"])


class MergeTest(unittest.TestCase):
    def _row(self, title, doi="", cited=0, tags=("openalex",), abstract=""):
        return {"title": title, "doi": doi, "cited": cited, "abstract": abstract,
                "source_tags": list(tags), "venue": "V", "issn": "", "is_top": False,
                "is_oa": False, "year": 2024, "url": ""}

    def test_doi_dedupe(self):
        a = self._row("Paper A", doi="10.1/x", cited=1, abstract="short")
        b = self._row("Paper A copy", doi="10.1/X", cited=9, tags=("crossref",),
                      abstract="a much longer abstract")
        merged = sources.merge_items([[a], [b]])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["cited"], 9)
        self.assertEqual(set(merged[0]["source_tags"]), {"openalex", "crossref"})
        self.assertEqual(merged[0]["abstract"], "a much longer abstract")

    def test_title_dedupe(self):
        a = self._row("Truck–Drone Routing!")
        b = self._row("truck drone routing", tags=("crossref",))
        merged = sources.merge_items([[a], [b]])
        self.assertEqual(len(merged), 1)

    def test_size_limit(self):
        rows = [self._row(f"Paper {i}") for i in range(10)]
        self.assertEqual(len(sources.merge_items([rows], size=3)), 3)


class SearchAllTest(unittest.TestCase):
    def test_partial_failure(self):
        ok = {"items": [{"title": "A", "doi": "10.1/a", "abstract": "",
                         "cited": 0, "source_tags": ["openalex"], "venue": "",
                         "issn": "", "is_top": False, "is_oa": False,
                         "year": 2024, "url": ""}],
              "total": 1, "raw_total": 1, "elapsed_ms": 1, "url": "u", "error": ""}
        fail = {"items": [], "total": 0, "raw_total": 0, "elapsed_ms": 0,
                "url": "", "error": "HTTP 500"}
        with mock.patch.object(sources, "search_openalex", return_value=ok), \
                mock.patch.object(sources, "search_crossref", return_value=fail):
            res = sources.search_all("q", sources=("openalex", "crossref"), size=10)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["errors"], {"crossref": "HTTP 500"})
        self.assertEqual(res["hit"], 1)

    def test_crossref_post_filter(self):
        payload = {
            "message": {
                "total-results": 2,
                "items": [
                    {"DOI": "10.1/top", "title": ["Top"], "ISSN": ["0968-090X"],
                     "issued": {"date-parts": [[2024]]}, "is-referenced-by-count": 10},
                    {"DOI": "10.1/other", "title": ["Other"], "ISSN": ["1234-5678"],
                     "issued": {"date-parts": [[2024]]}, "is-referenced-by-count": 10},
                ],
            },
        }
        with mock.patch.object(core, "_http_json", return_value=(payload, 5)):
            res = sources.search_crossref("q", top_only=True)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["items"][0]["doi"], "10.1/top")
        self.assertEqual(res["total"], 1)


if __name__ == "__main__":
    unittest.main()
