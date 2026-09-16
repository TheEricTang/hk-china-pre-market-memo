# HK/China Pre-Market Memo

Daily public-source market memo for Hong Kong trading days. The operating target is a reviewed edition **visible by 07:30 Hong Kong time**, leaving a buffer before the 08:00 distribution deadline. Hong Kong is UTC+8 throughout the year.

## Publication requirements

A draft is not published until formatting, current-date/cutoff checks, retrieved-source provenance, a separate factual review, and an eight-area coverage review pass. Material omissions or provenance failures permit up to two bounded repairs, each followed by a new review; persistent errors preserve the previous edition. A content-bound receipt accompanies successful publication. Deployment is only successful when the public page and receipt match the approved edition.

The review covers overnight markets; China/Hong Kong policy; AI and semiconductors; property and consumption; healthcare and industry; companies and capital markets; the calendar; and Chinese-language news. Each category must have researched evidence even when there is no material new item. Review is evidence-assisted model judgment, not proof that every fact or relevant event has been found. Editorial acceptance must be checked against real morning output.

Facts are reviewed in batches of at most three paragraphs, alongside a separate coverage review. At most four review requests run concurrently. Each batch must establish its own source evidence; another batch cannot supply missing provenance. All stages share the overall generation deadline.

## Timing and recovery

- Research may begin at 06:35 HKT. Automatic generation cannot start after 07:30.
- Early scheduled attempts at 01:35, 02:35, 03:35 and 04:35 HKT hold a runner until the actual 06:35 research window. Waiting is capped at five hours and only marked early jobs have a six-hour outer limit; normal jobs remain at 30 minutes. The existing 06:40, 06:52 and 07:04 schedules remain as retries. GitHub can delay or drop scheduled events, so this fallback still requires observed morning acceptance.
- The independent scheduler in `scheduler/` checks every five minutes in the morning window, triggers a non-forcing workflow, and verifies the actual public edition. It ships **disabled** until the cloud account and restricted GitHub credential are configured and tested.
- Existing approved editions are redeployed without paying to regenerate them. Late deployment-only recovery is bounded and stops dispatching at 08:00.
- Automatic runs reserve a deployment margin before 08:00 and explicitly fail the delivery check when live confirmation misses the 07:30 target, even if a valid edition eventually appears.
- Failed quality checks never turn into permission to publish unchecked material. A late/missing edition remains an operational incident even if a later attempt succeeds.

Do not mark delivery fixed based on repository code or unit tests alone. Daily-delivery acceptance requires a successful live research/review rehearsal, an actual scheduled morning execution, and verification of the final page and receipt within the HKT deadline. The independent scheduler additionally requires its own authenticated cloud execution. Cloud incidents and factual-review limitations still need an operational owner; no best-effort service provides an unconditional availability guarantee.

## Validation

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
node --test scheduler/worker.test.mjs
```

For a paid live rehearsal, manually dispatch **Daily HK China memo** with `dry_run=true`, `automatic=false`, `generate=true` and `edition_mode=intraday`. This researches and reviews a candidate without committing it or publishing. The validation environment is separate from protected GitHub Pages. Audit artifacts use an explicit public-source-only allowlist; public repository readers may download them. Never put private correspondence, credentials or private source material in these artifacts.

See [scheduler setup and acceptance](scheduler/README.md).
