import copy
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quality_audit import COVERAGE_AREAS, normalized_query, opened_urls, retrieved_queries, retrieved_urls, validate_audit


class QualityAuditTest(unittest.TestCase):
    def setUp(self):
        self.start = datetime.fromisoformat("2026-09-14T16:00:00+08:00")
        self.cutoff = datetime.fromisoformat("2026-09-15T06:40:00+08:00")
        self.markdown = "\n".join(f"- Issuer {i}: Verified catalyst. [[Source](https://example.com/{i})]" for i in range(8))
        self.urls = {f"https://example.com/{i}" for i in range(8)}
        self.audit = {
            "items": [{"bullet": i + 1, "supported": True, "freshness": "new",
                       "event_time_hkt": "2026-09-15T05:00:00+08:00", "source_published_at": "2026-09-15T05:30:00+08:00",
                       "evidence": "The retrieved issuer notice confirms the amount, currency and event date.",
                       "checked_facts": ["amount, currency, date"], "source_urls": [f"https://example.com/{i}"],
                       "source_checks": [{"url": f"https://example.com/{i}", "published_at": "2026-09-15T05:30:00+08:00",
                                          "checked_facts": ["issuer announcement confirms amount and event"]}], "issues": []}
                      for i in range(8)],
            "coverage": [{"area": area, "queries": ["research query"],
                          "finding": "The latest official notices were checked, with no other material events found.",
                          "source_urls": ["https://example.com/0"], "missing_material_stories": []} for area in COVERAGE_AREAS],
            "editorial_issues": [],
        }

    def check(self, audit=None, urls=None, opened=None):
        return validate_audit(audit or self.audit, self.markdown, self.urls if urls is None else urls, self.start, self.cutoff, {"research query"}, self.urls if opened is None else opened)

    def test_complete_evidence_passes(self):
        self.assertEqual(self.check(), [])

    def test_every_bullet_is_reviewed_exactly_once(self):
        self.audit["items"][7]["bullet"] = 1
        self.assertIn("Audit must check every bullet exactly once", self.check())

    def test_assistant_citations_are_not_retrieval_provenance(self):
        response = {"output": [{"type": "message", "content": [{"annotations": [{"url": "https://example.com/0"}]}]}]}
        self.assertEqual(retrieved_urls(response), set())
        self.assertTrue(any("sources not retrieved" in err for err in self.check(urls=set())))

    def test_completed_search_and_open_actions_are_provenance(self):
        response = {"output": [
            {"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": [{"url": "https://example.com/1"}]}},
            {"type": "web_search_call", "status": "completed", "action": {"type": "open_page", "url": "https://example.com/2"}},
            {"type": "web_search_call", "status": "failed", "action": {"type": "open_page", "url": "https://example.com/3"}},
        ]}
        self.assertEqual(retrieved_urls(response), {"https://example.com/1", "https://example.com/2"})

    def test_future_source_and_event_fail(self):
        for field in ("event_time_hkt", "source_published_at"):
            with self.subTest(field=field):
                audit = copy.deepcopy(self.audit)
                audit["items"][0][field] = "2026-09-15T07:00:00+08:00"
                self.assertTrue(any("later than the cutoff" in err for err in self.check(audit)))

    def test_unknown_timezone_and_bad_time_fail(self):
        for stamp in ("", "unknown", "2026-09-15T05:00:00", "2026-09-15T29:00:00+08:00"):
            self.audit["items"][0]["event_time_hkt"] = stamp
            self.assertTrue(any("timestamps must be verified" in err for err in self.check()))

    def test_old_news_cannot_claim_new(self):
        self.audit["items"][0].update(event_time_hkt="2026-09-14T08:00:00+08:00", source_published_at="2026-09-14T08:01:00+08:00")
        self.assertTrue(any("no verified new event" in err for err in self.check()))

    def test_recap_cap_is_enforced(self):
        for item in self.audit["items"][:3]:
            item["freshness"] = "recap"
        self.assertIn("Recap exceeds 30% of the memo", self.check())

    def test_material_omissions_fail_even_if_all_existing_facts_pass(self):
        self.audit["coverage"][0]["missing_material_stories"] = ["Verified material announcement omitted"]
        self.assertTrue(any("missing material stories" in err for err in self.check()))

    def test_missing_coverage_and_empty_blanket_checks_fail(self):
        self.audit["coverage"].pop()
        self.audit["items"][0]["evidence"] = "Looks good"
        self.audit["coverage"][0]["queries"] = []
        errors = self.check()
        self.assertIn("Independent coverage checklist is incomplete or duplicated", errors)
        self.assertTrue(any("missing concrete evidence" in err for err in errors))
        self.assertTrue(any("missing researched evidence" in err for err in errors))

    def test_unchecked_public_link_fails(self):
        self.audit["items"][0]["source_urls"] = ["https://example.com/1"]
        self.assertTrue(any("every public citation" in err for err in self.check()))

    def test_claimed_query_requires_real_tool_history(self):
        self.audit["coverage"][0]["queries"] = ["a query the reviewer never ran"]
        self.assertTrue(any("claimed queries were not executed" in err for err in self.check()))

    def test_claimed_queries_allow_only_case_and_whitespace_variants(self):
        self.audit["coverage"][0]["queries"] = [" Research   QUERY  "]
        self.assertEqual(self.check(), [])
        self.assertEqual(normalized_query("中國  政策\n 最新"), "中國 政策 最新")

    def test_query_provenance_reads_both_provider_action_shapes(self):
        response = {"output": [
            {"type": "web_search_call", "status": "completed", "action": {"type": "search", "query": " First  Query ", "queries": ["Second Query"]}},
            {"type": "web_search_call", "status": "failed", "action": {"type": "search", "query": "Not executed"}},
            {"type": "message", "queries": ["Assistant claim"]},
        ]}
        self.assertEqual(retrieved_queries(response), {"first query", "second query"})

    def test_future_secondary_source_cannot_hide_behind_primary_timestamp(self):
        item = self.audit["items"][0]
        item["source_urls"].append("https://example.com/1")
        item["source_checks"].append({"url": "https://example.com/1", "published_at": "2026-09-15T07:00:00+08:00", "checked_facts": ["secondary figure"]})
        self.assertTrue(any("checked source publication is later" in err for err in self.check()))

    def test_source_checks_cover_exact_urls_once(self):
        for checks in ([], [self.audit["items"][1]["source_checks"][0]], self.audit["items"][0]["source_checks"] * 2):
            audit = copy.deepcopy(self.audit)
            audit["items"][0]["source_checks"] = checks
            self.assertTrue(any("source_checks must cover every source URL exactly once" in err for err in self.check(audit)))

    def test_source_checks_require_facts_and_timezone(self):
        for facts in ([], [""], ["   "]):
            audit = copy.deepcopy(self.audit)
            audit["items"][0]["source_checks"][0]["checked_facts"] = facts
            self.assertTrue(any("every checked source must identify supported facts" in err for err in self.check(audit)))
        for timestamp in ("", "2026-09-15", "2026-09-15T05:30:00"):
            audit = copy.deepcopy(self.audit)
            audit["items"][0]["source_checks"][0]["published_at"] = timestamp
            self.assertTrue(any("every source publication timestamp must be verified" in err for err in self.check(audit)))

    def test_each_checked_source_requires_actual_provenance(self):
        item = self.audit["items"][0]
        item["source_urls"].append("https://unretrieved.example/article")
        item["source_checks"].append({"url": "https://unretrieved.example/article", "published_at": "2026-09-15T05:00:00+08:00", "checked_facts": ["claimed detail"]})
        self.assertTrue(any("checked source was not retrieved" in err for err in self.check()))

    def test_search_discovery_without_opening_does_not_pass(self):
        errors = self.check(opened=set())
        self.assertTrue(any("every public citation must be opened" in err for err in errors))

    def test_only_completed_explicit_open_is_article_open_evidence(self):
        response = {"output": [
            {"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": [{"url": "https://example.com/search"}]}},
            {"type": "web_search_call", "status": "completed", "action": {"type": "find_in_page", "url": "https://example.com/find"}},
            {"type": "web_search_call", "status": "failed", "action": {"type": "open_page", "url": "https://example.com/failed"}},
            {"type": "web_search_call", "status": "completed", "action": {"type": "open_page", "url": "https://example.com/opened"}},
        ]}
        self.assertEqual(opened_urls(response), {"https://example.com/opened"})


if __name__ == "__main__":
    unittest.main()
