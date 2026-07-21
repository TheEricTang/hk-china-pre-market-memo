import html
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from trading_calendar import HKEX_HOLIDAYS

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ARCHIVE = DOCS / "archive"
LINK = re.compile(r"\[\[([^\]]+)\]\((https?://[^)\s]+)\)\]")

CSS = """
:root{--paper:#f5f3ed;--ink:#171916;--muted:#686b65;--line:#d8d6ce;--accent:#174f9b}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.58 Georgia,serif}.wrap{width:min(100% - 32px,900px);margin:auto;padding:48px 0 72px}.brand{font:700 12px/1.2 Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;border-bottom:4px solid var(--ink);padding-bottom:18px}.eyebrow,.window,.stamp{font:700 12px/1.5 Arial,sans-serif;color:var(--muted);letter-spacing:.07em}.refresh-status{display:inline-flex;margin-top:14px;padding:7px 10px;border:1px solid var(--line);border-radius:3px;color:var(--accent);font:700 12px/1.2 Arial,sans-serif;letter-spacing:.03em}h1{font-size:clamp(32px,6vw,58px);line-height:1.05;font-weight:500;letter-spacing:-.035em;margin:42px 0 12px}.memo{list-style:none;margin:32px 0;padding:0;border-top:1px solid var(--line)}.memo li{display:grid;grid-template-columns:36px 1fr;gap:12px;padding:20px 0;border-bottom:1px solid var(--line)}.num{font:11px monospace;color:#969991}.memo p{margin:0}.memo b{font-family:Arial,sans-serif;font-size:14px}.memo a{color:var(--accent);font:700 12px Arial,sans-serif;text-decoration:none}.archive{margin-top:54px;padding-top:24px;border-top:2px solid var(--ink)}.archive a{display:inline-block;margin:5px 16px 5px 0;color:var(--accent);font:13px Arial,sans-serif}.stamp{margin-top:30px}.disclaimer{margin-top:42px;color:var(--muted);font:11px Arial,sans-serif}@media(max-width:600px){.wrap{padding-top:28px}.memo li{grid-template-columns:26px 1fr}h1{margin-top:34px}}
"""

COUNTDOWN = """<script>
(() => {
  const config = { refreshHour: 6, refreshMinute: 40, latestMemoDate: '__MEMO_DATE__', holidays: __HOLIDAYS__ };
  const el = document.querySelector('.refresh-status');
  const pad = n => String(n).padStart(2, '0');
  const iso = d => `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
  const hktNow = () => new Date(Date.now() + 8 * 60 * 60 * 1000);
  const supported = d => Object.prototype.hasOwnProperty.call(config.holidays, String(d.getUTCFullYear()));
  const tradingDay = d => d.getUTCDay() > 0 && d.getUTCDay() < 6 && !((config.holidays[d.getUTCFullYear()] || []).includes(iso(d)));
  const nextDay = d => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1));
  const label = d => d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', timeZone:'UTC'});
  function render() {
    const now = hktNow();
    const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    const afterStart = now.getUTCHours() > config.refreshHour || (now.getUTCHours() === config.refreshHour && now.getUTCMinutes() >= config.refreshMinute);
    if (tradingDay(today) && afterStart && config.latestMemoDate !== iso(today)) {
      el.textContent = "Today's refresh is in progress";
      return;
    }
    let target = today;
    if (!tradingDay(target) || afterStart) target = nextDay(target);
    while (!tradingDay(target)) target = nextDay(target);
    const targetMs = Date.UTC(target.getUTCFullYear(), target.getUTCMonth(), target.getUTCDate(), config.refreshHour - 8, config.refreshMinute);
    const remaining = Math.max(0, targetMs - Date.now());
    const hours = Math.floor(remaining / 3600000);
    const minutes = Math.floor((remaining % 3600000) / 60000);
    const seconds = Math.floor((remaining % 60000) / 1000);
    const estimate = supported(target) ? '' : ' (estimated)';
    el.textContent = `Next refresh in ${hours}h ${minutes}m ${seconds}s · ${label(target)}, 06:40 HKT${estimate}`;
  }
  render();
  setInterval(render, 1000);
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


def page(title: str, window: str, bullets: list[str], memos: list[Path], prefix: str = "") -> str:
    items = "".join(f'<li><span class="num">{i:02d}</span><p>{inline(item)}</p></li>' for i, item in enumerate(bullets, 1))
    links = "".join(f'<a href="{prefix}archive/{memo.stem}.html">{memo.stem[5:]}</a>' for memo in reversed(memos))
    updated = datetime.now(timezone(timedelta(hours=8))).strftime("%d %b %Y %H:%M HKT")
    memo_date = memos[-1].stem[5:]
    holidays = json.dumps({str(year): sorted(days) for year, days in HKEX_HOLIDAYS.items()}, separators=(",", ":"))
    countdown = COUNTDOWN.replace("__MEMO_DATE__", memo_date).replace("__HOLIDAYS__", holidays)
    eyebrow = "Verified intraday preview" if title.startswith("Intraday Market Memo") else "Latest verified edition"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><main class="wrap"><header class="brand">HK / China Market Memo</header><div class="eyebrow">{eyebrow}</div><div class="refresh-status" role="status" aria-live="polite">Next refresh in …</div><h1>{html.escape(title)}</h1><p class="window">{html.escape(window)}</p><ol class="memo">{items}</ol><p class="stamp">Updated {updated}</p><nav class="archive" aria-label="Memo archive"><b>Archive</b><br>{links}</nav><p class="disclaimer">Compiled from public sources. Informational only — not investment advice.</p></main>{countdown}</body></html>'''


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
        (ARCHIVE / f"{memo.stem}.html").write_text(page(title, window, bullets, memos, "../"), encoding="utf-8")
    title, window, bullets = parse(memos[-1])
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page(title, window, bullets, memos), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built site from {memos[-1].name} with {len(memos)} archived memos")


if __name__ == "__main__":
    main()
