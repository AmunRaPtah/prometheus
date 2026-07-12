"""PubChem + Ensembl flatten tests (offline)."""

from __future__ import annotations

from prometheus.sources import ensembl, pubchem


def test_pubchem_flatten_types():
    p = {"CID": 5284596, "MolecularFormula": "C19H21NO4", "MolecularWeight": "327.4",
         "XLogP": 2.1, "InChIKey": "KEY-1", "IUPACName": "x"}
    f = pubchem._flatten(p, "naloxone")
    assert f["cid"] == 5284596 and f["mw"] == 327.4 and isinstance(f["mw"], float)
    assert f["inchi_key"] == "KEY-1"


def test_ensembl_flatten():
    d = {"id": "ENSG1", "biotype": "protein_coding", "seq_region_name": "6",
         "start": 1, "end": 9, "strand": 1, "description": "opioid receptor"}
    f = ensembl._flatten("OPRM1", d)
    assert f["gene"] == "OPRM1" and f["ensembl_id"] == "ENSG1" and f["chromosome"] == "6"
