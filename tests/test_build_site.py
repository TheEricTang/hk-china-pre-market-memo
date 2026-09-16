import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_site import page, main
from publication_status import memo_hash


class BuildSiteCountdownTest(unittest.TestCase):
    def test_page_contains_configurable_accessible_countdown(self):
        output = page(
            "Morning Market Memo | 21 Jul 2026 | HK/China Pre-Open",
            "(covers 20 Jul 16:00 HKT close → 21 Jul 06:39 HKT research cutoff)",
            ["Item: News. [[Source](https://example.com)]"],
            [Path("memos/memo-2026-07-21.md")],
        )
        self.assertIn('class="refresh-status"', output)
        self.assertIn('aria-live="polite"', output)
        self.assertIn('refreshHour: 6', output)
        self.assertIn('refreshMinute: 40', output)
        self.assertIn('2026-10-01', output)
        self.assertIn("Today's refresh is in progress", output)
        self.assertIn('Next refresh in', output)

    def test_build_publishes_hash_bound_receipt_without_private_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memos").mkdir()
            memo = root / "memos" / "memo-2026-09-17.md"
            title = "Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open"
            memo.write_text(f"{title}\nResearch window\n- Story: Fact.\n")
            digest = memo_hash(memo)
            memo.with_suffix(".status.json").write_text(json.dumps({
                "schemaVersion": 1, "editionDate": "2026-09-17", "editionMode": "preopen",
                "memoSha256": digest, "qualityPassed": True,
                "researchCutoff": "2026-09-17T06:35:00+08:00",
                "generatedAt": "2026-09-17T06:44:00+08:00", "privateEvidence": "never public",
            }))
            with patch("build_site.ROOT", root), patch("build_site.DOCS", root / "docs"), \
                    patch("build_site.ARCHIVE", root / "docs" / "archive"):
                main()
            status = json.loads((root / "docs" / "status.json").read_text())
            self.assertTrue(status["qualityPassed"])
            self.assertEqual(status["memoSha256"], digest)
            self.assertNotIn("privateEvidence", status)
            self.assertIn(f'name="memo-sha256" content="{digest}"',
                          (root / "docs" / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
