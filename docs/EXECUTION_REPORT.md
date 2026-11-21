# Execution report — 2026-11-22

## Windows run

- Python 3.12.16, declared dependencies, CPU PyTorch and Chromium installed successfully. All 37 fixture tests passed after fixes for long archive and embedding cache paths.
- The interim release from the existing exports reproduced release ID `6f86fc58d97fad8a0c0ec387` on Windows. Deep validation and the offline experiment suite passed. The loopback API returned the MDN `Promise.all` page as its first hit for the scoped title query. IR Lab returned HTTP 200.
- The pinned MDN revision `df622a2a1c1e9626976cb3c091622d35e799b0cf` yielded 12,650 structured pages and zero parse failures. Browser compatibility metadata and the pinned MiniLM encoder downloaded successfully.
- Stack Exchange accepted the configured key. Question collection reached the answer-acquisition stage and is saving its checkpoints. Indexing the refreshed MDN snapshot is underway.
- Windows logs and live smoke-test output are under `artifacts/execution/`. No annotation credentials were loaded and no AI judgments were produced.

## Earlier Linux run

This report records actual execution in the repository on Linux x86_64/glibc 2.28, using Python 3.12. The user selected the existing exports and asked to report acquisition gaps separately. No raw export or completed checkpoint was deleted or replaced; no paid annotation request, publication, push or public deployment occurred.

## Verified milestones

- Full bootstrap and dependency consistency check passed with CPU PyTorch. The default `python3` is unsupported 3.9.25; use `.venv/bin/python`.
- Canonical snapshot: `data/processed/b1bddfda4e413b0e8d06ea0a/`, 7,691 parents: 4,943 MDN and 2,748 Stack Overflow. Canonical artifacts total 44,019,813 bytes.
- Lexical release: `artifacts/releases/6f86fc58d97fad8a0c0ec387/`, 82,965 terms, 1,398,540 document-term postings, 4,206,671 positional occurrences. Build time 121.825 seconds; release artifacts 243,305,087 bytes.
- Deep lexical validation passed, including source positions, forward TF/lengths/norms, and all three posting decoders. All 7,691 parents independently resolve to original input-array offsets with matching stable ID, URL and segment text.
- MiniLM encoder revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` downloaded and verified. Real encoder smoke test: 2 x 384 normalized vectors. Dense build is running for 42,374 passages.
- Fixture unit/integration and Chromium checks passed to date. The actual lexical Search and Lab were exercised on loopback; screenshots were inspected. Final dense checks remain pending.

## Measured lexical experiments

| Codec | Payload bytes | Metadata bytes | Complete artifact bytes |
| --- | ---: | ---: | ---: |
| uint32 | 107,767,312 | 3,111,352 | 110,878,664 |
| variable byte | 38,170,515 | 3,058,914 | 41,229,429 |
| gamma | 35,981,285 | 3,039,776 | 39,021,061 |

TAAT/DAAT rankings and scores matched exactly for six queries across 24 reader/strategy conditions. The 2,500-document latent sample used 48 dimensions (explained variance 0.2092853671) and 12 effective K-means clusters (inertia 1245.848759; sampled silhouette 0.1035856908). Likelihood, PageRank, MMR and declared Rocchio vector-probe outputs and timings are saved. These are algorithm/performance diagnostics, not relevance quality measurements.

The MDN induced graph has 4,943 nodes, 10,667 edges, 1,655 isolates, and 1,900 dangling nodes. PageRank converged in 75 iterations with L1 residual 9.4803563e-9.

## Evaluation and collection limits

The frozen catalog has 600 unique group IDs: 300 dev and 300 test, with 25 per class per split. No normalized query is duplicated across splits. No test relevance labels or outcomes have informed tuning; defaults remain fixed. Automated uniqueness checks do not establish semantic intent independence.

Relevance annotation is blocked by missing `TECHSEARCH_ANNOTATION_API_KEY` and annotation model. No labels, nDCG, MRR, precision or recall values have been fabricated. Metrics require every compared result through max(10, recall depth) to be judged; unavailable methods are excluded; pooled recall uses the judged relevant pool as denominator.

Both exports are valid, usable partial legacy collections with unattested source revisions and flattened text. There are 1,640 quarantined input offsets: 51 MDN out of scope, 1,125 SO framework/server exclusions, 458 insufficient domain evidence, and six exact-content duplicates. Quarantine changes only canonical admission; all original inputs remain intact.

The eligible SO collection is 2,252 below its 5,000 milestone. Of 2,748 eligible questions, 2,621 include 3,186 answers; all 2,381 declared accepted answers are exported. Structured headings/code boundaries and browser compatibility metadata are unavailable. Phrase matching is intentionally disabled within unsafe flat body/answer segments; titles remain phrase searchable. Further collection is deferred by user instruction.

## Evidence and launch

Commands, logs, environment versions, catalog audit, collection gaps, source-integrity results, and browser screenshots are in `artifacts/execution/`. Reports and runs are grouped by immutable release under `artifacts/reports/` and `artifacts/runs/`. The work log records failures and repairs as well as passes.

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/start.py --host 127.0.0.1 --port 8000
```

Search: `http://127.0.0.1:8000/`. Lab: `http://127.0.0.1:8000/lab`. Restart after changing the active release. Dense build, full-release benchmarks, offline bundle checks and final app checks are still in progress. Windows/macOS execution remains unperformed.
