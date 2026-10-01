# HK/China Memo Shadow V2 Design

**Date:** 2026-09-07
**Status:** Approved for implementation planning
**Product:** HK/China Pre-Market Memo (`cloud-github`)
**Out of scope:** Market Memo Beta

## 1. Objective

Build a shadow v2 of the existing HK/China memo that learns from the reviewer's story-selection behavior and supports later retrospective analysis of her final memos. V2 must demonstrate embeddings, vector retrieval-augmented generation (RAG), Model Context Protocol (MCP), and LangGraph through genuine product functions rather than technology wrappers.

The existing v1 is a functioning production product. V2 must not change v1 generation, validation, scheduling, publishing, URLs, archives, or output files. V1 remains the only production publisher unless the user later authorizes a separate promotion decision.

## 2. Non-negotiable isolation and retirement guarantees

V2 must satisfy all of the following:

1. V1's existing workflow and scripts continue to run without depending on v2.
2. V2 has a separate scheduled workflow, secrets, storage tables, budget limit, logs, and failure notifications.
3. V2 never writes to `memos/`, `docs/index.html`, or `docs/archive/`.
4. V2 outputs go only to a separate shadow-run store and an isolated reviewer companion page.
5. Failure, timeout, quota exhaustion, invalid output, or backend unavailability in v2 cannot block or delay v1.
6. V2 has no automatic promotion path. Metrics may recommend a decision, but only the user can authorize any production cutover.
7. Retirement consists of disabling the v2 workflow, revoking its credentials, and optionally deleting its companion page and backend resources. No rollback of v1 is required.

## 3. Current-state model

V1 operates as follows:

```text
Daily trigger
-> live web research through the OpenAI API
-> prompt containing the reviewer's source, format, watchlist, and relevance preferences
-> memo generation
-> deterministic validation
-> publication to the public GitHub Pages website
-> Reviewer manually copies useful items into her separate final memo
```

the reviewer's selection is human-in-the-loop behavior, but v1 does not capture or learn from it.

## 4. Rollout phases

### Phase A: Isolated feedback capture

Create a reviewer companion page under a separate v2 path. The public v1 homepage remains unchanged. Reviewer receives a private URL containing a reviewer credential in the URL fragment, for example:

```text
https://theerictang.github.io/hk-china-pre-market-memo/v2/#review=<private-token>
```

The fragment is not sent to GitHub Pages. Client-side code uses it only when calling the feedback API over HTTPS.

The companion page mirrors the current published v1 edition and offers three item states:

- **Copy & mark used:** copies the story and records a strong positive label.
- **Not relevant:** records an explicit negative label.
- **Unlabeled:** the default state; absence of selection is not treated as negative.

An undo action returns an item to unlabeled. The page displays local pending, saved, and failed states so Reviewer can see whether feedback synchronized.

### Phase B: Historical memory and shadow generation

Index the public v1 archive at story level. Existing archive items begin as unlabeled historical context and may be used for continuity and duplicate detection, but not as evidence of the reviewer's preferences.

Run a LangGraph v2 workflow in shadow mode. It retrieves related historical stories and accumulated explicit feedback, performs fresh web research, ranks candidates, validates the draft, and stores a private shadow output. It cannot publish to v1.

### Phase C: Retrospective Reviewer-memo import

When the user supplies the reviewer's final memos, match each final memo to the corresponding v1 edition by date. Matching produces confidence-scored candidate relationships:

- exact or near-exact retained item;
- materially rewritten retained item;
- omitted or unmatched item;
- Reviewer-only item not present in v1.

Only retained matches are automatic strong positives. Omission remains an unknown/weak signal unless corroborated by the reviewer's explicit `not_relevant` feedback. Low-confidence matches require review and are never silently converted into labels.

The retrospective analysis generates a versioned preference report and proposed prompt changes. It does not rewrite the production v1 prompt automatically.

### Phase D: Evaluation and decision

Compare v2 with the unchanged v1. V2 remains shadow-only regardless of evaluation results. The user may retire it, continue collecting data, revise it, or separately approve a future promotion.

## 5. Architecture

```text
                         PRODUCTION V1 (unchanged)
GitHub schedule -> v1 research/generation -> v1 validation -> public v1 site
                                                       |
                                                       | read-only mirror
                                                       v
                                            v2 reviewer companion
                                                       |
                                        explicit Reviewer feedback
                                                       v
                                           dedicated feedback API
                                                       |
                                                       v
                                             dedicated v2 database

                         SHADOW V2 (isolated)
Separate schedule -> LangGraph workflow -> MCP retrieval tools
                          |                       |
                          |                       v
                          |            archive + labels + preferences
                          v
                   live web research
                          |
                          v
              rank / draft / validate / evaluate
                          |
                          v
                 private shadow-run storage
```

The recommended backend is a dedicated Supabase project owned by the HK/China product. It is not connected to Market Memo Beta. Supabase provides Postgres for structured feedback, a server-side function for token validation, and pgvector for the later embedding index.

## 6. Data model

### `memo_editions`

- `id`
- `edition_date`
- `research_cutoff`
- `source_version`
- `prompt_version`
- `created_at`

### `memo_items`

- `id`
- `edition_id`
- `position`
- `headline`
- `body`
- `source_urls`
- `companies`
- `tickers`
- `sectors`
- `topics`
- `content_hash`
- `created_at`

Item IDs are deterministic from edition date, normalized content, and source URLs. A separate content hash supports detection of content edits and repeated stories.

### `feedback_events`

- `id`
- `item_id`
- `reviewer_id` (initially a fixed pseudonymous reviewer identifier for Reviewer)
- `label` (`used`, `not_relevant`, or `cleared`)
- `event_time`
- `client_event_id` for idempotency

Events are append-only. The effective current label is derived from the latest valid event, preserving an audit trail and undo history.

### `memo_item_embeddings`

- `item_id`
- `embedding_model`
- `embedding_version`
- `embedding`
- `embedded_text_hash`
- `created_at`

### `preference_profiles`

- `id`
- `version`
- `evidence_window`
- `profile_json`
- `proposed_prompt_changes`
- `created_at`
- `approved_for_experiment`

### `shadow_runs`

- `id`
- `edition_date`
- `graph_version`
- `prompt_version`
- `retrieval_version`
- `status`
- `output_json`
- `validation_json`
- `evaluation_json`
- `usage_json`
- `created_at`

## 7. Feedback API and security

The static site never receives a database service credential. A dedicated server-side endpoint performs all writes.

Security controls:

1. The reviewer token is generated randomly, stored only as a server-side hash, and supplied to Reviewer through a private URL fragment.
2. The token is revocable and replaceable without changing v1.
3. The endpoint accepts requests only over HTTPS and applies origin checks and rate limits.
4. Feedback writes use idempotency keys to avoid duplicate events when the browser retries.
5. A distinct CI credential registers editions and reads feedback for v2. the reviewer's token cannot invoke CI or administrative operations.
6. No confidential desk memo or internal desk material is made public. Retrospective files are processed only in an explicitly approved private environment.
7. Logs exclude raw credentials and minimize copied memo content.

Because the link is a bearer credential rather than full identity authentication, the UI describes it as a private reviewer link, not as secure user login.

## 8. Embeddings and vector RAG

The retrieval unit is one memo story, not an arbitrary fixed-length chunk. The embedded representation combines the headline, body, companies, sectors, and topics. Source URLs and dates remain metadata rather than semantic text.

For each current candidate, v2 retrieves:

1. semantically similar prior stories;
2. explicit labels on those stories;
3. recent coverage of the same company, sector, or narrative;
4. relevant approved preference-profile statements.

Retrieval uses metadata filters and recency-aware scoring. Explicit `used` and `not_relevant` labels influence experimental ranking. Unlabeled and historically omitted items do not become negative examples.

Retrieved history is used for preference, continuity, and duplicate detection. It is not treated as proof of current facts. Current claims still require fresh, direct source citations from the live research step.

## 9. MCP boundary

V2 exposes narrow, read-only MCP tools:

- `search_memo_history(query, date_from, date_to, tickers, topics, limit)`
- `get_preference_profile(version)`
- `get_item_feedback(item_ids)`
- `check_recent_coverage(query, lookback_days)`

MCP provides a stable contract between orchestration and retrieval. It does not expose publication, workflow administration, arbitrary SQL, or raw secrets. Tool inputs and outputs use explicit schemas and are recorded in shadow-run traces.

The MCP server runs only for v2. If it is unavailable, v2 fails or records a retrieval-disabled experimental run; v1 is unaffected.

## 10. LangGraph workflow

V2 uses explicit state containing the edition date, cutoff, configuration versions, retrieved context, candidate stories, validation results, evaluation results, usage, and errors.

Nodes:

1. `snapshot_inputs`
2. `load_preferences`
3. `retrieve_history_via_mcp`
4. `research_current_sources`
5. `generate_candidates`
6. `rank_and_deduplicate`
7. `draft_shadow_memo`
8. `validate_sources_and_schema`
9. `evaluate_against_policy`
10. `persist_shadow_run`

Conditional edges permit one budget-bounded retry for correctable research, drafting, or validation failures. Non-correctable failures terminate the shadow run with structured diagnostics. There is no publication node.

Checkpointing allows inspection and replay of v2 without coupling its state to v1. Every run records graph, prompt, retrieval, and embedding versions so results remain reproducible.

## 11. Evaluation

V1 is the frozen operational baseline. Evaluations are matched by edition date and research cutoff where possible.

Primary measures:

- used-item precision among the first 5 and first 10 stories;
- explicit `not_relevant` rate among the first 5 and first 10 stories;
- rank assigned by v2 to stories Reviewer used from v1;
- repeated or stale story rate;
- citation presence, validity, and freshness pass rate;
- generation cost and wall-clock runtime;
- retrieval usefulness, measured by whether retrieved stories are judged related to the candidate.

The first formal review occurs after at least 20 labeled trading-day editions or 100 explicit feedback events, whichever occurs later. Historical matched memos may supplement this dataset but do not remove the requirement for forward explicit feedback.

No metric automatically promotes v2. Results must include failures and neutral findings; resume or interview claims use only measured outcomes.

## 12. Failure handling and observability

- V2 has independent timeouts, concurrency controls, and a per-run cost ceiling.
- V2 failures produce a structured terminal state and diagnostic artifact.
- The workflow does not retry indefinitely.
- Feedback events queue locally during brief network failures and retry idempotently; the UI shows unsynchronized state.
- Malformed or unauthenticated feedback is rejected without exposing whether a specific item exists.
- Embedding-model changes create a new embedding version rather than silently mixing incompatible vectors.
- Prompt, tool, retrieval, token, latency, validation, and error metadata are recorded for each shadow run.
- A v2 kill switch disables its schedule and API access without touching v1.

## 13. Testing and verification

### Isolation tests

- Compare v1 workflow and production-file hashes before and after v2 installation.
- Assert v2 code has no permitted write path to v1 memo or public-index locations.
- Simulate every v2 dependency failing and verify the v1 workflow still succeeds independently.

### Feedback tests

- Token rejection, rotation, and revocation.
- `used`, `not_relevant`, undo, duplicate submission, offline retry, and stale-edition behavior.
- Clipboard failure must not falsely record `used`.
- Public visitors without the private fragment cannot see reviewer controls or write feedback.

### Retrieval tests

- Known semantic matches, metadata filters, recency ranking, duplicate detection, and embedding-version separation.
- Unlabeled omissions never appear as negative labels.
- Retrieved archive content cannot replace current-source verification.

### Workflow tests

- Deterministic node tests with model and MCP fixtures.
- Conditional retry and budget termination.
- Checkpoint resume and reproducible version metadata.
- No graph path reaches a production publishing function.

## 14. Deliverables

1. Isolated v2 reviewer companion page.
2. Dedicated feedback API and database migration files.
3. Archive ingestion and stable item-ID tooling.
4. Embedding index and retrieval tests.
5. Read-only MCP server and contract tests.
6. LangGraph shadow workflow with checkpointing and cost controls.
7. Private v1-versus-v2 comparison report.
8. Historical Reviewer-memo importer and comparison report after the files are supplied.
9. Operator runbook covering token rotation, kill switch, costs, and retirement.

## 15. Explicitly deferred decisions

These are not implementation blockers and do not weaken isolation:

- Production promotion criteria beyond the mandatory human decision.
- Any replacement of v1's prompt or generation workflow.
- Any use of confidential desk sources or non-public data.
- Additional reviewers or role-based access control.

The system is intentionally designed so these can be considered later without changing v1.
