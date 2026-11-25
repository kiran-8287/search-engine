# Implementation status

| Area | Status | Evidence in the workspace |
| --- | --- | --- |
| Project configuration, setup and launch | Implemented | Python package, dependency declarations, config files and scripts |
| Collector integration, scope, provenance and resumability | Implemented and fixture-tested | Both root collectors passed all 16 collector tests on Windows |
| Active corpus and lexical indexes | Built and validated | Release `250a15ecd349951d6c69364c` has 15,345 documents from canonical snapshot `1a1a58867f0b20556402c331`. Standard and deep validation passed. |
| Active exact dense and hybrid | Built and validated | The same release has 197,628 passages and 384-dimensional vectors. The pinned MiniLM revision is `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. |
| Historical lexical experiments | Measured | Codec, TAAT/DAAT, retrieval and latent reports are saved for `6f86fc58d97fad8a0c0ec387` and `a585b9035a3c6cd217a93cbb`. Development benchmark and ablation runs are saved for `6f86fc58d97fad8a0c0ec387`. |
| HTTP and browser interfaces | Implemented and smoke-tested on the active release | Chromium 159 checked Search and all three IR Lab tabs, including a live Semantic/Hybrid comparison and exports. See the [IR Lab guide](IR_LAB.md). |
| Active Lab development measurements | Measured | The five displayed methods share 299 of 300 Development queries. Compression, TAAT/DAAT, retrieval/feedback and latent reports were generated on the active indexes. |
| Benchmark protocol and query catalog | Frozen, validation passed | 300 dev / 300 test, 25/class/split, no cross-split duplicate normalized queries; independent conformance fixtures |
| AI relevance evaluation | Pending configuration and judgments | The active Lab Development pool has 12,056 pending pairs and zero cached judgments. The annotation key and model are unset. The held-out Test run remains sealed. |
| Data acquisition | MDN and SO pilot exports saved | The pinned MDN run saved 12,650 structured pages. The later SO pilot reached 5,000 eligible questions. The active release still uses 2,748 eligible legacy SO questions. |
| Fixture suite | Passed on Windows | All 56 tests passed, including Search and IR Lab against temporary fixture releases. |
| Offline demo packaging | Archive and Windows runtime verified | The extracted bundle passed keyword, semantic and hybrid API searches with Python socket access and DNS blocked. A fresh disconnected installation and other destination OSes remain unverified. See the [demo run sheet](DEMO_RUN_SHEET.md). |

The **42,374** passage count belongs to the earlier Linux dense release `0bc9d95b4db6f1357b62a591` on 7,691 legacy documents, as recorded in the work log. Its manifest is absent from this workspace. The active Windows build uses refreshed structured MDN and the same legacy SO input. Its final build log, manifest, and vector array agree on the release and passage count. The build process had exited when checked on 2026-11-22.

## Collector repair verification, 2026-11-22

Each of the five reproduced failures came from collector code. The existing test expectations and assertions still apply.

| Failing case | Root cause | Fix |
| --- | --- | --- |
| Scoped MDN extraction with long paths | The extractor unpacked the entire archive and used ordinary Windows paths. | Pinned archives extract the configured English pages and redirect file using extended-length Windows paths. The scope-keyed extraction remains tied to the archive checksum. |
| Stack Exchange throttle retry | Retry classification relied on HTTP status, so API throttle error 502 sent with HTTP 400 stopped collection. | Recognize the API throttle code, honor the longer of a numeric `Retry-After` and JSON `backoff`, and keep retries bounded. A successful low-quota page remains available to the caller. |
| Highest-voted answers for each question | Supplemental lookup made a separate request per question and had no way to read globally sorted batch pages. | Group short threads and collect up to three distinct vote-sorted candidates per question across pages. Give unfinished questions individual lookups if the shared page budget runs out. |
| Question scope from extracted text | Scope was checked against raw HTML, allowing link URLs to count as browser evidence. | Check the structured document in both the tag and date-partition collection paths before crediting it toward the target. Preserve references, code and provenance for admitted questions. |
| Per-question progress after a quota stop | Supplemental completion was modeled as one lookup per question and could not record partial progress from a shared page. | Checkpoint completed question IDs and answers from successful pages. Leave unfinished IDs pending and deduplicate stored answers when they are replayed. |

The focused collector run initially reported 6 passed and 5 failed. After repair, it reported 16 passed. The full suite reported 49 passed with two dependency deprecation warnings. Collector checks used mocked Stack Exchange responses and local MDN ZIP and provenance fixtures. The repair left the existing exports, collection checkpoint and active indexes untouched.

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

See the [execution report](EXECUTION_REPORT.md) and [work log](../progress/WORK_LOG.md) for release-specific evidence. Ranking defaults have not been tuned against test outcomes or relevance labels. Normalized query uniqueness does not prove semantic intent independence.
