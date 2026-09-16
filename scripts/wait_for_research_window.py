"""Start a runner early, but never research before the same day's 06:35 HKT window."""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from trading_calendar import HKEX_HOLIDAYS, is_hk_trading_day

HKT = ZoneInfo("Asia/Hong_Kong")
EARLY_SCHEDULE = "35 17-20 * * *"
MAX_WAIT_SECONDS = 5 * 60 * 60


def wait_for_research_window(*, clock=None, sleep=None, monotonic=None):
    clock = clock or (lambda: datetime.now(HKT))
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    started = clock().astimezone(HKT)
    if started.year not in HKEX_HOLIDAYS:
        raise RuntimeError("HK trading calendar needs renewal before an early scheduled run")
    if not is_hk_trading_day(started.date()):
        print(f"No early wait: {started.date()} is not an HK trading day.", flush=True)
        return "non_trading_day"
    target = started.replace(hour=6, minute=35, second=0, microsecond=0)
    if started >= target:
        print(f"Runner started at {started.isoformat()}; research window is already open.", flush=True)
        return "ready"
    if (target - started).total_seconds() > MAX_WAIT_SECONDS:
        raise RuntimeError("Research window is more than five hours away; refusing an unbounded wait")
    print(f"Early runner started at {started.isoformat()}; waiting until {target.isoformat()}. "
          "Research has not started.", flush=True)
    deadline = monotonic() + MAX_WAIT_SECONDS
    while True:
        current = clock().astimezone(HKT)
        if current.date() != started.date():
            raise RuntimeError("Early runner crossed its intended HK date; refusing to roll into another edition")
        if current >= target:
            print(f"Research window reached at {current.isoformat()}; subsequent generation records its own actual cutoff.", flush=True)
            return "ready"
        remaining_budget = deadline - monotonic()
        if remaining_budget <= 0:
            raise TimeoutError("Early runner exhausted its five-hour wait budget")
        # Short clock-driven waits tolerate delayed starts and never backdate research.
        sleep(min(60, (target - current).total_seconds(), remaining_budget))


def main():
    if os.getenv("GITHUB_EVENT_NAME") != "schedule" or os.getenv("MEMO_SCHEDULE") != EARLY_SCHEDULE:
        print("This is not an early scheduled run; no wait is required.")
        return
    wait_for_research_window()


if __name__ == "__main__":
    main()
