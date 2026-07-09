# Prometheus

The **technology, mathematics, and frontier-science knowledge base** — a point-in-time
corpus of scholarly open-access literature at the edge of computing, security, and the
physical sciences.

*Named for the Titan who stole fire from the gods — frontier technology and the pursuit
of powerful knowledge.*

Sibling of [`aqueduct`](https://github.com/AmunRaPtah/aqueduct) (the life-science
knowledge base) and [`numeraire`](https://github.com/AmunRaPtah/numeraire) (the
financial one) — **same proven corpus framework, deliberately separate data and topics.**

## Scope

AI / machine learning · cybersecurity · cryptography · frontier physics · mathematics ·
quantum · robotics · materials science, plus focused strands on **hacking, technical
social engineering, computational propaganda, military & cyber technology, deception
(deepfakes / adversarial ML), technical espionage, blockchain forensics & AML, arms &
weapons engineering, and digital forensics.**

All entries are academic searches over open-access research literature (**arXiv** across
CS / math / physics / EE + **OpenAlex** for engineering & applied CS). This is a research
corpus for study and analysis.

## Pipeline

```
arXiv / OpenAlex ──▶ ingest ──▶ DuckDB warehouse ──▶ sections + chunks ──▶ LSA index ──▶ RAG / report
```

Built on the aqueduct corpus engine (DuckDB, zero-config, in-process).

```bash
python -m prometheus harvest --topics topics.json --limit 15   # fetch + build
python -m prometheus corpus search "post quantum" -k 5         # lexical search
python -m prometheus facts                                     # corpus metrics
```

## Operations

A daily GitHub Actions harvest (`.github/workflows/prometheus-harvest.yml`) pulls the
corpus state from OneDrive (`onedrive:prometheus-state/state.tgz`), harvests, emails a
report, and pushes state back. Public repo → free unlimited Actions minutes.
