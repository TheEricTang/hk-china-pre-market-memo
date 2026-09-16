# HK/China Pre-Market Memo

Public daily news dashboard generated at 06:10 Asia/Hong_Kong time.

The workflow retrieves current sources through the OpenAI Responses API, validates the memo, preserves the previous public edition on failure, and deploys the successful result to GitHub Pages.

Generation retries transient API failures up to four total attempts, waiting 15,
30, and 60 seconds between attempts. SDK retries are disabled to avoid multiplying
requests, and each network operation has a five-minute timeout within the existing
30-minute workflow limit. Authentication, invalid requests, exhausted quota, and
memo validation failures stop immediately. Failed generation never replaces the
previous published memo. GitHub's scheduled start times can be delayed; this retry
policy does not guarantee a publication deadline.

Run the regression tests without making live API requests:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
```
