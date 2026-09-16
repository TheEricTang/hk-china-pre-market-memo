# HK/China Pre-Market Memo

Public daily news dashboard with a 07:30 Asia/Hong_Kong publication target.
Research begins no earlier than 06:35 HKT; the displayed edition date remains
authoritative when publication is delayed.

The workflow requests a runner at 01:35, 02:35, 03:35 and 04:35 HKT, then waits
until the actual 06:35 research window. This gives delayed scheduled events
additional margin without creating an early, stale memo. Waiting is capped at
five hours, and only these early jobs have a six-hour outer limit. Ordinary jobs
remain limited to 30 minutes. Duplicate scheduled runs skip an existing edition.
This fallback still depends on GitHub scheduling and requires observation of
real morning delivery; it is not a guaranteed service-level commitment.

The workflow retrieves current sources through the OpenAI Responses API, validates the memo, preserves the previous public edition on failure, and deploys the successful result to GitHub Pages.

Generation retries transient API failures up to four total attempts, waiting 15,
30, and 60 seconds between attempts. SDK retries are disabled to avoid multiplying
requests, and each network operation has a five-minute timeout within a
24-minute generation step. Authentication, invalid requests, exhausted quota, and
memo validation failures stop immediately. Failed generation never replaces the
previous published memo. GitHub's scheduled start times can be delayed; this retry
policy does not guarantee a publication deadline.

Run the regression tests without making live API requests:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
```
