# Isolated HK/China memo experiment

V2 is a separate reviewer workspace and private research experiment. It cannot publish the production memo. V1 remains at the existing URL with its existing schedule, generation, validation and files. The earlier experimental quality branch is not part of this release.

## Included

- `docs/v2/`: select, reorder and copy public news with source links; authenticated explicit used/not-relevant/undo feedback; offline queue, idempotent retry and visible unsaved state. Unselected items remain unknown. Copy without “mark used” does not create a label.
- Private SQLite development store, dedicated Supabase migration/Edge endpoint, separate reviewer and CI tokens, versioned story/edition identities, immutable feedback events, and semantic history retrieval.
- Actual MCP read-only history tools and a checkpointed LangGraph research process. Fresh evidence is assembled before English drafting, independently reviewed, and checked against stable blocking rules. History informs ranking and repetition only. Model-based factual review is fallible; passing software checks does not establish editorial acceptance.
- Local email comparison/import, with explicit provenance, conservative match proposals, and no silent conversion of omissions into negative labels or automatic production-prompt rewriting.

## Current acceptance boundary

The companion and research code run locally. Cloud deployment, real embedding indexing, live source coverage and on-time shadow generation require dedicated infrastructure and an actual acceptance run. Research is disabled unless `V2_ENABLED=true`; the independent reviewer refresh is disabled unless `V2_FEEDBACK_ENABLED=true`. Do not enable it merely because fixture tests pass. No production promotion is automatic.

## Local review

Create an isolated Python environment and install `shadow_v2/requirements.txt`. From the repository root:

```sh
python -m unittest discover -s shadow_v2/tests -p 'test_*.py'
npm ci --prefix shadow_v2 --ignore-scripts
node --test shadow_v2/tests/*.mjs
python -m shadow_v2.preview --private-dir /absolute/private/v2-preview
```

Open the printed loopback URL for a read-only preview. The private reviewer URL is saved in a permissions-restricted file inside that private directory; it is never printed. Its token is revoked when the preview stops normally. Private state must be outside this public repository. This preview serves an explicit file allowlist, binds only to loopback, and is not a cloud server.

Fixture research uses real graph/checkpoint/MCP machinery with explicitly synthetic evidence, no external API calls, and no publication:

```sh
python -m shadow_v2.run --fixture --store /absolute/private/v2.db --output-dir /absolute/private/runs
python -m shadow_v2.run --fixture --case failed --store /absolute/private/v2.db --output-dir /absolute/private/runs
python -m shadow_v2.run --fixture --case repaired --store /absolute/private/v2.db --output-dir /absolute/private/runs
```

The failed case must return a nonzero exit code and persist a rejected result. Fixture approval means the fixture passed the policy, not that live news was checked.

## Dedicated cloud activation

1. Create a new Supabase project for this product's v2 only. Apply and test [the private backend](backend/README.md). No v1/shared database, credentials or tables are reused.
2. Provision independently revocable reviewer and CI tokens. Put only their hashes in the database. Store server/service credentials exclusively in the Edge runtime. Reviewer links use `#review=…`, never a query-string token. No emails or private research go into GitHub Pages or Actions artifacts.
3. Configure the separate `hk-memo-shadow-v2` and `hk-memo-v2-feedback` GitHub environments with `V2_BACKEND_URL`, `V2_CI_TOKEN`, and a dedicated `V2_OPENAI_API_KEY` from a separate OpenAI project with its own spending/rate controls. The job has repository read permission and no Pages/deployment permission. Do not grant it v1's credentials.
4. Configure `V2_RATE_CARD` for the chosen model using currently verified prices and explicit context/output/search/embedding ceilings required by the runner. The default model is `gpt-5.6-sol`; the system will not silently select a cheaper model. Recorded dollar amounts are rate-card estimates, not invoices. Start with manual live runs while the schedule stays disabled.
5. Refresh the current public edition with `python -m shadow_v2.sync_public`. It requires the public receipt, public Markdown and fresh checkout to agree; failure preserves the previous private edition. For a one-off historical import from the public repository, use `python -m shadow_v2.ingest --public-archive memos --cloud --max-editions 100`. This imports unlabeled history and does not prove when a reader could access it. Run `sync_public` again after the historical import so the reviewer uses the verified current revision. Build the registered history's semantic index explicitly with `python -m shadow_v2.index_history --cloud --output-dir /absolute/private/index --rate-usd-per-million VERIFIED_RATE --budget-usd 1 --max-items 200`. The incremental index skips existing vectors with the same body, model and version, and saves its usage estimate privately. Run additional bounded batches only after checking usage; each invocation is capped at 200 items. Imports alone do not call an embedding API; empty history must not be described as working personalized retrieval.
6. Set `docs/v2/config.json`'s `apiBase` to the dedicated Edge endpoint (not a secret), test actual cross-origin review/undo/revocation/offline recovery, and separately publish the companion path as static assets. The v2 workflow cannot deploy Pages. Any static companion release must preserve the production homepage and archive.
7. After the backend and feedback tests pass, enable `V2_FEEDBACK_ENABLED=true`. Its separate workflow refreshes the reviewer after each successful production workflow and indexes registered new stories within a separate $1 estimated budget. It never delays or changes production. Run the refresh manually after initial activation; investigate failures in Actions.
8. Run `python -m shadow_v2.run --live --cloud --output-dir /absolute/private/runs --budget-usd 10 --deadline-seconds 1320` with `V2_ENABLE_LIVE=1`. Inspect private evidence, failed leads, English claim checks, time and usage. Keep rejected runs in the comparison. Only after cloud tests and live acceptance enable repository variable `V2_ENABLED=true` for the isolated schedule.

Scheduled job success/failure is visible in Actions and subject to the owner's GitHub notification preferences; no separate human alert channel has been configured. GitHub cron can be delayed. This workflow does not guarantee a delivery deadline and cannot repair/replace v1. Measure current-date public availability independently and report missed deadlines even if a later retry succeeds.

## Evaluation and retirement

Keep the exact dated v1 and v2 snapshots, cutoffs, generation duration and public verification evidence. Compare source-available relevant stories, critical-fact accuracy, ordering, unedited copy rate and editing time. Unavailable adoption metrics stay unknown. A historical overlap does not prove a reviewer used an edition published after their email. The first formal preference review needs at least 20 labeled trading editions and 100 explicit events; the current historic corpus does not substitute for forward feedback.

The private prospective evaluator accepts an operator-exported snapshot; no automatic feedback export or live adoption measurement is claimed:

```sh
python -m shadow_v2.evaluate --snapshot /absolute/private/evaluation-input.json --output-dir /absolute/private/evaluation
```

The snapshot contains `ranked_item_ids`, plus `feedback_events` with `event_id`, ordered `server_sequence`, `item_id`, `edition_date`, `label` (`used`, `not_relevant`, `cleared`) and `provenance=explicit_feedback`. Scope the export to the intended reviewer. Optional `reviewed_v1_matches` require an explicit `confirmed` flag and both story IDs. Optional `reviewed_checks` contain reviewed boolean values or nulls for stale/repeated stories, citation support, retrieval relevance and unedited copying. Runtime needs timezone-aware `started_at` and `finished_at`; cost, editing time and `independent_on_time_observation` must come from observed records. Missing judgments remain unknown, precision is withheld when labels are incomplete, and an eligible formal review never authorizes promotion.

To retire v2, set `V2_ENABLED=false` and `V2_FEEDBACK_ENABLED=false`, disable both workflows, revoke its CI/reviewer/OpenAI credentials, and optionally remove `docs/v2/` and the dedicated backend after privately exporting data you need. No v1 rollback is needed because this release does not replace v1. Production promotion requires a separate explicit decision.
