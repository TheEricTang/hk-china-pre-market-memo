import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

FILE_RE = re.compile(r"^memo-\d{4}-\d{2}-\d{2}\.md$")
TITLE_RE = re.compile(r"^Morning Market Memo \| \d{2} [A-Z][a-z]{2} \d{4} \| HK/China Pre-Open$")
INTRADAY_TITLE_RE = re.compile(r"^Intraday Market Memo \| \d{2} [A-Z][a-z]{2} \d{4} \| HK/China Update$")
LINK_RE = re.compile(r"\[\[[^\]]+\]\(https?://[^)\s]+\)\]")


def validate(markdown: str, filename: str, edition_mode: str = "preopen", latest_cutoff: datetime | None = None) -> list[str]:
    errors: list[str] = []
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if not FILE_RE.match(filename):
        errors.append("Filename must be memo-YYYY-MM-DD.md")
    expected_title = INTRADAY_TITLE_RE if edition_mode == "intraday" else TITLE_RE
    if not lines or not expected_title.match(lines[0]):
        errors.append("Invalid memo title")
    try:
        edition_date = datetime.strptime(filename, "memo-%Y-%m-%d.md").date()
        title_date = datetime.strptime(lines[0].split(" | ")[1], "%d %b %Y").date()
        if edition_date != title_date:
            errors.append("Title date must match filename date")
    except (ValueError, IndexError):
        errors.append("Filename and title must contain valid calendar dates")
        edition_date = None
    cutoff_match = re.fullmatch(
        r"\(covers (\d{2} [A-Z][a-z]{2}) 16:00 HKT close → (\d{2} [A-Z][a-z]{2}) (\d{2}:\d{2}) HKT research cutoff\)",
        lines[1] if len(lines) > 1 else "",
    )
    if not cutoff_match:
        errors.append("Coverage line must state the actual HKT research cutoff")
    elif edition_date:
        try:
            cutoff = datetime.strptime(f"{edition_date.year} {cutoff_match[2]} {cutoff_match[3]}", "%Y %d %b %H:%M").replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
            if cutoff.date() != edition_date:
                errors.append("Research cutoff date must match edition date")
            if edition_mode != "intraday" and (cutoff.hour, cutoff.minute) >= (9, 30):
                errors.append("Research cutoff must be before the 09:30 HKT market open")
            if latest_cutoff is not None and cutoff > latest_cutoff:
                errors.append("Research cutoff cannot be later than the machine-recorded cutoff")
        except ValueError:
            errors.append("Research cutoff must be a valid HKT date and time")
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
