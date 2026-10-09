# Isolated memo upgrade implementation

Implements the saved 7 September shadow-v2 design, informed by the private nine-email comparison and September delivery investigation. Current production baseline: `0a608cf`. The rejected `reliability-quality-delivery` experiment remains separate.

## Binding constraints

- V1 workflow, scripts, requirements, prompts, memo archives and public homepage remain byte-for-byte unchanged by this release. V2 has no production publication function. Market Memo Beta is out of scope.
- Research history informs preferences and duplicate checks, never current facts. Private emails, addresses, reviewer credentials and feedback never enter the public repository, logs or public artifacts.
- Unlabeled and omitted items are unknown. Only explicit feedback or confirmed retained matches create positive labels; no inferred negative labels.
- Current-source evidence, publication time, issuer, figure, unit, legal stage and attribution errors block acceptance. Optional writing preferences do not. A rejected candidate is stored privately as rejected, never described as approved.
- Preserve stable story identities and every discovered material lead across bounded correction; each must be retained or explicitly excluded with an evidence-based reason. No unconstrained rewrite/research retry loop.
- Cloud resources and credentials must be actually available before claiming cloud activation. Do not substitute a public Actions artifact for private storage. Local fixture tests do not prove live accuracy, adoption or future delivery.

## Task 1 — Delivery evidence (read-only)

Audit every HK trading date 18 September–1 October using generation and Pages deployment step timestamps, matching commits and public archives. Report target 07:30 and deadline 08:00 independently, preserve all failures and identify the limits of historical availability evidence. Store private report outside repository.

## Task 2 — Data, feedback and retrieval

Implement deterministic edition/item IDs, public archive ingestion, append-only idempotent feedback, reviewer token hashing/revocation/rotation, and a dedicated Supabase migration plus authenticated edge API. Provide a SQLite local backend for reproducible development. A bounded vector index must separate embedding model/version and support date/ticker/topic filters, recency and explicit feedback; expose the four planned read-only tools through real MCP. Indexing uses an explicit OpenAI embedding adapter, fixture vectors only in tests. Token-bearing links use fragments and feedback API never exposes administrator credentials.

## Task 3 — Evidence-first shadow graph

Implement actual LangGraph nodes with checkpointing, a real MCP client boundary, versioned configuration, bounded cost/time and at most one targeted correction. Research an eight-area source-backed inventory, independently verify fact cards before prose, rank using history/explicit labels, draft only verified facts and validate the final candidate. Structured deterministic blockers versus optional style suggestions. Preserve and reconcile discovered leads. Record failure and budget termination as private terminal runs. No production writer or publisher. Real OpenAI adapter plus offline fixture evaluation must exercise the same graph.

## Task 4 — Reviewer and retrospective evaluation

Build an isolated companion at `docs/v2/`: read-only mirror of public v1, individual/selectable/reordered rich/plain-text copy, explicit used/not-relevant/undo controls visible only with private reviewer link, idempotent offline queue with truthful saved/failed states, and stale-edition notice. Clipboard failure cannot record used. Private `.eml` importer strips headers/signatures, proposes matches with source/date provenance; uncertain or omitted matches remain unknown. Produce a private comparison and versioned proposed preferences without changing v1 prompts.

## Task 5 — Integration, isolation and operations

Separate shadow workflow with read-only repository permissions, separate secrets, independent concurrency, bounded timeout, explicit enable flag, private backend persistence and sanitized diagnostics only. Local demonstration and tests, authenticated backend tests where available, V1 hash comparison, independent code review, and operator guide for activation, reviewer token rotation, kill switch and retirement. Keep experimental generation off until credentials and real acceptance are verified. Record remaining external dependencies clearly.
