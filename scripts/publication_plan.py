"""Separate automatic generation freshness from public deployment freshness."""

import os
import json
import time
from datetime import datetime, time as wall_time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from memo_freshness import is_current_memo
from trading_calendar import is_hk_trading_day
from publication_status import publication_status

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_URL = "https://theerictang.github.io/hk-china-pre-market-memo/"
HKT = ZoneInfo("Asia/Hong_Kong")
FIRST_GENERATION_MINUTE = 6 * 60 + 35
LAST_GENERATION_MINUTE = 7 * 60 + 30
PUBLICATION_DEADLINE_MINUTE = 8 * 60


class PublicationDeadlineError(RuntimeError):
    """An automatic run missed the safe pre-open generation/publication window."""


def final_preopen_receipt(receipt: dict, now: datetime) -> bool:
    """An early provisional edition must not suppress the final morning research."""
    try:
        cutoff = datetime.fromisoformat(receipt["researchCutoff"])
        if cutoff.tzinfo is None:
            return False
        cutoff = cutoff.astimezone(HKT)
        earliest = datetime.combine(now.date(), wall_time(6, 35), HKT)
        return (receipt.get("qualityPassed") is True
                and receipt.get("editionMode") == "preopen"
                and receipt.get("editionDate") == now.date().isoformat()
                and earliest <= cutoff <= now)
    except (KeyError, TypeError, ValueError):
        return False


class EditionHeading(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.heading = ""
        self.memo_sha256 = None

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.in_heading = True
        if tag == "meta":
            attributes = dict(attrs)
            if attributes.get("name") == "memo-sha256":
                self.memo_sha256 = attributes.get("content")

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_heading = False

    def handle_data(self, data):
        if self.in_heading:
            self.heading += data


def fetch_public(path: str = "") -> bytes:
    request = Request(
        f"{PUBLIC_URL}{path}?freshness={time.time_ns()}",
        headers={"Cache-Control": "no-cache", "User-Agent": "HK-China-Memo-Freshness"},
    )
    with urlopen(request, timeout=10) as response:
        content = response.read(1_000_001)
    if len(content) > 1_000_000:
        raise ValueError("Public response exceeded 1 MB")
    return content


def live_edition_is_current(expected_title: str, expected_hash: str | None = None) -> bool:
    """A failed/unverifiable check permits redeployment, never regeneration."""
    try:
        parser = EditionHeading()
        parser.feed(fetch_public().decode("utf-8"))
        if parser.heading.strip() != expected_title:
            return False
        if expected_hash is None:
            return True
        receipt = json.loads(fetch_public("status.json").decode("utf-8"))
        return (isinstance(receipt, dict)
                and receipt.get("title") == expected_title
                and receipt.get("memoSha256") == expected_hash
                and parser.memo_sha256 == expected_hash
                and receipt.get("qualityPassed") is True)
    except (OSError, URLError, UnicodeError, ValueError):
        print("Could not verify the public edition; deployment will be retried.")
        return False


def publication_plan(*, automatic: bool, trading_day: bool,
                     generate_requested: bool, canonical_current: bool,
                     live_current: bool, hkt_time: wall_time) -> tuple[bool, bool]:
    """Return (generate_required, publish_required), preserving manual force."""
    if not automatic:
        return generate_requested, True
    minute = hkt_time.hour * 60 + hkt_time.minute
    if not trading_day or minute < FIRST_GENERATION_MINUTE:
        return False, False
    if canonical_current:
        if live_current:
            return False, False
        if minute >= PUBLICATION_DEADLINE_MINUTE:
            raise PublicationDeadlineError(
                "Missed 08:00 HKT publication deadline: approved edition exists but website is stale; manual recovery required.")
        return False, True
    if minute > LAST_GENERATION_MINUTE:
        raise PublicationDeadlineError(
            "Missed automatic generation deadline: no approved final edition exists after 07:30 HKT; manual recovery required.")
    return generate_requested, True


def main() -> None:
    now = datetime.now(HKT)
    today = now.date()
    dispatched = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
    automatic = not dispatched or os.getenv("AUTOMATIC", "false") == "true"
    generate_requested = not dispatched or os.getenv("GENERATE", "true") == "true"
    trading_day = is_hk_trading_day(today)
    expected_title = f"Morning Market Memo | {today:%d %b %Y} | HK/China Pre-Open"
    memo = ROOT / "memos" / f"memo-{today}.md"
    canonical_current = is_current_memo(memo, expected_title)
    receipt = publication_status(memo) if canonical_current else {}
    canonical_current = canonical_current and final_preopen_receipt(receipt, now)
    live_current = (live_edition_is_current(expected_title, receipt["memoSha256"])
                    if automatic and trading_day and canonical_current
                    and now.time() >= wall_time(6, 35) else False)
    try:
        generate, publish = publication_plan(
            automatic=automatic, trading_day=trading_day,
            generate_requested=generate_requested, canonical_current=canonical_current,
            live_current=live_current, hkt_time=now.time(),
        )
    except PublicationDeadlineError as error:
        raise SystemExit(f"::error::{error}") from error
    outputs = f"generate_required={str(generate).lower()}\nrequired={str(publish).lower()}\n"
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(outputs)
    print(f"Automatic={automatic}; trading day={trading_day}; "
          f"saved edition current={canonical_current}; public edition current={live_current}")
    print(outputs, end="")


if __name__ == "__main__":
    main()
