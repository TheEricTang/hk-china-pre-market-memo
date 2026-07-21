import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


HKEX_HOLIDAYS = {
    2026: {
        "2026-01-01", "2026-02-17", "2026-02-18", "2026-02-19",
        "2026-04-03", "2026-04-06", "2026-04-07", "2026-05-01",
        "2026-05-25", "2026-06-19", "2026-07-01", "2026-10-01",
        "2026-10-19", "2026-12-25",
    },
    2027: {
        "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-26",
        "2027-03-29", "2027-04-05", "2027-05-13", "2027-06-09",
        "2027-07-01", "2027-09-16", "2027-10-01", "2027-10-08",
        "2027-12-27",
    },
}


def is_hk_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in HKEX_HOLIDAYS.get(day.year, set())


def main() -> None:
    hong_kong_today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    result = str(is_hk_trading_day(hong_kong_today)).lower()
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"is_trading_day={result}\n")
    print(f"is_trading_day={result}")


if __name__ == "__main__":
    main()
