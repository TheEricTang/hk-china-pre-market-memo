# HK Trading-Day Refresh Countdown

## Goal

Show readers when the next HK/China memo refresh is expected, while moving the automated generation from 06:10 to 06:40 Hong Kong time so the run can include the morning edition of 东方财富财经早餐.

## Schedule

- Generate at 06:40 Asia/Hong_Kong on Hong Kong trading days.
- Do not generate on Saturdays, Sundays, or HKEX market holidays.
- Keep Hong Kong time authoritative regardless of the reader's browser timezone.
- Retain manual intraday generation as a separate, explicitly labelled preview mode.

## Countdown display

Place a compact status line beneath the edition label and above the memo title.

- Before the next run: `Next refresh in 12h 34m · 22 Jul, 06:40 HKT`.
- From 06:40 until a current-day edition is published: `Today's refresh is in progress`.
- Once the current-day edition is published: count down to the next HK trading day.
- Update the display every second without reloading the page.
- Include a machine-readable next-run timestamp and accessible status text.

## Trading-day calendar

Use an explicit HKEX holiday list in the generated site alongside weekend rules. Keep the holiday data isolated from countdown presentation so it can later be replaced by a market-calendar service. If the holiday calendar does not cover the candidate year, show a conservative weekday-based estimate marked `estimated` rather than silently claiming exchange-calendar precision.

## Publication behavior

The scheduled cloud job should still preserve the previous valid edition if research, validation, or deployment fails. The countdown does not imply that publication is guaranteed precisely at 06:40; 06:40 is the generation start time. While generation is underway, the site must say so plainly.

## Future personalization boundary

This version does not add accounts or store user preferences. A later application phase may add:

- selected stock tickers and internet-news scans;
- pre-market, end-of-day, and custom-time memo schedules;
- user timezone and delivery preferences;
- email delivery and social sign-in.

The countdown logic should accept schedule data as configuration so the fixed 06:40 schedule can later be replaced with a user-specific schedule without redesigning the component.

## Validation

- Test the next-run calculation before 06:40, during the in-progress window, after publication, across weekends, and across an HKEX holiday.
- Confirm the workflow schedule is 06:40 HKT.
- Build the static site and inspect the published page text.
- Confirm the normal pre-open cutoff validator remains strict and the manual intraday path remains separate.
