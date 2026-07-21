import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_memo import validate


class MemoValidationTest(unittest.TestCase):
    def test_accepts_sourced_memo_with_real_cutoff(self):
        bullets = "\n".join(
            f"- Item {i}: Confirmed market news. [[Source](https://example.com/{i})]" for i in range(8)
        )
        memo = "Morning Market Memo | 21 Jul 2026 | HK/China Pre-Open\n(covers 20 Jul 16:00 HKT close → 21 Jul 06:22 HKT research cutoff)\n" + bullets
        self.assertEqual(validate(memo, "memo-2026-07-21.md"), [])

    def test_rejects_unsourced_bullet(self):
        memo = "Morning Market Memo | 21 Jul 2026 | HK/China Pre-Open\n(covers 20 Jul 16:00 HKT close → 21 Jul 06:22 HKT research cutoff)\n" + "\n".join("- Item: Text" for _ in range(8))
        self.assertIn("Bullet 1 has no specific source link", validate(memo, "memo-2026-07-21.md"))

    def test_rejects_post_open_cutoff(self):
        bullets = "\n".join(
            f"- Item {i}: Confirmed news. [[Source](https://example.com/{i})]" for i in range(8)
        )
        memo = "Morning Market Memo | 21 Jul 2026 | HK/China Pre-Open\n(covers 20 Jul 16:00 HKT close → 21 Jul 12:15 HKT research cutoff)\n" + bullets
        self.assertIn("Research cutoff must be before the 09:30 HKT market open", validate(memo, "memo-2026-07-21.md"))

    def test_accepts_truthfully_labelled_intraday_preview(self):
        bullets = "\n".join(
            f"- Item {i}: Confirmed news. [[Source](https://example.com/{i})]" for i in range(8)
        )
        memo = "Intraday Market Memo | 21 Jul 2026 | HK/China Update\n(covers 20 Jul 16:00 HKT close → 21 Jul 13:30 HKT research cutoff)\n" + bullets
        self.assertEqual(validate(memo, "memo-2026-07-21.md", edition_mode="intraday"), [])


if __name__ == "__main__":
    unittest.main()
