# Implementation status

| Area | Status | Evidence in the workspace |
| --- | --- | --- |
| Project configuration, packaging, setup and launch | Implemented | Python package, dependency declarations, config files and scripts |
| Collector integration, scope, provenance and resumability | Implemented | Root collectors, wrappers, stage diagnostics and mocked tests |
| Canonical corpus and file repository | Implemented | JSONL records, random access, alias maps, quarantine and integrity checks |
| Lexical retrieval and compression | Executed, passed | Real release `6f86fc58d97fad8a0c0ec387`; deep source/forward/posting checks and measured codec reports |
| Local exact dense and hybrid | Model passed; build running | MiniLM revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; 42,374 planned passages, resumable cache |
| Graph, feedback, MMR, LSI and K-means | Executed, passed on lexical release | Independent graph export, six-query retrieval interventions, LSI/K-means and session tests |
| HTTP and browser interfaces | Implemented | Versioned API, Search and IR Lab with snapshots, viewers and experiments |
| Benchmark protocol and query catalog | Frozen, validation passed | 300 dev / 300 test, 25/class/split, no cross-split duplicate normalized queries; independent conformance fixtures |
| AI evaluation | Blocked | Annotation credentials/model absent; no qrels or relevance metrics generated, no paid requests made |
| Data acquisition | Deferred by user | Existing real exports used; exclusions and gaps saved separately; raw hashes unchanged |
| Tests and actual browser verification | Executed, passed to date | Fixture checks and actual lexical Search/Lab in Chromium 133; final dense API/browser run pending |
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

Linux x86_64/glibc 2.28 with Python 3.12 is the tested environment. Windows/macOS checks remain unperformed. See [execution report](EXECUTION_REPORT.md) and [work log](../progress/WORK_LOG.md) for current evidence. Ranking defaults have not been tuned against test outcomes or relevance labels. Normalized query uniqueness does not prove semantic intent independence.
