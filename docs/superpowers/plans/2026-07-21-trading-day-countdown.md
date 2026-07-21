# HK Trading-Day Countdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move generation to 06:40 HKT on HK trading days and display a live countdown or in-progress status on every memo page.

**Architecture:** Keep schedule calculation in a small dependency-free browser script generated with each static page. Pass the memo date into the page so the script can distinguish an unpublished current-day edition from a completed refresh. Gate the daily workflow with a Python trading-day check using an explicit official HKEX holiday calendar.

**Tech Stack:** Python 3.12, static HTML/CSS/JavaScript, GitHub Actions, `unittest`.

## Global Constraints

- Hong Kong time is authoritative for every viewer.
- Generation starts at 06:40 HKT and skips weekends and HKEX securities-market holidays.
- A failed run leaves the prior valid memo live.
- Manual intraday previews remain separate from scheduled pre-open editions.
- The countdown must remain configurable for future user-specific schedules.

---

### Task 1: Trading-day gate

**Files:**
- Create: `scripts/trading_calendar.py`
- Create: `tests/test_trading_calendar.py`
- Modify: `.github/workflows/daily-memo.yml`

**Interfaces:**
- Produces: `is_hk_trading_day(day: date) -> bool` and a command that exits 0 on a trading day, 78 otherwise.
- Consumes: the official 2026 HKEX securities-market holiday dates.

- [ ] Write tests for a normal weekday, weekend, and 1 October 2026 HKEX holiday.
- [ ] Run `python3 -m unittest tests.test_trading_calendar -v` and confirm it fails because the module is absent.
- [ ] Implement `HKEX_HOLIDAYS`, `is_hk_trading_day`, and the command exit status.
- [ ] Change the schedule to `40 6 * * *` with `timezone: Asia/Hong_Kong`; add a gate step and condition generation/publication on its output for scheduled runs, while preserving manual runs.
- [ ] Run the calendar tests and confirm all pass.

### Task 2: Countdown component

**Files:**
- Modify: `scripts/build_site.py`
- Create: `tests/test_build_site.py`

**Interfaces:**
- Consumes: memo date parsed from `memo-YYYY-MM-DD.md`, refresh hour/minute, and `HKEX_HOLIDAYS` serialized as ISO dates.
- Produces: accessible `.refresh-status` HTML and a dependency-free script that renders the next refresh in Hong Kong time.

- [ ] Write tests asserting the built HTML contains the 06:40 configuration, 2026 holiday data, `aria-live="polite"`, and both countdown/in-progress copy.
- [ ] Run `python3 -m unittest tests.test_build_site -v` and confirm the new assertions fail.
- [ ] Add the compact status-line styles and HTML immediately below the edition label.
- [ ] Add browser logic that calculates Hong Kong date/time via `Intl.DateTimeFormat`, skips weekends/holidays, shows `Today's refresh is in progress` after 06:40 when the latest memo is not dated today, and otherwise counts down to the next trading-day run once per second.
- [ ] Run the build-site tests and confirm all pass.

### Task 3: Full verification and publication

**Files:**
- Modify through generation: `docs/index.html`, `docs/archive/*.html`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: deployed GitHub Pages site and active 06:40 trading-day workflow.

- [ ] Run `python3 -m unittest discover -s tests -v` and confirm zero failures.
- [ ] Run `python3 scripts/build_site.py` and confirm it builds from the latest memo.
- [ ] Inspect `git diff --check` and the generated index for the new status component.
- [ ] Commit and push the implementation and generated site.
- [ ] Trigger a deployment-only workflow run and confirm it completes successfully.
- [ ] Fetch the public URL and confirm the live HTML includes the 06:40 countdown configuration.
