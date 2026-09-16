"""Fail deployment verification unless the public page exposes the approved edition."""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from publication_plan import live_edition_is_current

ROOT = Path(__file__).resolve().parents[1]


def approved_today(receipt: dict, today: str) -> bool:
    return (receipt.get("editionDate") == today and receipt.get("qualityPassed") is True
            and bool(receipt.get("title")) and bool(receipt.get("memoSha256")))


def verify(receipt: dict, today: str, attempts: int = 6) -> bool:
    if not approved_today(receipt, today):
        return False
    for attempt in range(attempts):
        if live_edition_is_current(receipt["title"], receipt["memoSha256"]):
            return True
        if attempt + 1 < attempts:
            time.sleep(10)
    return False


def main() -> None:
    receipt = json.loads((ROOT / "docs" / "status.json").read_text(encoding="utf-8"))
    today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat()
    if "--local-only" in sys.argv:
        if not approved_today(receipt, today):
            raise SystemExit("Refusing to deploy an outdated or unreviewed edition")
        print("Today's publication receipt passed; deployment is permitted.")
        return
    confirmed = verify(receipt, today)
    summary = (f"Public edition {'verified' if confirmed else 'NOT verified'}: "
               f"{receipt.get('title', 'unknown')}\n")
    print(summary, end="")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary)
    if not confirmed:
        raise SystemExit("Live page and quality receipt do not confirm today's approved edition")


if __name__ == "__main__":
    main()
