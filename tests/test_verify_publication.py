import sys
from datetime import datetime
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_publication import verify, delivery_result


class VerifyPublicationTest(unittest.TestCase):
    receipt = {"editionDate": "2026-09-17", "title": "Expected title",
               "memoSha256": "123abc", "qualityPassed": True}

    def test_verified_but_late_automatic_publication_is_not_a_success(self):
        result = delivery_result(True, datetime.fromisoformat("2026-09-17T07:31:00+08:00"), True)
        self.assertTrue(result["confirmed"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["onTime"])

    def test_on_time_confirmation_passes_but_stale_page_never_does(self):
        now = datetime.fromisoformat("2026-09-17T07:29:00+08:00")
        self.assertTrue(delivery_result(True, now, True)["accepted"])
        self.assertFalse(delivery_result(False, now, True)["accepted"])

    def test_manual_intraday_recovery_is_allowed_and_not_labeled_on_time(self):
        result = delivery_result(True, datetime.fromisoformat("2026-09-17T14:00:00+08:00"), False)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["onTime"])

    @patch("verify_publication.time.sleep")
    @patch("verify_publication.live_edition_is_current", side_effect=[False, True])
    def test_cdn_propagation_retries_then_confirms_exact_edition(self, live, sleep):
        self.assertTrue(verify(self.receipt, "2026-09-17"))
        self.assertEqual(live.call_count, 2)
        live.assert_called_with("Expected title", "123abc")
        sleep.assert_called_once_with(10)

    @patch("verify_publication.time.sleep")
    @patch("verify_publication.live_edition_is_current", return_value=False)
    def test_stale_deployment_fails_after_bounded_attempts(self, live, sleep):
        self.assertFalse(verify(self.receipt, "2026-09-17"))
        self.assertEqual(live.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    @patch("verify_publication.live_edition_is_current")
    def test_yesterdays_local_artifact_cannot_verify_as_today(self, live):
        self.assertFalse(verify(self.receipt, "2026-09-18"))
        live.assert_not_called()

    @patch("verify_publication.live_edition_is_current")
    def test_unreviewed_memo_cannot_verify(self, live):
        self.assertFalse(verify(dict(self.receipt, qualityPassed=False), "2026-09-17"))
        live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
