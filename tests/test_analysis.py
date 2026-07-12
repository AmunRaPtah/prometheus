"""Quantitative analysis library (offline).

The drug/protein graph metrics (top_drugs/top_targets/gaps/asymmetries) are guarded
by `_has(con, ...)` table-presence checks and degrade gracefully to empty results now
that nothing builds `entity_drugs`/`link_drug_*` (the pharma-specific `links.py` graph
was retired -- see entities.py for prometheus's own tech/org/vuln graph). Kept here as
regression coverage that the guarded paths stay harmless with those tables absent,
matching prometheus's actual production state (they were always empty in practice).
"""

from __future__ import annotations

import seed

from prometheus import analysis, corpus, datasets


def _graph(con):
    seed.seed_document("PMC1", source="europepmc", doi="10.1/a",
                       title="Fentanyl and the mu receptor",
                       abstract="Fentanyl is a mu-opioid receptor agonist.",
                       sections=[("Body", "Duragesic delivers fentanyl. " * 6)])
    seed.seed_document("openalex:W1", source="openalex", doi="10.1/a",  # cross-source dup
                       title="Fentanyl and the mu receptor", keywords="Pharmacology; Chemistry")
    corpus.build(con)
    seed.seed_chembl(); seed.seed_clinicaltrials(); seed.seed_uniprot()
    seed.seed_pdb()
    datasets.build(con)


def test_overview_counts_unique_papers(con):
    _graph(con)
    o = analysis.overview(con)
    assert o["source_rows"] == 2 and o["unique_papers"] == 1   # deduped by DOI
    assert o["cross_source_dupes"] == 1


def test_drug_graph_metrics_empty_without_link_tables(con):
    _graph(con)
    assert analysis.top_drugs(con) == []
    assert analysis.top_targets(con) == []
    assert analysis.gaps(con) == {}


def test_facts_and_sheet(con):
    _graph(con)
    f = analysis.facts(con)
    assert set(f) >= {"overview", "trends", "top_drugs", "top_targets", "gaps"}
    sheet = analysis.facts_sheet(con)
    assert "Prometheus facts" in sheet
    assert "Top drugs" not in sheet  # section omitted when there's nothing to show
