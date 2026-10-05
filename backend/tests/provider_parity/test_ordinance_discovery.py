import unittest
from backend.app.modules.law.reference.ordinance_discovery import discover_ordinances, public_record


class OrdinanceDiscoveryTests(unittest.TestCase):
    def test_echoed_credential_removed_from_official_detail_link(self):
        row = {"link": "https://www.law.go.kr/DRF/lawService.do?OC=secret&target=ordin&MST=123"}
        cleaned = public_record(row)
        self.assertNotIn("secret", str(cleaned))
        self.assertNotIn("OC=", str(cleaned))
        self.assertIn("MST=123", cleaned["link"])
        self.assertIn("secret", row["link"])
    def test_nationwide_names_and_dates_preserved_without_default_city(self):
        calls = []
        def fetch(params):
            calls.append(params)
            return {"OrdinSearch": {"totalCnt": 2, "law": [
                {"자치법규명": "부산광역시 도시계획 조례", "자치법규일련번호": "1", "시행일자": "20260801", "지자체명": "부산광역시"},
                {"자치법규명": "Future", "자치법규일련번호": "2", "시행일자": "20270101"}]}}
        result = discover_ordinances("부산광역시", "2026-09-13", "not-a-real-key", fetch_json=fetch)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["agency"], "부산광역시")
        self.assertEqual({call["nw"] for call in calls}, {1, 2})
        self.assertFalse(result["truncated"])
        self.assertFalse(result["coverage_complete"])

    def test_failure_does_not_expose_api_credential(self):
        def fail(params):
            raise ValueError("url?OC=secret")
        result = discover_ordinances("test", "2026-09-13", "secret", fetch_json=fail)
        self.assertEqual(result["status"], "external_failure")
        self.assertNotIn("secret", str(result))

    def test_exhausted_pagination_is_explicit(self):
        result = discover_ordinances("test", "2026-09-13", "key", max_pages=1,
            fetch_json=lambda params: {"OrdinSearch": {"totalCnt": 101, "law": [{"시행일자": "20260101", "자치법규일련번호": "1"}]}})
        self.assertTrue(result["truncated"])
