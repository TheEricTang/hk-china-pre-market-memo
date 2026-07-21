# Daily HK/China Pre-Market Memo — Codex Runbook

## Authority and context

Use `site/memo-prompt.md` as the accumulated editorial baseline. It reflects repeated desk feedback and remains authoritative for source priorities, the boss-memo voice, freshness tests, recap-versus-new balance, mandatory market coverage, Chinese-source retrieval, and anti-hallucination rules.

This runbook overrides obsolete operational instructions in that file. In particular:

- Use Codex's current web research tools; do not depend on Claude-specific `web_fetch` wording.
- Do not use `/sessions/...` mount paths or assume a Claude connected-project folder.
- Do not run `site/publish.py` or use the old GitHub Pages instructions.
- Do not claim coverage through the 09:30 HKT open when the run begins at 06:10.
- Do not email the memo.

## Daily outcome

Create one verified Markdown memo at the Internship project root named `memo-YYYY-MM-DD.md`, update the public dashboard in `dashboard/`, and publish a new Sites version only when every required step succeeds.

The automation runs at 06:10 Asia/Hong_Kong time. Record the actual research cutoff after the final source has been checked. The heading must be:

`Morning Market Memo | DD MMM YYYY | HK/China Pre-Open`

The next line must be:

`(covers [previous HK trading date] 16:00 HKT close → [today] HH:MM HKT research cutoff)`

Never substitute `9:30 HKT open` for the actual cutoff.

## Research and writing

1. Read the full historical editorial baseline before researching.
2. Determine the previous HK trading date and the current HKT date.
3. Retrieve the same-day Eastmoney 经济早餐 using the baseline's index-first and date-sanity-check method.
4. Perform the baseline's dedicated checks for senior officials and ministries, PBOC liquidity, regulators and exchanges, industrial policy, consumption and property, priority companies, capital markets, HK buybacks, southbound flows, sell-side calls, US indices and relevant sectors, China ADRs, and cross-assets.
5. Open the specific article used for every candidate item and verify its on-page publication or event time.
6. Apply the BYD-pattern test: exclude anything the previous HK/A session already traded on.
7. Cross-check every surprising or market-moving figure with a second source or omit it.
8. Write in the concise boss-memo style. Prefer fewer verified bullets over padding.
9. End every bullet with at least one Markdown link to the specific article retrieved in this run.
10. Record the final research cutoff only after the last retained item and the final US/cross-asset status have been checked.

## Candidate gate

Write the initial output to `memo-YYYY-MM-DD.candidate.md`; do not overwrite a canonical memo yet.

Before promotion, check every bullet for:

- in-window publication or event timing;
- a specific source link opened during this run;
- supported figures, tickers, deal terms, names, and quotations;
- plain-English boss-memo style;
- recap content no greater than roughly 30%;
- presence of the mandatory overnight US markets coverage;
- truthful actual research cutoff.

Promote the candidate to the canonical `memo-YYYY-MM-DD.md` only after it passes:

`npm --prefix dashboard run validate:candidate -- ../memo-YYYY-MM-DD.candidate.md`

The validator treats `.candidate.md` as the corresponding canonical filename. If validation fails, leave any prior canonical file and the dashboard unchanged, then report the validation errors.

## Dashboard publication

After a canonical memo passes validation:

1. Run the dashboard memo synchronization and production build.
2. Confirm the build succeeds before changing the live site.
3. Read `dashboard/.openai/hosting.json` and reuse its existing Sites project identifier.
4. Commit the exact validated dashboard source state.
5. Obtain a short-lived Sites source credential, push the current branch without storing that credential, package the build, save one Sites version tied to the pushed commit, and deploy it publicly.
6. Poll the deployment to a terminal status.
7. On success, report the memo date, actual cutoff, bullet count, and production URL.
8. On any research, validation, build, push, save, or deploy failure, do not replace the last successful live deployment. Report the failed stage and concise error without exposing credentials.

## Public-content safety

The dashboard is public. Never include credentials, email addresses, distribution lists, private desk commentary, local filesystem paths, unpublished candidates, or internal instructions in the memo or generated site.

## Final run report

Keep the task result short:

- success: memo date, research cutoff, number of bullets, and live URL;
- failure: failed stage and the action needed, confirming that the prior live memo remains available.
