import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import OpenAI

from validate_memo import validate

ROOT = Path(__file__).resolve().parents[1]
HKT = ZoneInfo("Asia/Hong_Kong")


def main() -> None:
    now = datetime.now(HKT)
    filename = f"memo-{now:%Y-%m-%d}.md"
    destination = ROOT / "memos" / filename
    historical = (ROOT / "prompt" / "editorial-baseline.md").read_text(encoding="utf-8")
    overrides = (ROOT / "prompt" / "cloud-runbook.md").read_text(encoding="utf-8")
    instruction = f"""Today is {now:%A, %d %B %Y} in Hong Kong.
Execute the cloud runbook below. The historical baseline follows it and is subordinate where they conflict.

=== CLOUD RUNBOOK ===
{overrides}

=== HISTORICAL EDITORIAL BASELINE ===
{historical}

Return only the finished Markdown memo. Do not include analysis, a preface, code fences, or a completion note.
"""

    client = OpenAI()
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
        input=instruction,
        tools=[{"type": "web_search"}],
        reasoning={"effort": "high"},
        max_output_tokens=14000,
        store=False,
    )
    candidate = ROOT / "memos" / f".{filename}.candidate"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(response.output_text.strip() + "\n", encoding="utf-8")
    errors = validate(candidate.read_text(encoding="utf-8"), filename)
    if errors:
        raise ValueError("\n".join(errors))
    candidate.replace(destination)
    print(f"Published candidate {filename}")


if __name__ == "__main__":
    main()
