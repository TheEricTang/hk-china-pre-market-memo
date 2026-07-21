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


if __name__ == "__main__":
    unittest.main()

