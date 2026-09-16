# Independent morning delivery trigger

Cloudflare Worker Cron Triggers call the GitHub workflow-dispatch API independently of GitHub cron. This avoids the observed delayed scheduled-event creation; GitHub runners, the research provider and Pages remain dependencies. The Worker verifies both the public page and its hash-bound quality receipt.

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
