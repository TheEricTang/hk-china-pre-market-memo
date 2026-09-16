import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import APIConnectionError, APIStatusError, OpenAI

from validate_memo import validate

ROOT = Path(__file__).resolve().parents[1]
HKT = ZoneInfo("Asia/Hong_Kong")
RETRY_DELAYS = (15, 30, 60)


def request_memo(client: OpenAI, instruction: str):
    """Allow transient outages time to clear without unbounded API retries."""
    attempts = len(RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            return client.responses.create(
                model=os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
                input=instruction,
                tools=[{"type": "web_search"}],
                reasoning={"effort": "high"},
                max_output_tokens=14000,
                store=False,
            )
        except (APIConnectionError, APIStatusError) as error:
            if isinstance(error, APIStatusError):
                if error.status_code not in (408, 409, 429) and error.status_code < 500:
                    raise
                if error.code == "insufficient_quota":
                    raise
                reason = f"HTTP {error.status_code}"
            else:
                reason = "connection error or timeout"
            if attempt == attempts - 1:
                raise
            delay = RETRY_DELAYS[attempt]
            # Do not print provider response bodies, prompts, or credentials.
            print(
                f"Memo request attempt {attempt + 1}/{attempts} failed ({reason}); "
                f"retrying in {delay}s.",
                flush=True,
            )
            time.sleep(delay)


def main() -> None:
    now = datetime.now(HKT)
    edition_mode = os.getenv("EDITION_MODE", "preopen")
    filename = f"memo-{now:%Y-%m-%d}.md"
    destination = ROOT / "memos" / filename
    historical = (ROOT / "prompt" / "editorial-baseline.md").read_text(encoding="utf-8")
    overrides = (ROOT / "prompt" / "cloud-runbook.md").read_text(encoding="utf-8")
    mode_instruction = """
This is a manually requested intraday preview, not a pre-open edition. Use the heading:
`Intraday Market Memo | DD MMM YYYY | HK/China Update`
Use the truthful current HKT research cutoff, include only information available by that cutoff,
and do not describe the output as pre-market. This instruction overrides every pre-open heading
and cutoff requirement below. The next scheduled run will return to normal pre-open mode.
""" if edition_mode == "intraday" else ""
    instruction = f"""Today is {now:%A, %d %B %Y} in Hong Kong.
Execute the cloud runbook below. The historical baseline follows it and is subordinate where they conflict.
{mode_instruction}

=== CLOUD RUNBOOK ===
{overrides}

=== HISTORICAL EDITORIAL BASELINE ===
{historical}

Return only the finished Markdown memo. Do not include analysis, a preface, code fences, or a completion note.
"""

    # One retry layer: avoid multiplying these attempts by the SDK's retries.
    # Bound each network operation; the workflow retains its 30-minute deadline.
    with OpenAI(max_retries=0, timeout=300.0) as client:
        response = request_memo(client, instruction)
    markdown = response.output_text.strip()
    markdown = re.sub(
        r"\s*\(\[[^\]]+\]\(https?://[^\s)]+\)\)\s*(?=\[\[)",
        " ",
        markdown,
    )
    candidate = ROOT / "memos" / f".{filename}.candidate"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(markdown + "\n", encoding="utf-8")
    errors = validate(candidate.read_text(encoding="utf-8"), filename, edition_mode=edition_mode)
    if errors:
        raise ValueError("\n".join(errors))
    candidate.replace(destination)
    print(f"Published candidate {filename}")


if __name__ == "__main__":
    main()
