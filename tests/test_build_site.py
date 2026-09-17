import sys
import json
import tempfile
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_site import page, main
from publication_status import memo_hash


class BuildSiteFreshnessTest(unittest.TestCase):
    def render_status(self, output, now):
        script = re.search(r"<script>([\s\S]*?)</script>", output).group(1)
        setup = ("const output = {textContent:''}; const document={querySelector:()=>output,addEventListener:()=>{}};"
                 "const setInterval=()=>{}; Date.now=()=>Date.parse(" + json.dumps(now) + ");")
        result = subprocess.run(["node", "-e", setup + script + "console.log(output.textContent);"],
                                capture_output=True, text=True, check=True, timeout=10)
        return result.stdout.strip()

    def run_browser(self, output, actions, *, receipt=None, visibility="visible", fetch_mode="normal"):
        script = re.search(r"<script>([\s\S]*?)</script>", output).group(1)
        setup = r"""
const assert = require('node:assert/strict');
let now = Date.parse('2026-09-16T23:40:00Z'); Date.now = () => now;
const status = {textContent:''}, notice = {hidden:true}, link = {href:'./'};
const events = {}, intervals = [], timers = [], calls = [];
const document = {visibilityState: VISIBILITY,
  querySelector: selector => ({'.refresh-status':status,'.edition-update':notice,'.load-latest':link})[selector],
  addEventListener: (name, callback) => {events[name] = callback;}};
const setInterval = callback => {intervals.push(callback);};
const setTimeout = (callback, delay) => {const timer = {callback,delay,cleared:false}; timers.push(timer); return timer;};
const clearTimeout = timer => {timer.cleared = true;};
let receipt = RECEIPT, fetchMode = FETCH_MODE;
const fetch = async (url, options) => {
  calls.push({url, options});
  if (fetchMode === 'offline') throw Error('Offline');
  if (fetchMode === 'pending') return new Promise((resolve,reject) => options.signal.addEventListener('abort',()=>reject(Error('Timeout'))));
  return {ok:fetchMode !== 'http_error', json:async()=>{
    if (fetchMode === 'bad_json') throw Error('Invalid JSON'); return receipt;}};
};
const flush = () => new Promise(resolve => setImmediate(resolve));
""".replace("VISIBILITY", json.dumps(visibility)).replace("RECEIPT", json.dumps(receipt)).replace("FETCH_MODE", json.dumps(fetch_mode))
        result = subprocess.run(["node", "-e", "(async()=>{" + setup + script + "await flush();" + actions + "})().catch(error=>{console.error(error);process.exit(1);});"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def receipt(self, **changes):
        return {"schemaVersion": 1, "editionDate": "2026-09-17", "editionMode": "preopen",
                "title": "Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open",
                "memoSha256": "b" * 64, "qualityPassed": True, **changes}

    def test_open_old_tab_discovers_new_receipt_without_replacing_loaded_memo(self):
        output = self.legacy_page(memo_sha256="a" * 64)
        self.run_browser(output, """
assert.match(status.textContent, /Today's edition is delayed/);
assert.equal(notice.hidden, true); assert.equal(calls.length, 1);
receipt = NEW_RECEIPT;
now += 59999; intervals[0](); await flush(); assert.equal(calls.length, 1);
now += 1; intervals[0](); await flush(); assert.equal(calls.length, 2);
assert.match(status.textContent, /New edition available/);
assert.match(status.textContent, /viewing the loaded 16 Sept 2026 edition/);
assert.equal(notice.hidden, false); assert.equal(link.href, './?edition=' + 'b'.repeat(64));
assert.equal(calls[1].options.cache, 'no-store'); assert.equal(calls[1].options.credentials, 'omit');
assert.equal(timers[1].delay, 10000); assert.equal(timers[1].cleared, true);
""".replace("NEW_RECEIPT", json.dumps(self.receipt())), receipt=self.receipt(
            editionDate="2026-09-16", title="Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open", memoSha256="a" * 64))
        self.assertIn('<h1>Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open</h1>', output)

    def test_same_day_intraday_update_and_legacy_receipt_offer_link_without_review_claim(self):
        receipt = self.receipt(editionDate="2026-09-16", editionMode="intraday", qualityPassed=False,
                               title="Intraday Market Memo | 16 Sep 2026 | HK/China Update")
        self.run_browser(self.legacy_page(memo_sha256="a" * 64), """
assert.match(status.textContent, /New edition available/); assert.equal(notice.hidden, false);
assert.doesNotMatch(status.textContent, /verified|reviewed|updated/i);
""", receipt=receipt)

    def test_hidden_tabs_pause_polling_and_visibility_resume_respects_throttle(self):
        self.run_browser(self.legacy_page(memo_sha256="a" * 64), """
assert.equal(calls.length, 0); intervals[0](); await flush(); assert.equal(calls.length, 0);
document.visibilityState = 'visible'; events.visibilitychange(); await flush(); assert.equal(calls.length, 1);
events.visibilitychange(); await flush(); assert.equal(calls.length, 1);
document.visibilityState = 'hidden'; now += 60000; intervals[0](); await flush(); assert.equal(calls.length, 1);
document.visibilityState = 'visible'; events.visibilitychange(); await flush(); assert.equal(calls.length, 2);
""", visibility="hidden", receipt=self.receipt())

    def test_archive_never_polls_or_offers_latest_link(self):
        output = self.legacy_page(prefix="../")
        self.run_browser(output, """
assert.equal(calls.length, 0); assert.equal(intervals.length, 0);
assert.equal(events.visibilitychange, undefined); assert.match(status.textContent, /Archive edition/);
""", receipt=self.receipt())
        self.assertNotIn('class="edition-update"', output)

    def test_failed_or_malformed_receipts_leave_loaded_status_unchanged(self):
        cases = [("offline", self.receipt()), ("http_error", self.receipt()), ("bad_json", self.receipt()),
                 ("normal", self.receipt(memoSha256="invalid")), ("normal", self.receipt(title="wrong heading")),
                 ("normal", self.receipt(editionDate="2026-09-15", title="Morning Market Memo | 15 Sep 2026 | HK/China Pre-Open")),
                 ("normal", self.receipt(editionDate="2026-09-18", title="Morning Market Memo | 18 Sep 2026 | HK/China Pre-Open")),
                 ("normal", self.receipt(memoSha256="a" * 64)), ("normal", None)]
        for mode, receipt in cases:
            with self.subTest(mode=mode, receipt=receipt):
                self.run_browser(self.legacy_page(memo_sha256="a" * 64), """
assert.match(status.textContent, /Today's edition is delayed/); assert.equal(notice.hidden, true);
""", receipt=receipt, fetch_mode=mode)

    def test_timeout_aborts_and_allows_next_check_without_concurrent_requests(self):
        self.run_browser(self.legacy_page(memo_sha256="a" * 64), """
assert.equal(calls.length, 1); now += 60000; intervals[0](); await flush(); assert.equal(calls.length, 1);
assert.equal(timers[0].delay, 10000); timers[0].callback(); await flush();
assert.equal(calls[0].options.signal.aborted, true); assert.equal(notice.hidden, true);
fetchMode = 'normal'; intervals[0](); await flush(); assert.equal(calls.length, 2);
assert.match(status.textContent, /New edition available/);
""", receipt=self.receipt(), fetch_mode="pending")

    def legacy_page(self, **kwargs):
        return page("Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open", "Research window",
                    ["Item: News. [[Source](https://example.com)]"],
                    [Path("memos/memo-2026-09-16.md")], **kwargs)

    def test_page_is_accessible_without_claiming_active_run_or_guaranteed_countdown(self):
        output = page(
            "Morning Market Memo | 21 Jul 2026 | HK/China Pre-Open",
            "(covers 20 Jul 16:00 HKT close → 21 Jul 06:39 HKT research cutoff)",
            ["Item: News. [[Source](https://example.com)]"],
            [Path("memos/memo-2026-07-21.md")],
        )
        self.assertIn('class="refresh-status"', output)
        self.assertIn('aria-live="polite"', output)
        self.assertIn('2026-10-01', output)
        self.assertNotIn("refresh is in progress", output)
        self.assertNotIn('Next refresh in', output)
        self.assertNotIn('Latest verified edition', output)

    def test_stale_before_target_says_not_yet_available(self):
        status = self.render_status(self.legacy_page(), "2026-09-16T23:29:59Z")
        self.assertIn("Today's edition is not yet available", status)
        self.assertIn("Showing 16 Sept 2026", status)
        self.assertIn("Target 07:30 HKT", status)
        self.assertNotIn("research begins", status)

    def test_stale_at_target_and_hours_later_explicitly_says_delayed(self):
        for now in ("2026-09-16T23:30:00Z", "2026-09-17T03:00:00Z"):
            status = self.render_status(self.legacy_page(), now)
            self.assertIn("Today's edition is delayed — showing 16 Sept 2026", status)
            self.assertNotIn("progress", status)

    def test_current_reviewed_edition_shows_its_date_and_receipt_cutoff(self):
        output = page("Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open", "Research window",
                      [], [Path("memos/memo-2026-09-17.md")], receipt={
                          "qualityPassed": True, "researchCutoff": "2026-09-17T06:35:00+08:00",
                          "generatedAt": "2026-09-17T07:12:00+08:00"})
        status = self.render_status(output, "2026-09-16T23:40:00Z")
        self.assertEqual(status, "Today's edition · 17 Sept 2026 · Research cutoff 06:35 HKT")
        self.assertIn("Generated 17 Sep 2026 07:12 HKT", output)

    def test_legacy_current_edition_does_not_claim_quality_review(self):
        output = self.legacy_page()
        status = self.render_status(output, "2026-09-16T03:00:00Z")
        self.assertIn("Review receipt unavailable", status)
        self.assertNotIn("Reviewed pre-open edition", output)

    def test_weekend_shows_next_target_instead_of_claiming_delay(self):
        status = self.render_status(self.legacy_page(), "2026-09-19T03:00:00Z")
        self.assertIn("Next publication target: 21 Sept 2026, 07:30 HKT", status)
        self.assertNotIn("delayed", status)

    def test_archive_uses_own_date_even_when_newer_edition_exists(self):
        output = page("Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open", "Research window", [],
                      [Path("memos/memo-2026-09-16.md"), Path("memos/memo-2026-09-17.md")],
                      prefix="../", memo_date="2026-09-16")
        status = self.render_status(output, "2026-09-16T23:40:00Z")
        self.assertEqual(status, "Archive edition · 16 Sept 2026 · Review receipt unavailable")
        self.assertIn('<div class="eyebrow">Archive · 16 Sep 2026</div>', output)
        self.assertNotIn("Latest verified edition", output)

    def test_unknown_calendar_year_does_not_invent_publication_schedule(self):
        status = self.render_status(self.legacy_page(), "2028-01-03T00:00:00Z")
        self.assertIn("Publication calendar needs updating", status)

    def test_build_publishes_hash_bound_receipt_without_private_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memos").mkdir()
            memo = root / "memos" / "memo-2026-09-17.md"
            title = "Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open"
            memo.write_text(f"{title}\nResearch window\n- Story: Fact.\n")
            older = root / "memos" / "memo-2026-09-16.md"
            older.write_text("Morning Market Memo | 16 Sep 2026 | HK/China Pre-Open\nResearch window\n- Old story.\n")
            digest = memo_hash(memo)
            memo.with_suffix(".status.json").write_text(json.dumps({
                "schemaVersion": 1, "editionDate": "2026-09-17", "editionMode": "preopen",
                "memoSha256": digest, "qualityPassed": True,
                "researchCutoff": "2026-09-17T06:35:00+08:00",
                "generatedAt": "2026-09-17T06:44:00+08:00", "privateEvidence": "never public",
            }))
            with patch("build_site.ROOT", root), patch("build_site.DOCS", root / "docs"), \
                    patch("build_site.ARCHIVE", root / "docs" / "archive"):
                main()
            status = json.loads((root / "docs" / "status.json").read_text())
            self.assertTrue(status["qualityPassed"])
            self.assertEqual(status["memoSha256"], digest)
            self.assertNotIn("privateEvidence", status)
            self.assertIn(f'name="memo-sha256" content="{digest}"',
                          (root / "docs" / "index.html").read_text())
            archive = (root / "docs" / "archive" / "memo-2026-09-16.html").read_text()
            self.assertIn('"editionDate":"2026-09-16"', archive)
            self.assertIn("Archive · 16 Sep 2026", archive)


if __name__ == "__main__":
    unittest.main()
