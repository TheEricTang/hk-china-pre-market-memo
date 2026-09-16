import sys
import json
import tempfile
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_site import page, main
from publication_status import memo_hash


class BuildSiteFreshnessTest(unittest.TestCase):
    def render_status(self, output, now):
        script = re.search(r"<script>([\s\S]*?)</script>", output).group(1)
        setup = ("const output = {textContent:''}; const document={querySelector:()=>output};"
                 "const setInterval=()=>{}; Date.now=()=>Date.parse(" + json.dumps(now) + ");")
        result = subprocess.run(["node", "-e", setup + script + "console.log(output.textContent);"],
                                capture_output=True, text=True, check=True, timeout=10)
        return result.stdout.strip()

    def legacy_page(self, **kwargs):
        return page("Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open", "Research window",
                    ["Item: News. [[Source](https://example.com)]"],
                    [Path("memos/memo-2026-09-16.md")], **kwargs)

    def test_page_is_accessible_without_claiming_active_run_or_guaranteed_countdown(self):
        output = page(
            "Morning Market Memo | 21 Jul 2026 | HK/China Pre-Open",
            "(covers 20 Jul 16:00 HKT close → 21 Jul 06:39 HKT research cutoff)",
            ["Item: News. [[Source](https://example.com)]"],
            [Path("memos/memo-2026-07-21.md")],
        )
        self.assertIn('class="refresh-status"', output)
        self.assertIn('aria-live="polite"', output)
        self.assertIn('2026-10-01', output)
        self.assertNotIn("refresh is in progress", output)
        self.assertNotIn('Next refresh in', output)
        self.assertNotIn('Latest verified edition', output)

    def test_stale_before_target_says_not_yet_available(self):
        status = self.render_status(self.legacy_page(), "2026-09-16T23:29:59Z")
        self.assertIn("Today's edition is not yet available", status)
        self.assertIn("Showing 16 Sept 2026", status)
        self.assertIn("Target 07:30 HKT", status)
        self.assertIn("research begins 06:35 HKT", status)

    def test_stale_at_target_and_hours_later_explicitly_says_delayed(self):
        for now in ("2026-09-16T23:30:00Z", "2026-09-17T03:00:00Z"):
            status = self.render_status(self.legacy_page(), now)
            self.assertIn("Today's edition is delayed — showing 16 Sept 2026", status)
            self.assertNotIn("progress", status)

    def test_current_reviewed_edition_shows_its_date_and_receipt_cutoff(self):
        output = page("Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open", "Research window",
                      [], [Path("memos/memo-2026-09-17.md")], receipt={
                          "qualityPassed": True, "researchCutoff": "2026-09-17T06:35:00+08:00",
                          "generatedAt": "2026-09-17T07:12:00+08:00"})
        status = self.render_status(output, "2026-09-16T23:40:00Z")
        self.assertEqual(status, "Today's edition · 17 Sept 2026 · Research cutoff 06:35 HKT")
        self.assertIn("Generated 17 Sep 2026 07:12 HKT", output)

    def test_legacy_current_edition_does_not_claim_quality_review(self):
        output = self.legacy_page()
        status = self.render_status(output, "2026-09-16T03:00:00Z")
        self.assertIn("Review receipt unavailable", status)
        self.assertNotIn("Reviewed pre-open edition", output)

    def test_weekend_shows_next_target_instead_of_claiming_delay(self):
        status = self.render_status(self.legacy_page(), "2026-09-19T03:00:00Z")
        self.assertIn("Next publication target: 21 Sept 2026, 07:30 HKT", status)
        self.assertNotIn("delayed", status)

    def test_archive_uses_own_date_even_when_newer_edition_exists(self):
        output = page("Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open", "Research window", [],
                      [Path("memos/memo-2026-09-16.md"), Path("memos/memo-2026-09-17.md")],
                      prefix="../", memo_date="2026-09-16")
        status = self.render_status(output, "2026-09-16T23:40:00Z")
        self.assertEqual(status, "Archive edition · 16 Sept 2026 · Review receipt unavailable")
        self.assertIn('<div class="eyebrow">Archive · 16 Sep 2026</div>', output)
        self.assertNotIn("Latest verified edition", output)

    def test_unknown_calendar_year_does_not_invent_publication_schedule(self):
        status = self.render_status(self.legacy_page(), "2028-01-03T00:00:00Z")
        self.assertIn("Publication calendar needs updating", status)

    def test_build_publishes_hash_bound_receipt_without_private_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memos").mkdir()
            memo = root / "memos" / "memo-2026-09-17.md"
            title = "Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open"
            memo.write_text(f"{title}\nResearch window\n- Story: Fact.\n")
            older = root / "memos" / "memo-2026-09-16.md"
            older.write_text("Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open\nResearch window\n- Old story.\n")
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
            archive = (root / "docs" / "archive" / "memo-2026-09-16.html").read_text()
            self.assertIn('"editionDate":"2026-09-16"', archive)
            self.assertIn("Archive · 16 Sep 2026", archive)


if __name__ == "__main__":
    unittest.main()
