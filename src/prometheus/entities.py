"""Entity extraction + graph -- prometheus's own link layer, LLM-driven.

Unlike aqueduct's drug/protein graph (resolved against ChEMBL/UniProt registries),
prometheus has no canonical ID source for the entities that matter here
(technologies, organizations, vulnerabilities, methods) -- so entities are extracted
directly from each document's title+abstract via a local LLM (`local_llm.py`), plus a
deterministic CVE-ID regex pass (no model needed, and a built-in quality anchor to
sanity-check the LLM-extracted types against).

Because extraction tags each document directly (rather than aqueduct's approach of
resolving a registry, then regex-matching it back across the whole corpus), the graph
falls out of the mentions table directly -- no word-boundary matching machinery needed.

  doc_entity_mentions   one row per extracted mention (bronze)
  entities              canonical entity rollup (type, display name, counts)
  link_entity_document  entity <-> paper, with mention count

Local-only: run via `prometheus entities build` on a box with llama-swap reachable
(see scripts/sync-local.sh). Not wired into `harvest.py` -- GitHub Actions runners
have no route to this box's local model server.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import duckdb

from . import local_llm, obs
from .storage import connect

ENTITY_TYPES = ("technology", "organization", "vulnerability", "method")

_CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)

_SYSTEM = (
    "You extract named entities from academic paper title/abstracts in technology, "
    "security, and frontier-science research. Output ONLY a JSON array, no prose. "
    'Each item: {"type": one of "technology"|"organization"|"method", '
    '"mention": exact text span from the input, "canonical": a normalized display '
    "name (e.g. expand acronyms you recognize, fix casing)}. Only extract concrete "
    "named technologies, organizations, or techniques/methods -- skip generic terms, "
    "author names, and vague concepts. Return [] if none. Do not extract "
    "vulnerability/CVE identifiers -- those are handled separately."
)


def _prompt(title: str, abstract: str) -> str:
    return f"Title: {title}\nAbstract: {abstract}"


def _norm(name: str) -> str | None:
    """Canonical join key: lowercased, punctuation collapsed to single spaces."""
    if not name:
        return None
    n = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return n or None


def extract_cves(text: str) -> list[dict]:
    """Deterministic CVE-ID extraction -- no LLM, a quality anchor for the LLM path."""
    return [{"type": "vulnerability", "mention": m, "canonical": m}
            for m in dict.fromkeys(x.upper() for x in _CVE.findall(text or ""))]


def extract_document(title: str, abstract: str, *, model: str | None = None) -> list[dict]:
    """One LLM call + a CVE regex pass.

    Never raises -- a bad document (malformed model output, endpoint down) shouldn't
    stop a `build()` run over thousands of others; it just yields fewer mentions.
    """
    text = f"{title or ''}\n{abstract or ''}"
    out = extract_cves(text)
    try:
        raw = local_llm.complete(_prompt(title or "", abstract or ""), system=_SYSTEM,
                                 model=model, max_tokens=500)
    except local_llm.LocalLLMUnavailable as e:
        obs.log("entities.extract.unavailable", error=str(e))
        return out
    items = _parse_json_array(raw)
    for it in items:
        if not isinstance(it, dict):
            continue
        etype = it.get("type")
        mention = (it.get("mention") or "").strip()
        canonical = (it.get("canonical") or mention).strip()
        if etype in ENTITY_TYPES and etype != "vulnerability" and mention and canonical:
            out.append({"type": etype, "mention": mention, "canonical": canonical})
    return out


def _parse_json_array(raw: str) -> list:
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # small local models occasionally wrap JSON in prose/fences despite instructions
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            obs.log("entities.extract.bad_json", raw=raw[:200])
            return []
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            obs.log("entities.extract.bad_json", raw=raw[:200])
            return []
    return items if isinstance(items, list) else []


def build(con: duckdb.DuckDBPyConnection | None = None,
         *, model: str | None = None) -> dict[str, int]:
    """Extract entities from every not-yet-processed document, then rebuild the graph.

    Incremental: only documents absent from `doc_entity_mentions` are (re-)extracted,
    mirroring `embeddings.py`'s skip-unchanged-work pattern at document granularity.
    """
    owns = con is None
    con = con or connect()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS doc_entity_mentions (
                pmcid TEXT, entity_type TEXT, mention_text TEXT,
                canonical_name TEXT, entity_norm TEXT, extracted_at TEXT
            )
        """)
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "documents_raw" not in tables:
            print("[entities] no documents_raw -- run `corpus build` first.")
            return {"extracted_docs": 0, "mentions": 0}

        pending = con.execute("""
            SELECT d.pmcid, d.title, d.abstract FROM documents_raw d
            WHERE d.pmcid NOT IN (SELECT DISTINCT pmcid FROM doc_entity_mentions)
        """).fetchall()

        n_docs = 0
        n_mentions = 0
        now = datetime.now(timezone.utc).isoformat()
        with obs.span("entities.build", pending=len(pending)):
            for pmcid, title, abstract in pending:
                mentions = extract_document(title, abstract, model=model)
                n_docs += 1
                if not mentions:
                    # Still mark the doc as processed -- an empty extraction is a
                    # valid outcome (e.g. nothing worth tagging). Without a placeholder
                    # row this pmcid would be re-attempted (and re-billed) every run.
                    con.execute(
                        "INSERT INTO doc_entity_mentions VALUES (?, NULL, NULL, NULL, NULL, ?)",
                        [pmcid, now])
                    continue
                for m in mentions:
                    norm = m["canonical"] if m["type"] == "vulnerability" else _norm(m["canonical"])
                    con.execute(
                        "INSERT INTO doc_entity_mentions VALUES (?, ?, ?, ?, ?, ?)",
                        [pmcid, m["type"], m["mention"], m["canonical"], norm, now])
                    n_mentions += 1

        _rebuild_rollups(con)
        counts = {
            "extracted_docs": n_docs, "mentions": n_mentions,
            "entities": con.execute("SELECT count(*) FROM entities").fetchone()[0],
            "links": con.execute("SELECT count(*) FROM link_entity_document").fetchone()[0],
        }
        print(f"[entities] extracted {n_docs} docs -> {n_mentions} mentions -> "
              f"{counts['entities']} entities, {counts['links']} document links")
        return counts
    finally:
        if owns:
            con.close()


def _rebuild_rollups(con: duckdb.DuckDBPyConnection) -> None:
    """Roll `doc_entity_mentions` up into `entities` + `link_entity_document`."""
    con.execute("""
        CREATE OR REPLACE TABLE entities AS
        SELECT entity_norm, entity_type,
               arg_max(canonical_name, len(canonical_name)) AS display_name,
               count(*) AS n_mentions, count(DISTINCT pmcid) AS n_documents
        FROM doc_entity_mentions
        WHERE entity_norm IS NOT NULL
        GROUP BY entity_norm, entity_type
    """)
    con.execute("""
        CREATE OR REPLACE TABLE link_entity_document AS
        SELECT entity_norm, entity_type, pmcid, count(*) AS n_mentions
        FROM doc_entity_mentions
        WHERE entity_norm IS NOT NULL
        GROUP BY entity_norm, entity_type, pmcid
    """)


def report(con: duckdb.DuckDBPyConnection | None = None) -> None:
    owns = con is None
    con = con or connect()
    try:
        if "entities" not in {r[0] for r in con.execute("SHOW TABLES").fetchall()}:
            print("No entities built yet -- run `entities build`.")
            return
        print("\n========== Entity graph ==========\n")
        rows = con.execute("""
            SELECT entity_type, display_name, n_documents, n_mentions
            FROM entities ORDER BY n_documents DESC, n_mentions DESC LIMIT 20
        """).fetchall()
        print(f"{'type':13} {'entity':40} {'docs':>5} {'mentions':>9}")
        print("-" * 72)
        for etype, name, ndoc, nmen in rows:
            print(f"{etype:13} {(name or '')[:40]:40} {ndoc:5} {nmen:9}")
        by_type = con.execute(
            "SELECT entity_type, count(*) FROM entities GROUP BY entity_type ORDER BY 1"
        ).fetchall()
        print("\nBy type: " + ", ".join(f"{t}={n}" for t, n in by_type))
        print("\n===================================\n")
    finally:
        if owns:
            con.close()


def explore(name: str, con: duckdb.DuckDBPyConnection | None = None) -> None:
    """Show every document linked to one entity, by mention count."""
    owns = con is None
    con = con or connect()
    try:
        candidates = list(dict.fromkeys(
            c for c in (_norm(name), name.strip(), name.strip().upper()) if c))
        placeholders = ",".join("?" for _ in candidates)
        ent = con.execute(
            f"SELECT entity_norm, entity_type, display_name, n_mentions, n_documents "
            f"FROM entities WHERE entity_norm IN ({placeholders}) "
            f"ORDER BY n_documents DESC LIMIT 1",
            candidates,
        ).fetchone()
        if not ent:
            print(f"No entity matching {name!r}.")
            return
        norm, etype, display, nmen, ndoc = ent
        print(f"\n=== {display}  ({etype}) ===")
        print(f"  {nmen} mentions across {ndoc} documents")
        docs = con.execute("""
            SELECT d.pmcid, d.source, l.n_mentions, d.title
            FROM link_entity_document l JOIN documents_raw d USING (pmcid)
            WHERE l.entity_norm = ? AND l.entity_type = ?
            ORDER BY l.n_mentions DESC LIMIT 12
        """, [norm, etype]).fetchall()
        print(f"\nDocuments ({len(docs)} shown):")
        for pmcid, source, n, title in docs:
            print(f"  {pmcid} [{source}] (x{n})  {(title or '')[:56]}")
        print()
    finally:
        if owns:
            con.close()
