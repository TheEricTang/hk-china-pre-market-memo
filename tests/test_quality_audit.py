import copy
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quality_audit import COVERAGE_AREAS, normalized_query, opened_urls, retrieved_queries, timestamp_bounds, completed_web_actions, retrieved_urls, validate_audit


class QualityAuditTest(unittest.TestCase):
    def setUp(self):
        self.start = datetime.fromisoformat("2026-09-14T16:00:00+08:00")
        self.cutoff = datetime.fromisoformat("2026-09-15T06:40:00+08:00")
        self.markdown = "\n".join(f"- Issuer {i}: Verified catalyst. [[Source](https://example.com/{i})]" for i in range(8))
        self.urls = {f"https://example.com/{i}" for i in range(8)}
        self.queries = {f"research {area}" for area in COVERAGE_AREAS}
        self.audit = {
            "items": [{"bullet": i + 1, "supported": True, "freshness": "new",
                       "event_time_hkt": "2026-09-15T05:00:00+08:00", "source_published_at": "2026-09-15T05:30:00+08:00",
                       "evidence": "The retrieved issuer notice confirms the amount, currency and event date.",
                       "checked_facts": ["amount, currency, date"], "source_urls": [f"https://example.com/{i}"],
                       "source_checks": [{"url": f"https://example.com/{i}", "published_at": "2026-09-15T05:30:00+08:00",
                                          "checked_facts": ["issuer announcement confirms amount and event"]}], "issues": []}
                      for i in range(8)],
            "coverage": [{"area": area, "queries": [f"research {area}"],
                          "finding": "The latest official notices were checked, with no other material events found.",
                          "source_urls": ["https://example.com/0"], "missing_material_stories": []} for area in COVERAGE_AREAS],
            "editorial_issues": [],
        }

    def check(self, audit=None, urls=None, opened=None):
        return validate_audit(audit or self.audit, self.markdown, self.urls if urls is None else urls, self.start, self.cutoff, self.queries, self.urls if opened is None else opened)

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
        self.audit["coverage"][0]["queries"] = [f" Research   {COVERAGE_AREAS[0].upper()}  "]
        self.assertEqual(self.check(), [])
        self.assertEqual(normalized_query("中國  政策\n 最新"), "中國 政策 最新")

    def test_one_broad_query_cannot_cover_every_area(self):
        self.queries = {"broad market news"}
        for check in self.audit["coverage"]:
            check["queries"] = [" Broad   MARKET news "]
        self.assertIn("Each coverage area must have a distinct executed research query", self.check())

    def test_overlapping_queries_allow_distinct_assignment(self):
        first, second = self.audit["coverage"][:2]
        self.queries.update({"shared first", "unique second"})
        first["queries"] = ["shared first", "unique second"]
        second["queries"] = ["shared first"]
        self.assertEqual(self.check(), [])

    def test_total_query_count_does_not_resolve_area_collision(self):
        first, second, third = self.audit["coverage"][:3]
        second["queries"] = first["queries"].copy()
        third["queries"].append(f"research {COVERAGE_AREAS[1]}")
        self.assertIn("Each coverage area must have a distinct executed research query", self.check())

    def test_indented_bullets_are_reviewed_like_rendered_bullets(self):
        self.markdown = "\n".join("  " + line + "  " for line in self.markdown.splitlines())
        self.assertEqual(self.check(), [])
        self.audit["items"].pop()
        self.assertIn("Audit must check every bullet exactly once", self.check())

    def test_indented_bullets_cannot_pass_with_empty_review(self):
        self.markdown = "\n".join("  " + line for line in self.markdown.splitlines())
        self.audit["items"] = []
        self.assertIn("Audit must check every bullet exactly once", self.check())

    def test_no_bullets_and_no_review_cannot_pass(self):
        self.markdown = "Morning Market Memo\nNo sourced news units."
        self.audit["items"] = []
        self.assertIn("Audit must check every bullet exactly once", self.check())

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
        for timestamp in ("", "2026-09-15T05:30:00"):
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

    def test_fact_batch_cannot_borrow_another_reviewers_source_open(self):
        queries = {query for check in self.audit["coverage"] for query in check["queries"]}
        by_item = {i: {"urls": self.urls, "opened": self.urls} for i in range(1, 9)}
        by_item[1] = {"urls": self.urls, "opened": set()}
        errors = validate_audit(self.audit, self.markdown, self.urls, self.start, self.cutoff,
                                queries, self.urls, item_provenance=by_item)
        self.assertTrue(any("Bullet 1: every public citation must be opened" in error for error in errors))

    def test_coverage_cannot_borrow_fact_batch_search_history(self):
        queries = {query for check in self.audit["coverage"] for query in check["queries"]}
        errors = validate_audit(self.audit, self.markdown, self.urls, self.start, self.cutoff,
                                queries, self.urls, coverage_provenance={"urls": self.urls, "queries": set()})
        self.assertTrue(any("claimed queries were not executed" in error for error in errors))

    def test_first_public_report_does_not_require_private_meeting_clock(self):
        item = self.audit["items"][0]
        item["event_time_basis"] = "first_public_report"
        item["event_time_hkt"] = item["source_checks"][0]["published_at"]
        item["evidence"] = "This is the verified first public report of the announcement, not the private signing clock."
        self.assertEqual(self.check(), [])
        item["event_time_hkt"] = "2026-09-15T05:29:00+08:00"
        self.assertTrue(any("first-public-report time must match" in error for error in self.check()))

    def test_prior_calendar_date_keeps_precision_and_can_support_recap(self):
        item = self.audit["items"][0]
        item.update(freshness="recap", event_time_basis="calendar_recap",
                    event_time_hkt="2026-09-01", source_published_at="2026-09-01")
        item["source_checks"][0]["published_at"] = "2026-09-01"
        self.assertEqual(self.check(), [])
        lower, upper = timestamp_bounds("2026-09-01")
        self.assertGreater((upper - lower).total_seconds(), 24 * 3600)

    def test_same_day_date_only_cannot_prove_pre_cutoff_eligibility(self):
        for value in ("2026-09-15", "2026-09-15@+08:00"):
            self.audit["items"][0]["source_checks"][0]["published_at"] = value
            self.assertTrue(any("checked source publication is later" in error for error in self.check()))

    def test_previous_dated_known_timezone_source_remains_recap_not_precisely_timed_new_news(self):
        item = self.audit["items"][0]
        item.update(event_time_basis="calendar_recap", freshness="recap",
                    event_time_hkt="2026-09-14@+08:00", source_published_at="2026-09-14@+08:00")
        item["source_checks"][0]["published_at"] = "2026-09-14@+08:00"
        self.assertEqual(self.check(), [])
        item.update(event_time_basis="event", freshness="new")
        self.assertTrue(any("no verified new event" in error for error in self.check()))

    def test_metadata_diagnostics_do_not_include_page_text_or_failed_actions(self):
        response = {"output": [
            {"type": "web_search_call", "status": "completed", "action": {"type": "open_page", "url": None, "text": "never persist"}},
            {"type": "web_search_call", "status": "failed", "action": {"type": "open_page", "url": "https://example.com/fail"}},
        ]}
        self.assertEqual(completed_web_actions(response), [{"type": "open_page", "url": None, "sources": []}])


if __name__ == "__main__":
    unittest.main()
