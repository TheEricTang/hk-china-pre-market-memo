import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from trading_calendar import is_hk_trading_day


class TradingCalendarTest(unittest.TestCase):
    def test_normal_weekday_is_trading_day(self):
        self.assertTrue(is_hk_trading_day(date(2026, 7, 21)))

    def test_weekend_is_not_trading_day(self):
        self.assertFalse(is_hk_trading_day(date(2026, 7, 25)))

    def test_hkex_holiday_is_not_trading_day(self):
        self.assertFalse(is_hk_trading_day(date(2026, 10, 1)))


if __name__ == "__main__":
    unittest.main()
