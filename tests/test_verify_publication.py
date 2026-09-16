import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_publication import verify


class VerifyPublicationTest(unittest.TestCase):
    receipt = {"editionDate": "2026-09-17", "title": "Expected title",
               "memoSha256": "123abc", "qualityPassed": True}

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
