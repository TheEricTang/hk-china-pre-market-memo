import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_status import memo_hash, publication_status


class PublicationStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.memo = Path(self.tmp.name) / "memo-2026-09-17.md"
        self.memo.write_text("Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open\nBody\n")
        self.receipt = {
            "schemaVersion": 1, "editionDate": "2026-09-17", "editionMode": "preopen",
            "memoSha256": memo_hash(self.memo), "qualityPassed": True,
            "researchCutoff": "2026-09-17T06:35:00+08:00",
            "generatedAt": "2026-09-17T06:44:00+08:00",
            "privateEvidence": "must never appear on public site",
        }

    def save_receipt(self):
        self.memo.with_suffix(".status.json").write_text(json.dumps(self.receipt))

    def test_only_safe_content_bound_metadata_is_published(self):
        self.save_receipt()
        status = publication_status(self.memo)
        self.assertTrue(status["qualityPassed"])
        self.assertEqual(status["generatedAt"], self.receipt["generatedAt"])
        self.assertNotIn("privateEvidence", status)

    def test_modified_memo_cannot_reuse_quality_pass(self):
        self.save_receipt()
        self.memo.write_text(self.memo.read_text() + "Unreviewed story\n")
        self.assertFalse(publication_status(self.memo)["qualityPassed"])

    def test_legacy_memo_does_not_get_fabricated_quality_pass(self):
        status = publication_status(self.memo)
        self.assertFalse(status["qualityPassed"])
        self.assertIsNone(status["generatedAt"])

    def test_receipt_for_other_edition_is_rejected(self):
        self.receipt["editionMode"] = "intraday"
        self.save_receipt()
        self.assertFalse(publication_status(self.memo)["qualityPassed"])


if __name__ == "__main__":
    unittest.main()
