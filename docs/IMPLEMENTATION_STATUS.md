# Implementation status

Current course release checked on 27 November 2026. The original 300-query timings are from 25 November. The fixed 50-query Groq study has its own 27 November timings. See the [course report](PROJECT_REPORT.md) for measurements and limitations.

| Area | Status | Evidence |
| --- | --- | --- |
| Structured source inputs | Admitted and audited | The structured MDN and Stack Overflow exports produced 12,597 pages and 5,000 threads. The threads contain 13,303 saved answers. The older prepared release and original exports remain available. [Data dictionary](DATA_DICTIONARY.md#course-corpus-admission) |
| Lexical, dense and graph files | Built and deep-validated | Release `0a7d123cb6254929b6985dbd` has 17,597 parents and 252,965 passages. Files include all three codecs, exact float32 dense vectors, the passage map, and MDN PageRank. [Validation and build log](../artifacts/execution/course-final/) |
| Search and IR Lab | Implemented and verified | All eight search modes and structured answer Preview passed. Auto distinguishes natural-language camelCase names from standalone identifiers. Search and Lab use the same release. [IR Lab guide](IR_LAB.md) |
| Development results | Measured | Five baseline methods, paired BM25 + PageRank, TAAT/DAAT, compression, retrieval/feedback and LSI/K-means. The comparison uses 300 common Development queries. [Course report](PROJECT_REPORT.md#development-timing) |
| Relevance | Blocked | 0 judgments and 12,286 pending Development pairs. Blinded prompt v2, resumable audit stages and a hard per-invocation request cap passed mocked tests. The private key, approved model and request authorization are pending. Test remains sealed. |
| Groq Free subset | Timed, pilot rejected | Access confirmed. The pilot saved 50 provisional grades in 69 attempts. AI review found material relevance errors. The remaining 1,035 pairs are unjudged. [Study details](GROQ_STUDY.md) |
| Groq v2 judging | Pilot rejected | 50 provisional pairs, 57 attempts, and 73,935 reported tokens. AI review found four unsupported primary grades and one unsupported adjudication. [V2 review](../artifacts/execution/groq-dev50/v2-pilot-ai-review.json) |
| Human Development review | Awaiting a complete export | The offline page covers 1,085 pairs across 50 queries. The comparison accepts compatible human exports and requires all pairs to have numeric grades. [Review instructions](GROQ_V3.md) |
| Software tests | Passed | The study review suite passed 92 tests. Chromium verified the real page, including separate grades for shared documents, preview, navigation, persistence and JSON round trips. |
| Demo | Refreshed and verified on Windows | Use the [demo run sheet](DEMO_RUN_SHEET.md) for setup, checksum and exact package verification. |

Historical results are tied to their own releases. The 42,374-passage Linux build and the 197,628-passage fallback Windows build are documented in the [execution report](EXECUTION_REPORT.md).

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
