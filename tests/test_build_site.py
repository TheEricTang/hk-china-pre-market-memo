import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_site import page


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


if __name__ == "__main__":
    unittest.main()
