import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from memo_freshness import is_current_memo


class MemoFreshnessTest(unittest.TestCase):
    def test_accepts_markdown_trailing_spaces_on_title(self):
        expected = "Morning Market Memo | 23 Jul 2026 | HK/China Pre-Open"
        with tempfile.TemporaryDirectory() as directory:
            memo = Path(directory) / "memo-2026-07-23.md"
            memo.write_text(f"{expected}  \nBody\n", encoding="utf-8")
            self.assertTrue(is_current_memo(memo, expected))

    def test_rejects_a_different_edition(self):
        with tempfile.TemporaryDirectory() as directory:
            memo = Path(directory) / "memo-2026-07-23.md"
            memo.write_text(
                "Morning Market Memo | 22 Jul 2026 | HK/China Pre-Open\n",
                encoding="utf-8",
            )
            self.assertFalse(
                is_current_memo(
                    memo,
                    "Morning Market Memo | 23 Jul 2026 | HK/China Pre-Open",
                )
            )

    def test_rejects_a_missing_memo(self):
        self.assertFalse(
            is_current_memo(
                Path("does-not-exist.md"),
                "Morning Market Memo | 23 Jul 2026 | HK/China Pre-Open",
            )
        )


if __name__ == "__main__":
    unittest.main()
