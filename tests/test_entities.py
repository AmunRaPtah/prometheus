"""Entity graph: pure-function tests + LLM mocked so no real endpoint calls (offline)."""

from __future__ import annotations

import seed

from prometheus import corpus, entities


# ---- pure functions, no DB/mock ----
def test_norm_collapses_punctuation_and_case():
    assert entities._norm("OpenAI, Inc.") == "openai inc"
    assert entities._norm("  Post-Quantum  Crypto ") == "post quantum crypto"
    assert entities._norm("") is None
    assert entities._norm(None) is None


def test_extract_cves_dedupes_and_uppercases():
    text = "Affected by cve-2023-12345 and CVE-2023-12345, also CVE-2021-9999."
    out = entities.extract_cves(text)
    mentions = {m["mention"] for m in out}
    assert mentions == {"CVE-2023-12345", "CVE-2021-9999"}
    assert all(m["type"] == "vulnerability" for m in out)


def test_extract_cves_none_found():
    assert entities.extract_cves("nothing here") == []


def test_parse_json_array_handles_fenced_output():
    raw = 'Sure, here is the JSON:\n```json\n[{"type": "technology", "mention": "x", "canonical": "X"}]\n```'
    items = entities._parse_json_array(raw)
    assert items == [{"type": "technology", "mention": "x", "canonical": "X"}]


def test_parse_json_array_bad_json_returns_empty():
    assert entities._parse_json_array("not json at all") == []


def test_parse_json_array_non_list_returns_empty():
    assert entities._parse_json_array('{"not": "a list"}') == []


# ---- extract_document, LLM mocked at the module boundary ----
def test_extract_document_merges_llm_and_cve(monkeypatch):
    monkeypatch.setattr(entities.local_llm, "complete", lambda *a, **k: (
        '[{"type": "technology", "mention": "post-quantum crypto", '
        '"canonical": "Post-Quantum Cryptography"}]'))
    out = entities.extract_document("Title mentions CVE-2024-0001", "Abstract text.")
    types = {m["type"] for m in out}
    assert types == {"technology", "vulnerability"}
    assert any(m["mention"] == "CVE-2024-0001" for m in out)
    assert any(m["canonical"] == "Post-Quantum Cryptography" for m in out)


def test_extract_document_drops_unknown_types(monkeypatch):
    monkeypatch.setattr(entities.local_llm, "complete", lambda *a, **k: (
        '[{"type": "person", "mention": "Jane Doe", "canonical": "Jane Doe"},'
        ' {"type": "technology", "mention": "x", "canonical": "X"}]'))
    out = entities.extract_document("t", "a")
    assert len(out) == 1 and out[0]["canonical"] == "X"


def test_extract_document_llm_unavailable_falls_back_to_cve_only(monkeypatch):
    def _raise(*a, **k):
        raise entities.local_llm.LocalLLMUnavailable("no endpoint")
    monkeypatch.setattr(entities.local_llm, "complete", _raise)
    out = entities.extract_document("CVE-2024-0001 found", "abstract")
    assert out == [{"type": "vulnerability", "mention": "CVE-2024-0001",
                    "canonical": "CVE-2024-0001"}]


# ---- build()/report()/explore(), real DuckDB, LLM mocked ----
def _seed_two_docs(con):
    seed.seed_document("PMC1", title="A survey of post-quantum cryptography",
                       abstract="We review lattice-based schemes from OpenAI and NIST.")
    seed.seed_document("PMC2", title="Exploiting CVE-2024-0001 in the wild",
                       abstract="A vulnerability in a widely used library.")
    corpus.build(con)


def test_build_extracts_and_rolls_up(con, env, monkeypatch):
    calls = []

    def _fake_complete(prompt, **k):
        calls.append(prompt)
        if "post-quantum" in prompt.lower():
            return ('[{"type": "technology", "mention": "post-quantum cryptography", '
                    '"canonical": "Post-Quantum Cryptography"},'
                    '{"type": "organization", "mention": "OpenAI", "canonical": "OpenAI"}]')
        return "[]"

    monkeypatch.setattr(entities.local_llm, "complete", _fake_complete)
    _seed_two_docs(con)
    counts = entities.build(con)

    assert counts["extracted_docs"] == 2
    assert len(calls) == 2  # one LLM call per document
    assert counts["mentions"] == 3  # 2 LLM entities + 1 CVE
    ent_types = {r[0] for r in con.execute("SELECT entity_type FROM entities").fetchall()}
    assert ent_types == {"technology", "organization", "vulnerability"}
    cve = con.execute(
        "SELECT n_documents FROM entities WHERE entity_type='vulnerability'").fetchone()
    assert cve[0] == 1


def test_build_is_incremental(con, env, monkeypatch):
    monkeypatch.setattr(entities.local_llm, "complete", lambda *a, **k: "[]")
    _seed_two_docs(con)
    entities.build(con)
    calls = []
    monkeypatch.setattr(entities.local_llm, "complete",
                        lambda *a, **k: calls.append(1) or "[]")
    counts = entities.build(con)  # nothing new to extract
    assert counts["extracted_docs"] == 0 and not calls


def test_explore_finds_entity_by_display_name(con, env, monkeypatch):
    monkeypatch.setattr(entities.local_llm, "complete", lambda *a, **k: (
        '[{"type": "organization", "mention": "the Agency", "canonical": "NSA"}]'))
    seed.seed_document("PMC1", title="Signals research", abstract="Work at the Agency.")
    corpus.build(con)
    entities.build(con)
    row = con.execute("SELECT n_documents FROM entities WHERE display_name='NSA'").fetchone()
    assert row and row[0] == 1
    entities.explore("NSA", con=con)  # smoke test: must not raise
    entities.report(con=con)  # smoke test: must not raise
