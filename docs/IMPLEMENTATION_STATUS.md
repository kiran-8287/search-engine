# Implementation status

| Area | Status | Evidence in the workspace |
| --- | --- | --- |
| Project configuration, packaging, setup and launch | Implemented | Python package, dependency declarations, config files and scripts |
| Collector integration, scope, provenance and resumability | Implemented | Root collectors, wrappers, stage diagnostics and mocked tests |
| Canonical corpus and file repository | Implemented | JSONL records, random access, alias maps, quarantine and integrity checks |
| Lexical retrieval and compression | Implemented | Binary forward/positional files, three codecs, modes, rankers and execution comparisons |
| Local exact dense and hybrid | Implemented | Pinned local model flow, passage chunks, NumPy artifacts, RRF and fallback |
| Graph, feedback, MMR, LSI and K-means | Implemented | Algorithms, reporting commands, session isolation and knobs |
| HTTP and browser interfaces | Implemented | Versioned API, Search and IR Lab with snapshots, viewers and experiments |
| Benchmark protocol and query catalog | Implemented | 600 authored intent groups, freeze command, independent conformance fixtures |
| AI evaluation | Implemented workflow, not started | Explicit credentials/model required for annotation, no qrels generated |
| Data acquisition, release builds, performance and browser verification | Not started | Existing raw files remain available, all new artifacts and measured results await execution |
| Offline bundle preparation | Implemented workflow, not started | Archive command and documentation, portability unverified |

## Additional research

| Research | Status | Reason |
| --- | --- | --- |
| ANN, float16 and int8 dense representations | Deferred | Establish exact baseline quality and resource costs first |
| HITS | Deferred | Inspect graph structure and PageRank diagnostics first |
| WAND | Deferred | Requires safe field-aware upper bounds and equivalence checks |
| Cross-encoder | Deferred | Evaluate bounded second-pass relevance and latency after pooling |
| Learned Auto and learning to rank | Deferred | Requires a stable developmental label set and leakage controls |
| Hierarchical clustering and DBSCAN | Deferred | Compare against measured K-means diagnostics first |
| LDA / PLSI | Deferred | Lexical/latent baselines and appropriate corpus diagnostics are prerequisites |

No executable checks have been run. Linux and Windows portability remains unverified. The queries and their grouping need a development protocol review before the first freeze.
