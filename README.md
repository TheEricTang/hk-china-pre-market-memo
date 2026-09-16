# HK/China Pre-Market Memo

Daily public-source market memo for Hong Kong trading days. The operating target is a reviewed edition **visible by 07:30 Hong Kong time**, leaving a buffer before the 08:00 distribution deadline. Hong Kong is UTC+8 throughout the year.

## Publication requirements

A draft is not published until formatting, current-date/cutoff checks, retrieved-source provenance, a separate factual review, and an eight-area coverage review pass. Material omissions trigger one repair and a new review; persistent errors preserve the previous edition. A content-bound receipt accompanies successful publication. Deployment is only successful when the public page and receipt match the approved edition.

The review covers overnight markets; China/Hong Kong policy; AI and semiconductors; property and consumption; healthcare and industry; companies and capital markets; the calendar; and Chinese-language news. Each category must have researched evidence even when there is no material new item. Review is evidence-assisted model judgment, not proof that every fact or relevant event has been found. Editorial acceptance must be checked against real morning output.

## Timing and recovery

- Research may begin at 06:35 HKT. Automatic generation cannot start after 07:30.
- GitHub's existing 06:40, 06:52 and 07:04 schedules are fallback triggers; GitHub can delay scheduled events.
- The independent scheduler in `scheduler/` checks every five minutes in the morning window, triggers a non-forcing workflow, and verifies the actual public edition. It ships **disabled** until the cloud account and restricted GitHub credential are configured and tested.
- Existing approved editions are redeployed without paying to regenerate them. Late deployment-only recovery is bounded and stops dispatching at 08:00.
- Failed quality checks never turn into permission to publish unchecked material. A late/missing edition remains an operational incident even if a later attempt succeeds.

Do not mark delivery fixed based on repository code or unit tests alone. Activation requires a successful live research/review rehearsal, independent scheduler execution, and verification of the final page and receipt within the HKT deadline. Cloud incidents and factual-review limitations still need an operational owner; no best-effort service provides an unconditional availability guarantee.

## Validation

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
node --test scheduler/worker.test.mjs
```

For a paid live rehearsal, manually dispatch **Daily HK China memo** with `dry_run=true`, `automatic=false`, `generate=true` and `edition_mode=intraday`. This researches and reviews a candidate without committing it or publishing. The validation environment is separate from protected GitHub Pages. Audit artifacts use an explicit public-source-only allowlist; public repository readers may download them. Never put private correspondence, credentials or private source material in these artifacts.

See [scheduler setup and acceptance](scheduler/README.md).
