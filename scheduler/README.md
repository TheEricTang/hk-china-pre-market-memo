# Independent morning delivery trigger

Cloudflare Worker Cron Triggers call the GitHub workflow-dispatch API independently of GitHub cron. This avoids the observed delayed scheduled-event creation; GitHub runners, the research provider and Pages remain dependencies. The Worker verifies both the public page and its hash-bound quality receipt.

## GitHub early-runner fallback

The workflow also requests a runner at 01:35, 02:35, 03:35 and 04:35 HKT. A runner that starts early waits until the actual same-day 06:35 HKT research window before synchronizing the repository and generating anything. It does not generate an early edition or backdate a late run. This gives delayed scheduled events several hours of margin while keeping the intended research cutoff. The existing daily concurrency group and current-edition checks suppress duplicate generation.

Only these marked early scheduled jobs have a six-hour outer limit. Waiting is capped at five hours with short clock checks; normal jobs remain capped at 30 minutes, generation at 24 minutes with its 22-minute internal budget, and the other steps have bounded timeouts. Weekends, known HK holidays, unsupported calendar years and date rollover are handled explicitly. The Worker measures a same-day marked early runner's stall allowance from the later of its real creation time and 06:35 HKT, without rewriting its actual timestamp. Older runs receive no new allowance.

GitHub documents a [six-hour hosted-job limit](https://docs.github.com/en/actions/reference/limits) and [free standard hosted runners for public repositories](https://docs.github.com/en/actions/concepts/billing-and-usage). This fallback uses no new hosting account. It is still exposed to [delayed or dropped GitHub schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), and its first actual overnight operation must be observed before treating it as validated delivery. The independent Worker remains the stronger separate-clock safeguard.

## Activation prerequisites

1. Connect the owner's Cloudflare account. Do not deploy into an unrelated project or turn on billing without authorization.
2. Create an expiring GitHub fine-grained credential restricted to `TheEricTang/hk-china-pre-market-memo`, with **Actions: read and write** and required metadata access. Store it as the Worker's `GITHUB_TOKEN` secret. Do not copy a broad local GitHub OAuth token to cloud hosting or commit a token.
3. Deploy with `ENABLED=false` first. The config has no public HTTP trigger, preview URL or workers.dev URL. Only the scheduled handler can initiate work.
4. Complete live workflow validation and verify main contains the expected inputs, quality gate and public receipt implementation.
5. Enable the Worker and observe an actual scheduled execution during a Hong Kong trading morning. Cloudflare cron changes can take time to propagate; activate before the delivery window.
6. Confirm the same-date reviewed edition and matching hash appear at the existing public URL before 07:30 HKT. Record workflow start, research cutoff, review finish, deployment completion and public verification times separately. Exercise recovery on a test target before relying on it.

Use Wrangler's interactive login/secret commands; enter credentials through the provider prompt, never in chat or command history. Install/use a current compatible Wrangler version and inspect its deployment target before publishing.

## Controls

- Five-minute checks from 06:35 to 07:55 HKT (22:35–23:55 UTC).
- Skip weekends and explicit HK exchange holidays. The calendar is shared with the Python implementation and its synchronization is tested. Unsupported years fail visibly; renew the calendar before 2028.
- Stop when the live page, current-date receipt, research cutoff and content hash agree.
- Skip dispatch while a production main-branch run is active. Marked rehearsals do not block production or consume its attempt allowance. Runs stalled for more than 35 minutes require attention; the scheduler never cancels another run automatically.
- At most three generation-window dispatches; at most two additional deployment-only recovery dispatches after 07:30.
- After 07:30, recovery uses `generate=false`; the workflow refuses to fabricate or regenerate a missing approved edition.
- Public-page failures, GitHub API failures, exhausted attempts and missed targets remain visible in Worker execution logs. Never log secrets.

Notifications to a person/channel require the owner's selected destination. Execution logs alone are not a staffed incident response. Do not describe this as an unattended, guaranteed service until notification and recovery ownership are agreed and the acceptance run succeeds.

## Local regression tests

```sh
node --test scheduler/worker.test.mjs
```

Tests cover trading dates, HKT boundaries, duplicate suppression, limits, deployment-only recovery, credential/API failures, stale/early editions and mismatched public content. They do not substitute for a real cloud execution.
