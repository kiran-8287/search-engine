# TechSearch

**Information Retrieval course project · Human review prepared 28 November 2026**

The 50-query Development study has compatible timings and a blind human review page for all 1,085 pooled pairs. The six-method quality comparison awaits a complete numeric export. Two earlier AI pilots remain provisional. The 300-query timings below describe the original run. [Study and pilot findings](GROQ_STUDY.md) · [Human review](GROQ_V3.md)

| 50-query method | Median ms | p95 ms | Relevance metrics |
| --- | ---: | ---: | --- |
| TF-IDF | 162.19 | 1,977.39 | Pending |
| BM25 | 189.74 | 1,860.62 | Pending |
| Query likelihood | 158.41 | 1,710.47 | Pending |
| Semantic | 365.08 | 1,630.48 | Pending |
| Hybrid | 410.57 | 2,415.35 | Pending |
| BM25 + PageRank | 184.23 | 1,706.17 | Pending |

The study pools the six methods' saved top ten for each query. The two pilots used 126 generation attempts and 124,342 reported tokens. Their AI reviews found unsupported grades and missing source context. V3 repaired evidence selection and positional checks offline. The fixed subset would use nDCG@10 against the judged pool, Precision@10 and MRR@10. Test remains sealed.

TechSearch searches English web-development documentation and practical programming questions on a local computer. MDN explains how a web feature works. Stack Overflow provides concrete problems and answers. Search keeps the interface simple. IR Lab provides controlled comparisons on the same indexes.

## From source records to search

```text
MDN archive ────────┐
                    ├─► Structured exports ─► Scope and deduplication
Stack Overflow API ─┘                                 │
                                                      ▼
                                              Canonical JSONL
                     ┌──────────────────┬─────────────┴────────────────┐
                     ▼                  ▼                              ▼
              Lexical files      Dense passages                   MDN graph
                     └──────────────────┴──────────────────────────────┘
                                        ▼
                          Immutable release verified at startup
                                        ▼
                       Search and IR Lab ─► Evidence and attribution
```

The final build uses the saved structured exports at `data/raw/mdn_documents.json` and `data/raw/stackoverflow_documents.json`. Scope prioritizes browser-side JavaScript, DOM and Web APIs, CSS, HTML, HTTP, security, accessibility and performance. Scope excludes selected server-side and framework material. The root JSON files remain available for a first build from a public clone. The earlier prepared release is preserved as a fallback.

| Source | Raw parents | Admitted parents | Rejected | Reason | Admitted answers |
| --- | ---: | ---: | ---: | --- | ---: |
| MDN | 12,650 | 12,597 | 53 | Outside scope | 0 |
| Stack Overflow | 5,056 | 5,000 | 56 | Insufficient browser-domain evidence | 13,303 |
| **Total** | **17,706** | **17,597** | **109** | | **13,303** |

All 4,157 declared accepted answers in the admitted threads were saved. The pilot checkpoint has no pending answer lookups. The saved export omits a license on 472 admitted question records and an author on three questions and one answer. Source excerpts retain those gaps in attribution. [Data dictionary and admission evidence](DATA_DICTIONARY.md#course-corpus-admission)

The MDN collector pins an English source revision and retains headings, prose, code and source references. Known documentation macros are converted to readable labels and links, and unresolved cases retain diagnostics. The Stack Exchange collector uses tag and browser-domain rules, keeps accepted and high-scoring answers within its per-question cap, and writes checkpoints for resumption. The final build used existing exports and made no Stack Exchange requests.

Preprocessing checks URLs, identity, usable source segments and scope, and fingerprints exact duplicates. It keeps one searchable parent per question with distinct answer IDs. A canonical Stack Overflow parent can contain question, answer and code segments. Answer data still carries its own license, author where supplied, accepted status, and original link. A stable source ID identifies a parent across builds. The document number and passage rows are local to a release.

## Storage and ranking

| Structure | What it stores and how Search uses it |
| --- | --- |
| Catalog and offsets | The catalog maps stable IDs to integer document IDs. A byte-offset table lets the service read one canonical JSONL record without scanning the corpus. |
| Forward index | Per-document term counts, field lengths, indexed length and the TF-IDF norm. Feedback and diversity can read document term vectors. |
| Positional inverted index | A term dictionary gives document and collection frequency and a binary slice. Each posting stores fields, segment and token positions, character spans and an original-token flag. |
| Three posting codecs | Fixed 32-bit integers are the storage baseline. Variable-byte and gamma use document gaps. Normal Search uses variable-byte. All three encode the same positional data. |
| Dense passage store | A pinned pretrained MiniLM encoder produces normalized 384-dimensional float32 vectors. Windows use up to 220 encoder tokens and 28 overlap. Source section, code and answer boundaries inform chunking. The store maps passage rows back to the parent and exact source spans. |
| Link graph | Resolved links between admitted MDN pages feed PageRank. The optional reranker moves only MDN results within their existing top-20 slots. |

The lexical analyzer casefolds terms and preserves API identifiers and supported operators. For instance, `Promise.all` is indexed as `promise.all` plus aliases `promise` and `all`. It does not stem or remove stopwords. Phrases match adjacent original positions inside the same segment. Code is indexed separately and can be searched as an explicit field.

BM25 uses term frequency, inverse document frequency and length normalization by field. TF-IDF compares weighted vectors with cosine similarity. Query likelihood estimates query term probabilities with Dirichlet smoothing. TAAT processes a posting list at a time. DAAT merges posting lists by document ID. Both can execute BM25 and TF-IDF, and share scoring and tie-breaking.

Semantic search encodes each query and scores eligible passages exactly, keeping the best passage for each parent. Hybrid adds reciprocal ranks from BM25 and Semantic. With the default constant of 60, lexical rank 3 contributes `1/63`. Lexical and semantic scores have different scales. Auto gives priority to explicit syntax, dotted identifiers and operators, and recognizes standalone camelCase identifiers. Ordinary prose can use Hybrid even when it contains a camelCase technology name. This is a routing heuristic, so an identifier first in a prose query may need explicit Keyword mode when exact lookup is intended.

## Search modes and the course

| Topic | Working example | Where it runs |
| --- | --- | --- |
| Keyword, fields and postings | `Promise.all` or `source:mdn title:promise` | Search or Try a query. BM25 uses a title field weight of 3. |
| Boolean retrieval | `source:mdn AND (title:CSS OR title:HTML) AND NOT title:SVG` | Search. The parser implements NOT, then AND, then OR. |
| Phrases | `"event bubbling"` | Search. Original adjacent positions are required. |
| Prefix and fuzzy matching | `querySelec*` or `promsie.all` | Try a query. Fuzzy expands eligible misspellings that are outside the index vocabulary. |
| Dense retrieval and fusion | `wait for several JavaScript promises to finish` | Compare Semantic and Hybrid in Try a query. |
| Compression and traversal | Same terms across codecs. Same ordered result IDs and scores in TAAT/DAAT. | Course experiments. |
| Graph, diversity and feedback | BM25 with authority. MMR on top results. Rocchio term expansion with a chosen input. | Optional retrieval controls and saved experiments. |
| LSI and clustering | Fit truncated SVD and K-means on a fixed document sample and inspect representative terms. | Exploratory experiment. The public ranker does not use its cluster labels. |
| Relevance evaluation | Judge a pool shared by compared methods, then calculate rank metrics. | The pipeline is implemented. Quality depends on independent judgments. |

The final corpus contains the literal typo `addEventListner` in one document's code. Fuzzy mode keeps known vocabulary terms unchanged, so that lookup did not run correction. In the same corpus, `promsie.all` has no posting and expanded to `promise.all` with weight 0.25. Returned source excerpts highlighted the matched term. These checks used the index and evidence without expecting a particular result rank.

The course syllabus and lecture list were unavailable. These examples map to standard IR topics. The project uses a pretrained encoder and fits LSI and K-means on local data. It does not train a learned ranker. ANN, WAND, HITS and other deferred approaches are outside this implementation.

## Reproduce the local work

Use Python 3.11 or 3.12 and the [setup guide](../README.md). Use the matching structured inputs and provenance to reproduce the course corpus. A prepared demo serves its existing files without a rebuild. Keep the frozen evaluation catalog and leave the Test split sealed until the settings and judgment workflow are ready.

```sh
python -m techsearch inspect-data
python -m techsearch preprocess
python -m techsearch build-indexes
python -m techsearch validate-release
python -m techsearch validate-release --deep
python -m techsearch benchmark --split dev --lab
python -m techsearch evaluate --split dev --lab
python -m techsearch experiments --suite all
python scripts/start.py --host localhost --port 8000
```

The Development measurement includes parse, ranking, dense query encoding where applicable, and excerpt preparation. It excludes HTTP transfer, pagination and cold starts. The relevance pipeline pools every compared method through at least rank 20. Its nDCG@10 uses gain `2^grade - 1` discounted by log rank. Precision divides the number of grades 2 or 3 in the first ten by ten. MRR uses the first such rank. These metrics do not come from search scores or from answer votes. Selecting a top hit for the Rocchio demonstration supplies an input to that demonstration only.

## Final release and measurements

The verified course release contains **17,597 parents** and **252,965 dense passages**.
The earlier active release had 15,345 parents and 197,628 passages.
The new build reused 184,556 compatible passage rows from previously verified files. It re-encoded or used the text cache for the other 68,409 rows.
The build regenerated the canonical files, forward and positional indexes and link graph for the current corpus. The source files and the earlier prepared release remain available.

### Development timing

The frozen Development workload has 300 queries. The table uses the 300 queries with a non-degraded success in all five baseline methods.
One warm-up per method is discarded. Measurements record one full local search per method per query in a warmed process on Windows with Python 3.12.16 and 12 logical CPU cores. Method order was seeded and shuffled. CPU thread settings were `OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2` and `OPENBLAS_NUM_THREADS=1`.
The baseline uses TAAT for lexical ranking, BM25 k₁ 1.2 and b 0.75, fusion constant 60, and at most 150 candidates per branch.

| Method | Median ms | p95 ms | Successful | Empty successes | Unavailable | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TF-IDF | 86.81 | 896.47 | 300 | 23 | 0 | 0 |
| BM25 | 100.06 | 954.51 | 300 | 23 | 0 | 0 |
| Query likelihood | 111.42 | 930.07 | 300 | 23 | 0 | 0 |
| Semantic | 198.17 | 908.17 | 300 | 11 | 0 | 0 |
| Hybrid | 214.11 | 1124.59 | 300 | 1 | 0 | 0 |
| BM25 + PageRank | 91.80 | 792.82 | 300 | 23 | 0 | 0 |

An empty success is a completed search that found no hits. Failed or unsupported queries are recorded with reasons in the full saved run.
TF-IDF had the lowest observed median among the baseline methods, and TF-IDF had the lowest observed p95. These are measurements on one machine and query workload. They do not establish an overall winner or a reliable difference between close timings.
The paired authority subset has 300 queries. On those, BM25 changes from 100.06/954.51 ms to 91.80/792.82 ms median/p95 with PageRank.
The reranker adds a pass over the results. One measured run cannot establish the timing effect of that pass.
The graph contains 12,597 MDN nodes and 106,261 edges. PageRank converged in 76 iterations, with damping 0.85.

### Course experiments

| Codec | Postings payload bytes | Payload and lexicon bytes | Median lookup/decode ms |
| --- | ---: | ---: | ---: |
| Fixed | 267,633,856 | 274,340,699 | 156.70 |
| Variable-byte | 76,758,686 | 83,227,640 | 194.20 |
| Gamma | 66,023,283 | 72,453,535 | 1060.64 |

The codecs decoded identical postings on this workload. The measured batch includes 10 distinct terms (===, aria-live, cors, css, delegation, event, grid, preflight, promise.all, value). Each codec got one untimed batch and 3 timed batches, with a new reader per batch and rotated order. The table gives the median total time for a batch. Reader setup, equality testing and index construction were outside the timer. Gamma used the least space. Fixed-width used the most space. Fixed-width had the lowest observed decode time in this experiment.

TAAT and DAAT agreed on result IDs, order and scores across 6 queries, with 3 timings per condition and no separate warm-up. Fresh readers shared the OS cache. Memory tracing was separate.

| Reader | TAAT median / p95 ms | DAAT median / p95 ms | Samples per strategy |
| --- | ---: | ---: | ---: |
| Fresh | 50.77 / 211.99 | 55.67 / 240.69 | 18 |
| Reused | 28.30 / 188.29 | 28.65 / 217.62 | 18 |

The optional retrieval experiment compares lexical baselines, authority, MMR and a Rocchio probe. It uses a selected top hit as demonstration input. These changes have no independent relevance labels.
The latent experiment used 2,500 sampled parents, 48 SVD dimensions, and 12 clusters. Its sample silhouette was 0.102. The cluster labels describe high-weight terms. They do not establish true categories or ranking gains.

### Relevance is pending

The separate 300-query Development pool has **12,286 unique pending pairs, 0 judgments, and 0 provider requests**. It covers all six configurations through rank 20, including BM25 plus PageRank. The 300 timed queries include 299 with pooled candidates and one with none. No nDCG@10, Precision@10 or MRR@10 values were computed for the corpus. Ranking quality and quality–speed trade-offs are still unknown. The 300 held-out Test queries remain sealed. No Test pool has been generated.

The local `TECHSEARCH_ANNOTATION_API_KEY`, the approved `annotation.model` and authorization to send requests are required. The endpoint is configured in `config/evaluation.yaml`. The proposed pilot interleaves query classes and sources. Its evidence includes the query, topic and source excerpts, including available code or answer text. It omits retrieval scores, ranks and method names. The `techsearch-relevance-v2` prompt asks the judge to return the matching pair identifier and a grade supported by the excerpts. Insufficient evidence remains pending. Mocked provider and browser tests check the workflow. They do not supply corpus judgments.

```sh
python -m techsearch evaluate --split dev --lab --annotate --limit 50 --max-requests 75
```

Run this proposed pilot only after approval of its provider, model and request budget. `--limit` counts newly completed judgments. `--max-requests` stops all outbound attempts at the specified number, including retries, audits and adjudication. The preset 15% audit fraction gives an estimated 1,843 audits across the full Development pool, in addition to 12,286 primary calls. Adjudication and retries add to that total. A request cap does not set a currency cap. Cache identity includes the release, protocol, judge configuration and pair. Saved review stages can resume within a new authorized budget. Review the pilot and settle the Development instructions before running the held-out commands.

```sh
python -m techsearch benchmark --split test --lab --confirm-sealed
python -m techsearch evaluate --split test --lab --confirm-sealed
```

### A real search and its source

Typing `Promise.all` takes Auto's exact-identifier branch. The browser sends the query to `POST /api/v1/search` and the service uses BM25/TAAT. The request had 17,597 eligible parents and saved 66 ranked hits.
The first hit was **Promise.all()** with a BM25 score of 57.594529. The app highlighted `Promise.all` from source segment 1. Preview looks up that parent and displays source text and attribution. Page 2 slices the saved ranking instead of rerunning retrieval.

The structured Stack Overflow example, **Handling errors in Promise.all**, remains one parent with 3 saved answers. A code-field query selected an accepted answer's code block. Chromium displayed its original line breaks, author and license. A phrase within the answer matched, and constructed phrases crossing a segment or an answer boundary did not.

![Search results from the current course corpus](../artifacts/execution/groq-dev50/browser/search-desktop.png)

![Structured accepted-answer Preview](../artifacts/execution/course-final/structured-answer-preview.png)

![IR Lab with 50-query Development timings and the rejected Groq pilot status](../artifacts/execution/groq-dev50/pilot-browser/lab-model-comparison.png)

### Verification evidence

- [Standard release validation](../artifacts/execution/course-final/validate-release.json) and [deep validation](../artifacts/execution/course-final/validate-deep.json) cover the actual final release. [Search correctness](../artifacts/execution/course-final/search-correctness.json) covers the eight modes, no match, exact and prose routing, pagination and the structured answer.
- [Full fixture and browser suite](../artifacts/execution/course-final/pytest.log) verifies software behavior. The full suite used the project environment, and the fresh Windows setup was exercised separately.
- [Development summary](../artifacts/reports/0a7d123cb6254929b6985dbd/lab-dev.json), [full run](../artifacts/runs/0a7d123cb6254929b6985dbd/lab-dev.json), and [quality status](../artifacts/reports/0a7d123cb6254929b6985dbd/evaluation-lab-dev.json) distinguish measured timing from pending judgments.
- [Input audit](../artifacts/execution/course-final/input-audit.json) and [admission summary](../artifacts/execution/course-final/admission.json) record provenance and counts. [Demo run sheet](DEMO_RUN_SHEET.md) describes clean-environment preparation and the extracted archive check.
