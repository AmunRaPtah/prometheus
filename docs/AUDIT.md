# Prometheus audit — findings & status

This file used to be aqueduct's `docs/AUDIT.md` copied verbatim (find-replace of the
package name only) — flagged as a stale-docs finding in the 2026-07-11 cross-repo
audit, since it described drug/protein matching, RxNorm/MeSH, and ChEMBL synonyms,
none of which apply to prometheus's tech/frontier-science domain. Replaced with an
accurate summary below.

## Hardening ported from aqueduct (verified 2026-07-11, still true)
Prometheus is a fork of aqueduct's corpus engine and inherited its resilience work
byte-for-byte (only naming differs): `net.py`'s per-host rate limiter + circuit
breaker + structured `TransientError`/`PermanentError`, the ingest-time quality gate
(`quality.py`, admission control with an auditable `documents_rejected` quarantine),
`embeddings.py`'s randomized-truncated-SVD LSA fit (avoids the full-SVD OOM aqueduct
hit in production), chunk-level metadata (`sec_kind`/IMRaD/`is_methods`/`is_results`),
index versioning with `corpus_hash` skip-if-unchanged, structured JSON logging
(`obs.py`), and harvest query-version tracking (`data/harvest_state.json`).

One gap found and fixed in the 2026-07-11 audit: `server.py`'s bearer-auth check used
a plain `==` string comparison on the API key (a timing side-channel), inherited
identically from aqueduct. Fixed to `hmac.compare_digest` in all three corpus-engine
repos (aqueduct, leviathan, prometheus) the same day.

## Retired: the pharma-specific link graph (2026-07-11)
`links.py`/`discover.py` — aqueduct's drug/trial/paper/protein graph (ChEMBL/UniProt
entity resolution, stereoisomer normalization, drug↔document confidence scoring) —
were inherited but never functional here: prometheus's `topics.json` `structured`
query lists were always empty, so nothing ever populated `entity_drugs`/`link_drug_*`.
Removed outright, along with the dependent `/discover` HTTP endpoint and the
`harvest.py` call. `analysis.py`'s drug/protein-graph metrics (`top_drugs`,
`top_targets`, `gaps`, `asymmetries`) and `rag.py`'s graph-context enrichment are
guarded by table-presence checks and degrade to empty results now that those tables
never get created — no behavior change from before (they were already always empty in
production), see `tests/test_analysis.py`/`tests/test_rag.py`.

## New: prometheus's own entity graph (2026-07-11)
`entities.py` replaces it with a graph suited to this domain: `technology` /
`organization` / `vulnerability` / `method` entities extracted from each document's
title+abstract via a local LLM (`local_llm.py`, llama-swap's OpenAI-compatible
endpoint on this box) plus a deterministic CVE-ID regex pass. Schema is one generic
`doc_entity_mentions` → `entities` → `link_entity_document` rollup rather than
per-type tables, since (unlike ChEMBL/UniProt) there's no canonical registry per
entity type here — every entity comes from the same extraction source. CLI:
`prometheus entities {build, report, explore}`.

**Local-only, deliberately not wired into `harvest.py`**: GitHub Actions runners have
no route to this box's `127.0.0.1:8080` llama-swap endpoint. Run via
`scripts/sync-local.sh pull && python -m prometheus entities build && scripts/sync-local.sh push`
on this box. Known unsolved risk: this races the nightly GH Actions harvest (06:00
UTC) against the same OneDrive state object with no cross-environment locking — avoid
running near that window.

Piloted here first; leviathan gets the same `local_llm.py`/`entities.py` pattern as a
near-mechanical port once this is validated for quality and cost.

**Cost validated (2026-07-12): not yet viable at this corpus's scale.** Measured
steady-state throughput on the live warehouse (2612-doc corpus, ~800-970 new docs/day):
~98s/doc — one sequential local-LLM call per document via llama-swap's
`granite-4.0-h-1b`. At that rate, just keeping up with one day's new documents takes
~24.5h of continuous processing, before touching the pre-existing backlog (~71h to
clear once). The pilot is correct and behind incremental-skip semantics (safe to
interrupt/resume), but throughput doesn't clear the bar for production use here, and
leviathan would hit the identical wall. **Do not port to leviathan** until this is
fixed — batched/concurrent local-LLM calls, a faster model, or scoping extraction to a
curated subset are the likely paths; unstarted as of this writing.
