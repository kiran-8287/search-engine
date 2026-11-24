# Execution report — 2026-11-22

## Active release on Windows

- `artifacts/releases/active.json` points to `250a15ecd349951d6c69364c`. Its manifest records canonical snapshot `1a1a58867f0b20556402c331`, 15,345 documents, and 197,628 passages. The saved vector array has shape `(197628, 384)`. The dense build log ends with this release ID and the dense flag set, and no index build was running when checked on 2026-11-22.
- The release contains 12,597 admitted MDN pages from pinned revision `df622a2a1c1e9626976cb3c091622d35e799b0cf` and 2,748 legacy Stack Overflow threads. The MDN acquisition saved 12,650 structured pages before corpus exclusions, with zero parse failures. The later 5,000-question Stack Overflow export is recorded separately in `data/manifests/collection-stackoverflow.json`.
- Standard and deep validation passed on the active release. The pinned MiniLM encoder is `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Saved Chromium 159 evidence covers actual Search results, desktop and mobile previews, source filtering and IR Lab. See the [fresh deep validation output](../artifacts/execution/validate-active-dense-windows.json), [live browser evidence](../artifacts/execution/ui-redesign/live-browser.json), and [cleanup report](CLEANUP_REPORT.md).

## Fixture tests

The latest full run with Python 3.12.16 on Windows passed 49 tests, including 16 collector tests and Search and IR Lab tests in Chromium. The release fixtures use temporary data. Earlier Windows runs with 37 passes remain in the logs. See the [work log](../progress/WORK_LOG.md).

## Earlier Linux run

This report records actual execution in the repository on Linux x86_64/glibc 2.28, using Python 3.12. The user selected the existing exports and asked to report acquisition gaps separately. No raw export or completed checkpoint was deleted or replaced; no paid annotation request, publication, push or public deployment occurred.

## Legacy corpus releases

- Full bootstrap and dependency consistency check passed with CPU PyTorch. The default `python3` was 3.9.25. The run used the Python 3.12 virtual environment.
- Canonical snapshot: `data/processed/b1bddfda4e413b0e8d06ea0a/`, 7,691 parents: 4,943 MDN and 2,748 Stack Overflow. Canonical artifacts total 44,019,813 bytes.
- Lexical release: `artifacts/releases/6f86fc58d97fad8a0c0ec387/`, 82,965 terms, 1,398,540 document-term postings, 4,206,671 positional occurrences. Build time 121.825 seconds; release artifacts 243,305,087 bytes.
- Deep lexical validation passed, including source positions, forward TF/lengths/norms, and all three posting decoders. All 7,691 parents independently resolve to original input-array offsets with matching stable ID, URL and segment text.
- The earlier Linux dense release `0bc9d95b4db6f1357b62a591` completed with 42,374 passages on those 7,691 documents, according to the work log. Its manifest and dense benchmark outputs are absent from the current workspace. The active Windows dense release uses the larger refreshed-MDN snapshot.

## Historical lexical experiments

The following measurements are from legacy lexical release `6f86fc58d97fad8a0c0ec387`. Windows also reproduced and deep-validated this release. Its development benchmark and ablation artifacts remain under `artifacts/runs/6f86fc58d97fad8a0c0ec387/`.

| Codec | Payload bytes | Metadata bytes | Complete artifact bytes |
| --- | ---: | ---: | ---: |
| uint32 | 107,767,312 | 3,111,352 | 110,878,664 |
| variable byte | 38,170,515 | 3,058,914 | 41,229,429 |
| gamma | 35,981,285 | 3,039,776 | 39,021,061 |

TAAT/DAAT rankings and scores matched exactly for six queries across 24 reader/strategy conditions. The 2,500-document latent sample used 48 dimensions (explained variance 0.2092853671) and 12 effective K-means clusters (inertia 1245.848759; sampled silhouette 0.1035856908). Likelihood, PageRank, MMR and declared Rocchio vector-probe outputs and timings are saved. These are algorithm/performance diagnostics, not relevance quality measurements.

The MDN induced graph has 4,943 nodes, 10,667 edges, 1,655 isolates, and 1,900 dangling nodes. PageRank converged in 75 iterations with L1 residual 9.4803563e-9.

Windows also built and deep-validated refreshed-MDN lexical release `a585b9035a3c6cd217a93cbb`, which shares the active dense release's canonical snapshot. Its saved compression, TAAT/DAAT, retrieval and latent reports are grouped under its own release ID. The active dense release has no saved benchmark or experiment runs in this workspace.

## Pending AI relevance evaluation

The frozen catalog has 600 unique group IDs: 300 dev and 300 test, with 25 per class per split. No normalized query is duplicated across splits. No test relevance labels or outcomes have informed tuning; defaults remain fixed. Automated uniqueness checks do not establish semantic intent independence.

The saved development evaluation for `6f86fc58d97fad8a0c0ec387` reported 0 labels and 7,563 pending judgments. It gives missing `TECHSEARCH_ANNOTATION_API_KEY` and annotation model as the blocker. Relevance metrics remain unavailable. Metrics require every compared result through max(10, recall depth) to be judged. Pooled recall uses the judged relevant pool as its denominator.

## Historical collection limits

The two legacy exports have unattested source revisions and flattened text. Their historical snapshot quarantined 1,640 input offsets: 51 MDN out of scope, 1,125 SO framework/server exclusions, 458 insufficient domain evidence, and six exact-content duplicates. Quarantine applies to canonical admission and preserves the original inputs.

The legacy SO export was 2,252 eligible questions short of the 5,000 milestone. Of its 2,748 eligible questions, 2,621 include 3,186 answers and all 2,381 declared accepted answers are exported. Phrase matching is disabled within unsafe flat body and answer segments. Titles remain phrase searchable. These counts describe the frozen legacy input used in the active release.

## Offline demo

The 513,327,888-byte ZIP was built with `python -m techsearch package-demo` from the active release. It includes the pinned encoder and tokenizer, release files, local frontend and app source. All 87 archive entries extracted successfully, and application startup checked the release files against the bundled hashes. Semantic and hybrid search loaded the bundled encoder with an empty external model cache.

With the app imported from the extracted ZIP, an in-process ASGI check passed for keyword, semantic and hybrid search, source excerpt and attribution, session pagination, and the IR Lab comparison API. Search and Lab HTML and the search JavaScript were also served. An audit hook blocked the verification process from using Python sockets or DNS. Both TCP and DNS control probes were blocked and the application made zero networking attempts. See the [verification record](../artifacts/execution/offline-demo-250a15ecd349951d6c69364c.json) and [demo run sheet](DEMO_RUN_SHEET.md).

Verification used the existing Windows Python dependencies. A clean disconnected installation and runtime on another destination OS remain unverified. The ZIP requires a separate package wheelhouse for offline installation.

## Evidence and launch

Commands, logs, environment versions, catalog audit, collection gaps, source-integrity results, and browser screenshots are in `artifacts/execution/`. Reports and runs are grouped by immutable release under `artifacts/reports/` and `artifacts/runs/`. The work log records failures and repairs as well as passes.

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/start.py --host localhost --port 8000
```

Open Search at `http://localhost:8000/` and IR Lab at `http://localhost:8000/lab`. Restart after changing the active release.
