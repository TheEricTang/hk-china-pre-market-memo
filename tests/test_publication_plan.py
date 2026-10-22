import io
import json
import sys
import unittest
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_plan import (live_edition_is_current, publication_plan,
                              PublicationDeadlineError, final_preopen_receipt)


class PublicationPlanTest(unittest.TestCase):
    def plan(self, **overrides):
        inputs = dict(automatic=True, trading_day=True, generate_requested=True,
                      canonical_current=False, live_current=False, hkt_time=time(6, 35))
        inputs.update(overrides)
        return publication_plan(**inputs)

    def test_automatic_dispatch_generates_missing_edition(self):
        self.assertEqual(self.plan(), (True, True))

    def test_automatic_retries_do_not_repeat_paid_generation(self):
        self.assertEqual(self.plan(canonical_current=True, live_current=True), (False, False))

    def test_committed_memo_with_stale_website_retries_only_deployment(self):
        self.assertEqual(self.plan(canonical_current=True), (False, True))

    def test_automatic_dispatch_obeys_trading_calendar(self):
        self.assertEqual(self.plan(trading_day=False), (False, False))

    def test_manual_regeneration_keeps_force_semantics(self):
        self.assertEqual(self.plan(automatic=False, trading_day=False,
                                   canonical_current=True, live_current=True), (True, True))

    def test_manual_deployment_does_not_generate(self):
        self.assertEqual(self.plan(automatic=False, generate_requested=False), (False, True))

    def test_dispatch_generate_false_never_generates(self):
        self.assertEqual(self.plan(generate_requested=False), (False, True))

    def test_0634_skips_automatic_generation_and_publication(self):
        self.assertEqual(self.plan(hkt_time=time(6, 34, 59)), (False, False))
        self.assertEqual(self.plan(hkt_time=time(6, 34), canonical_current=True), (False, False))

    def test_0635_allows_new_generation(self):
        self.assertEqual(self.plan(hkt_time=time(6, 35)), (True, True))

    def test_0730_allows_last_generation_start(self):
        self.assertEqual(self.plan(hkt_time=time(7, 30, 59)), (True, True))

    def test_0731_missing_edition_fails_instead_of_false_green(self):
        with self.assertRaisesRegex(PublicationDeadlineError, "07:30 HKT"):
            self.plan(hkt_time=time(7, 31))

    def test_0740_approved_edition_can_redeploy_without_regeneration(self):
        self.assertEqual(self.plan(hkt_time=time(7, 40), canonical_current=True), (False, True))

    def test_0800_stale_site_requires_manual_recovery(self):
        with self.assertRaisesRegex(PublicationDeadlineError, "08:00 HKT"):
            self.plan(hkt_time=time(8, 0), canonical_current=True)

    def test_already_published_final_edition_stays_noop_after_deadline(self):
        self.assertEqual(self.plan(hkt_time=time(10, 0), canonical_current=True,
                                   live_current=True), (False, False))

    def test_manual_forced_and_dry_run_generations_exempt_from_window(self):
        self.assertEqual(self.plan(automatic=False, hkt_time=time(5, 0)), (True, True))
        self.assertEqual(self.plan(automatic=False, hkt_time=time(10, 0)), (True, True))


class FinalReceiptTest(unittest.TestCase):
    now = datetime(2026, 9, 17, 7, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))

    def receipt(self, cutoff):
        return {"qualityPassed": True, "editionMode": "preopen", "editionDate": "2026-09-17",
                "researchCutoff": cutoff}

    def test_early_provisional_receipt_does_not_suppress_final(self):
        self.assertFalse(final_preopen_receipt(self.receipt("2026-09-17T06:34:59+08:00"), self.now))

    def test_0635_receipt_qualifies_in_hkt_or_equivalent_utc(self):
        self.assertTrue(final_preopen_receipt(self.receipt("2026-09-17T06:35:00+08:00"), self.now))
        self.assertTrue(final_preopen_receipt(self.receipt("2026-09-16T22:35:00Z"), self.now))

    def test_wrong_date_naive_or_future_cutoffs_rejected(self):
        for cutoff in ("2026-09-16T06:40:00+08:00", "2026-09-17T06:40:00",
                       "2026-09-17T07:01:00+08:00", None, "invalid"):
            with self.subTest(cutoff=cutoff):
                self.assertFalse(final_preopen_receipt(self.receipt(cutoff), self.now))


class LiveEditionTest(unittest.TestCase):
    title = "Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open"

    @patch("publication_plan.urlopen")
    def test_checks_primary_heading_with_bounded_uncached_request(self, request):
        request.return_value = io.BytesIO(f"<h1>{self.title}</h1>".encode())
        self.assertTrue(live_edition_is_current(self.title))
        args, kwargs = request.call_args
        self.assertEqual(kwargs["timeout"], 10)
        self.assertIn("freshness=", args[0].full_url)
        self.assertEqual(args[0].get_header("Cache-control"), "no-cache")

    @patch("publication_plan.urlopen")
    def test_archive_or_script_date_does_not_prove_current_edition(self, request):
        request.return_value = io.BytesIO(
            f'<h1>Previous edition</h1><a>{self.title}</a>'.encode())
        self.assertFalse(live_edition_is_current(self.title))

    @patch("publication_plan.urlopen", side_effect=URLError("unavailable"))
    def test_fetch_failure_requests_safe_redeployment(self, request):
        self.assertFalse(live_edition_is_current(self.title))

    @patch("publication_plan.urlopen", side_effect=TimeoutError)
    def test_timeout_requests_safe_redeployment(self, request):
        self.assertFalse(live_edition_is_current(self.title))

    @patch("publication_plan.urlopen")
    def test_current_page_requires_matching_approved_receipt(self, request):
        request.side_effect = [
            io.BytesIO(f'<meta name="memo-sha256" content="abc"><h1>{self.title}</h1>'.encode()),
            io.BytesIO(json.dumps({"title": self.title, "memoSha256": "abc",
                                   "qualityPassed": True}).encode()),
        ]
        self.assertTrue(live_edition_is_current(self.title, "abc"))
        self.assertIn("status.json?freshness=", request.call_args.args[0].full_url)

    @patch("publication_plan.urlopen")
    def test_stale_html_with_fresh_receipt_is_rejected(self, request):
        request.side_effect = [
            io.BytesIO(f'<meta name="memo-sha256" content="old"><h1>{self.title}</h1>'.encode()),
            io.BytesIO(json.dumps({"title": self.title, "memoSha256": "abc",
                                   "qualityPassed": True}).encode()),
        ]
        self.assertFalse(live_edition_is_current(self.title, "abc"))

    @patch("publication_plan.urlopen")
    def test_false_quality_flag_is_rejected(self, request):
        request.side_effect = [
            io.BytesIO(f'<meta name="memo-sha256" content="abc"><h1>{self.title}</h1>'.encode()),
            io.BytesIO(json.dumps({"title": self.title, "memoSha256": "abc",
                                   "qualityPassed": False}).encode()),
        ]
        self.assertFalse(live_edition_is_current(self.title, "abc"))

    @patch("publication_plan.urlopen")
    def test_oversized_page_is_rejected(self, request):
        request.return_value = io.BytesIO(b"x" * 1_000_001)
        self.assertFalse(live_edition_is_current(self.title))


if __name__ == "__main__":
    unittest.main()
