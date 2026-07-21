import re
from pathlib import Path

FILE_RE = re.compile(r"^memo-\d{4}-\d{2}-\d{2}\.md$")
TITLE_RE = re.compile(r"^Morning Market Memo \| \d{2} [A-Z][a-z]{2} \d{4} \| HK/China Pre-Open$")
INTRADAY_TITLE_RE = re.compile(r"^Intraday Market Memo \| \d{2} [A-Z][a-z]{2} \d{4} \| HK/China Update$")
LINK_RE = re.compile(r"\[\[[^\]]+\]\(https?://[^)\s]+\)\]")


def validate(markdown: str, filename: str, edition_mode: str = "preopen") -> list[str]:
    errors: list[str] = []
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if not FILE_RE.match(filename):
        errors.append("Filename must be memo-YYYY-MM-DD.md")
    expected_title = INTRADAY_TITLE_RE if edition_mode == "intraday" else TITLE_RE
    if not lines or not expected_title.match(lines[0]):
        errors.append("Invalid memo title")
    if len(lines) < 2 or not lines[1].startswith("(covers ") or "research cutoff)" not in lines[1]:
        errors.append("Coverage line must state the actual HKT research cutoff")
    elif match := re.search(r"(\d{2}):(\d{2}) HKT research cutoff", lines[1]):
        cutoff_minutes = int(match.group(1)) * 60 + int(match.group(2))
        if edition_mode != "intraday" and cutoff_minutes >= 9 * 60 + 30:
            errors.append("Research cutoff must be before the 09:30 HKT market open")
    bullets = [line for line in lines[2:] if line.startswith("- ")]
    if len(bullets) < 8:
        errors.append("Memo needs at least 8 verified bullets")
    for number, bullet in enumerate(bullets, 1):
        if not LINK_RE.search(bullet):
            errors.append(f"Bullet {number} has no specific source link")
        if re.search(r"\(\[[^\]]+\]\(https?://", bullet):
            errors.append(f"Bullet {number} contains a duplicate inline citation")
    return errors


def validate_file(path: Path) -> None:
    errors = validate(path.read_text(encoding="utf-8"), path.name)
    if errors:
        raise ValueError("\n".join(errors))
