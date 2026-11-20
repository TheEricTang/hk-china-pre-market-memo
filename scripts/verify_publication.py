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


def delivery_result(confirmed: bool, checked_at: datetime, automatic: bool) -> dict:
    checked_at = checked_at.astimezone(ZoneInfo("Asia/Hong_Kong"))
    target = checked_at.replace(hour=7, minute=30, second=0, microsecond=0)
    on_time = confirmed and checked_at <= target
    return {"confirmed": confirmed, "checkedAt": checked_at.isoformat(),
            "targetHkt": target.isoformat(), "onTime": on_time,
            "automatic": automatic, "accepted": confirmed and (not automatic or on_time)}


def main() -> None:
    receipt = json.loads((ROOT / "docs" / "status.json").read_text(encoding="utf-8"))
    today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat()
    if "--local-only" in sys.argv:
        if not approved_today(receipt, today):
            raise SystemExit("Refusing to deploy an outdated or unreviewed edition")
        print("Today's publication receipt passed; deployment is permitted.")
        return
    confirmed = verify(receipt, today)
    result = delivery_result(confirmed, datetime.now(ZoneInfo("Asia/Hong_Kong")),
                             os.getenv("MEMO_AUTOMATIC") == "true")
    result.update(editionDate=receipt.get("editionDate"), memoSha256=receipt.get("memoSha256"))
    artifact = ROOT / "artifacts" / "publication-verification.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary = (f"Public edition {'verified' if confirmed else 'NOT verified'}: "
               f"{receipt.get('title', 'unknown')}\n")
    if result["automatic"]:
        summary += f"07:30 HKT delivery target: {'MET' if result['onTime'] else 'MISSED'}; confirmed at {result['checkedAt']}\n"
    print(summary, end="")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary)
    if not confirmed:
        raise SystemExit("Live page and quality receipt do not confirm today's approved edition")
    if not result["accepted"]:
        raise SystemExit("Approved edition is live, but the 07:30 HKT delivery target was missed")


if __name__ == "__main__":
    main()
