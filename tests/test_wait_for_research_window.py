import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wait_for_research_window as waiting


class FakeClock:
    def __init__(self, stamp, frozen=False):
        self.current = datetime.fromisoformat(stamp)
        self.elapsed = 0
        self.sleeps = []
        self.frozen = frozen

    def now(self):
        return self.current

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.elapsed += seconds
        if not self.frozen:
            self.current += timedelta(seconds=seconds)


class ResearchWindowWaitTest(unittest.TestCase):
    def wait(self, fake):
        with redirect_stdout(io.StringIO()):
            return waiting.wait_for_research_window(clock=fake.now, sleep=fake.sleep,
                                                    monotonic=fake.monotonic)

    def test_earliest_runner_waits_five_hours_without_early_release(self):
        fake = FakeClock("2026-09-17T01:35:00+08:00")
        self.assertEqual(self.wait(fake), "ready")
        self.assertEqual(fake.now().isoformat(), "2026-09-17T06:35:00+08:00")
        self.assertEqual(fake.elapsed, 5 * 3600)
        self.assertEqual(len(fake.sleeps), 300)
        self.assertLessEqual(max(fake.sleeps), 60)

    def test_two_hour_scheduler_delay_still_waits_until_actual_window(self):
        fake = FakeClock("2026-09-17T03:35:00+08:00")
        self.assertEqual(self.wait(fake), "ready")
        self.assertEqual(fake.now().isoformat(), "2026-09-17T06:35:00+08:00")
        self.assertEqual(fake.elapsed, 3 * 3600)

    def test_partial_minute_wait_and_utc_hkt_date_conversion(self):
        fake = FakeClock("2026-09-16T22:34:30+00:00")
        self.assertEqual(self.wait(fake), "ready")
        self.assertEqual(fake.sleeps, [30])
        self.assertEqual(fake.now().astimezone(waiting.HKT).isoformat(), "2026-09-17T06:35:00+08:00")

    def test_already_open_or_late_runner_does_not_wait_or_backdate(self):
        for stamp in ("2026-09-17T06:35:00+08:00", "2026-09-17T07:40:00+08:00"):
            fake = FakeClock(stamp)
            self.assertEqual(self.wait(fake), "ready")
            self.assertEqual(fake.sleeps, [])
            self.assertEqual(fake.now().isoformat(), stamp)

    def test_weekends_and_holidays_do_not_hold_a_runner(self):
        for stamp in ("2026-09-19T01:35:00+08:00", "2026-10-01T01:35:00+08:00"):
            fake = FakeClock(stamp)
            self.assertEqual(self.wait(fake), "non_trading_day")
            self.assertEqual(fake.sleeps, [])

    def test_too_early_or_unknown_calendar_does_not_create_unbounded_wait(self):
        for stamp in ("2026-09-17T01:34:59+08:00", "2028-01-03T01:35:00+08:00"):
            fake = FakeClock(stamp)
            with self.assertRaises(RuntimeError):
                self.wait(fake)
            self.assertEqual(fake.sleeps, [])

    def test_frozen_wall_clock_cannot_exceed_monotonic_five_hour_budget(self):
        fake = FakeClock("2026-09-17T06:34:00+08:00", frozen=True)
        with self.assertRaisesRegex(TimeoutError, "five-hour wait budget"):
            self.wait(fake)
        self.assertEqual(fake.elapsed, 5 * 3600)
        self.assertLessEqual(max(fake.sleeps), 60)

    def test_clock_jump_into_next_date_never_rolls_into_another_edition(self):
        values = iter([datetime.fromisoformat("2026-09-17T03:35:00+08:00"),
                       datetime.fromisoformat("2026-09-18T06:35:00+08:00")])
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "intended HK date"):
            waiting.wait_for_research_window(clock=lambda: next(values), sleep=lambda _: None,
                                            monotonic=lambda: 0)

    def test_manual_and_normal_scheduled_runs_never_enter_wait(self):
        for event, schedule in (("workflow_dispatch", waiting.EARLY_SCHEDULE),
                                ("schedule", "40 22 * * *"), ("push", "")):
            with patch.dict("os.environ", {"GITHUB_EVENT_NAME": event, "MEMO_SCHEDULE": schedule}), \
                    patch.object(waiting, "wait_for_research_window") as wait, redirect_stdout(io.StringIO()):
                waiting.main()
                wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
