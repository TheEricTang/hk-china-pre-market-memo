import html
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from trading_calendar import HKEX_HOLIDAYS
from publication_status import memo_hash, publication_status

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ARCHIVE = DOCS / "archive"
LINK = re.compile(r"\[\[([^\]]+)\]\((https?://[^)\s]+)\)\]")

CSS = """
:root{--paper:#f5f3ed;--ink:#171916;--muted:#686b65;--line:#d8d6ce;--accent:#174f9b}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.58 Georgia,serif}.wrap{width:min(100% - 32px,900px);margin:auto;padding:48px 0 72px}.brand{font:700 12px/1.2 Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;border-bottom:4px solid var(--ink);padding-bottom:18px}.eyebrow,.window,.stamp{font:700 12px/1.5 Arial,sans-serif;color:var(--muted);letter-spacing:.07em}.refresh-status{display:inline-flex;margin-top:14px;padding:7px 10px;border:1px solid var(--line);border-radius:3px;color:var(--accent);font:700 12px/1.2 Arial,sans-serif;letter-spacing:.03em}h1{font-size:clamp(32px,6vw,58px);line-height:1.05;font-weight:500;letter-spacing:-.035em;margin:42px 0 12px}.memo{list-style:none;margin:32px 0;padding:0;border-top:1px solid var(--line)}.memo li{display:grid;grid-template-columns:36px 1fr;gap:12px;padding:20px 0;border-bottom:1px solid var(--line)}.num{font:11px monospace;color:#969991}.memo p{margin:0}.memo b{font-family:Arial,sans-serif;font-size:14px}.memo a{color:var(--accent);font:700 12px Arial,sans-serif;text-decoration:none}.archive{margin-top:54px;padding-top:24px;border-top:2px solid var(--ink)}.archive a{display:inline-block;margin:5px 16px 5px 0;color:var(--accent);font:13px Arial,sans-serif}.stamp{margin-top:30px}.disclaimer{margin-top:42px;color:var(--muted);font:11px Arial,sans-serif}@media(max-width:600px){.wrap{padding-top:28px}.memo li{grid-template-columns:26px 1fr}h1{margin-top:34px}}
"""

FRESHNESS_SCRIPT = """<script>
(() => {
  const config = __CONFIG__;
  const el = document.querySelector('.refresh-status');
  const iso = d => d.toISOString().slice(0, 10);
  const label = value => new Date(value + 'T00:00:00Z').toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric', timeZone:'UTC'});
  const supported = d => Object.prototype.hasOwnProperty.call(config.holidays, String(d.getUTCFullYear()));
  const tradingDay = d => d.getUTCDay() > 0 && d.getUTCDay() < 6 && !((config.holidays[d.getUTCFullYear()] || []).includes(iso(d)));
  const nextDay = d => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1));
  const edition = label(config.editionDate);
  const cutoff = config.qualityPassed && config.researchCutoff
    ? ' · Research cutoff ' + new Date(config.researchCutoff).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit', timeZone:'Asia/Hong_Kong'}) + ' HKT'
    : ' · Review receipt unavailable';
  function render() {
    if (config.archived) {
      el.textContent = `Archive edition · ${edition}${cutoff}`;
      return;
    }
    const now = new Date(Date.now() + 8 * 60 * 60 * 1000);
    const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    if (config.editionDate === iso(today)) {
      const kind = config.editionMode === 'intraday' ? 'Intraday edition' : "Today's edition";
      el.textContent = `${kind} · ${edition}${cutoff}`;
      return;
    }
    if (!supported(today)) {
      el.textContent = `Showing ${edition} · Publication calendar needs updating`;
      return;
    }
    if (tradingDay(today)) {
      const minutes = now.getUTCHours() * 60 + now.getUTCMinutes();
      el.textContent = minutes < 7 * 60 + 30
        ? `Today's edition is not yet available · Showing ${edition} · Target 07:30 HKT`
        : `Today's edition is delayed — showing ${edition} · Target 07:30 HKT`;
      return;
    }
    let next = nextDay(today);
    while (supported(next) && !tradingDay(next)) next = nextDay(next);
    el.textContent = supported(next)
      ? `Showing ${edition} · Next publication target: ${label(iso(next))}, 07:30 HKT`
      : `Showing ${edition} · Publication calendar needs updating`;
  }
  render();
  setInterval(render, 60000);
})();
</script>"""


def inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = LINK.sub(r'<a href="\2" target="_blank" rel="noopener noreferrer">[\1]</a>', escaped)
    escaped = re.sub(r"^([^:]{3,100}:)", r"<b>\1</b>", escaped, count=1)
    return escaped


def parse(path: Path):
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    title = lines[0]
    window = lines[1]
    bullets = [line[2:] for line in lines[2:] if line.startswith("- ")]
    return title, window, bullets


def page(title: str, window: str, bullets: list[str], memos: list[Path], prefix: str = "", memo_sha256: str = "", *, memo_date: str | None = None, receipt: dict | None = None) -> str:
    items = "".join(f'<li><span class="num">{i:02d}</span><p>{inline(item)}</p></li>' for i, item in enumerate(bullets, 1))
    links = "".join(f'<a href="{prefix}archive/{memo.stem}.html">{memo.stem[5:]}</a>' for memo in reversed(memos))
    memo_date = memo_date or memos[-1].stem[5:]
    receipt = receipt or {}
    archived = bool(prefix)
    reviewed = receipt.get("qualityPassed") is True
    edition_label = datetime.strptime(memo_date, "%Y-%m-%d").strftime("%d %b %Y")
    config = {
        "editionDate": memo_date,
        "editionMode": "intraday" if title.startswith("Intraday Market Memo") else "preopen",
        "qualityPassed": reviewed,
        "researchCutoff": receipt.get("researchCutoff") if reviewed else None,
        "archived": archived,
        "holidays": {str(year): sorted(days) for year, days in HKEX_HOLIDAYS.items()},
    }
    freshness = FRESHNESS_SCRIPT.replace("__CONFIG__", json.dumps(config, separators=(",", ":")))
    if archived:
        eyebrow = f"Archive · {edition_label}"
    else:
        eyebrow = "Intraday preview" if config["editionMode"] == "intraday" else "Pre-open edition"
        if reviewed:
            eyebrow = "Reviewed " + eyebrow.lower()
    stamp = f"Edition dated {edition_label}"
    if reviewed and receipt.get("generatedAt"):
        generated = datetime.fromisoformat(receipt["generatedAt"]).astimezone(timezone(timedelta(hours=8)))
        stamp = f"Generated {generated:%d %b %Y %H:%M HKT}"
    initial_status = f"{'Archive edition' if archived else 'Edition'} · {edition_label}"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><meta name="memo-sha256" content="{html.escape(memo_sha256)}"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><main class="wrap"><header class="brand">HK / China Market Memo</header><div class="eyebrow">{eyebrow}</div><div class="refresh-status" role="status" aria-live="polite">{html.escape(initial_status)}</div><h1>{html.escape(title)}</h1><p class="window">{html.escape(window)}</p><ol class="memo">{items}</ol><p class="stamp">{html.escape(stamp)}</p><nav class="archive" aria-label="Memo archive"><b>Archive</b><br>{links}</nav><p class="disclaimer">Compiled from public sources. Informational only — not investment advice.</p></main>{freshness}</body></html>'''


def main() -> None:
    memos = sorted((ROOT / "memos").glob("memo-????-??-??.md"))
    if not memos:
        raise SystemExit("No memos found")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    valid_pages = {f"{memo.stem}.html" for memo in memos}
    for stale in ARCHIVE.glob("memo-????-??-??.html"):
        if stale.name not in valid_pages:
            stale.unlink()
    for memo in memos:
        title, window, bullets = parse(memo)
        (ARCHIVE / f"{memo.stem}.html").write_text(page(title, window, bullets, memos, "../", memo_hash(memo), memo_date=memo.stem[5:], receipt=publication_status(memo)), encoding="utf-8")
    title, window, bullets = parse(memos[-1])
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page(title, window, bullets, memos, memo_sha256=memo_hash(memos[-1]), memo_date=memos[-1].stem[5:], receipt=publication_status(memos[-1])), encoding="utf-8")
    (DOCS / "status.json").write_text(json.dumps(publication_status(memos[-1]), indent=2) + "\n", encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built site from {memos[-1].name} with {len(memos)} archived memos")


if __name__ == "__main__":
    main()
