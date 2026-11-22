# TechSearch project facts

The figures below describe active release `250a15ecd349951d6c69364c`, frozen corpus `1a1a58867f0b20556402c331`, unless a different release is named. **Implemented** means the code exists. **Verified** names a test, saved measurement, file check, or observed behavior. **Pending** names a check or result that is still missing. The [source map](SOURCE_MAP.md) lists the code and workspace evidence.

## 1. Project purpose

TechSearch is a search engine for English web development material. It helps students and developers find documentation, API examples, and questions about browser JavaScript, HTML, CSS, HTTP, accessibility, and related topics. A result is one original MDN page or Stack Overflow thread. The result has a link, a short excerpt with matched text, and available source and author information. Preview opens the relevant source text and can show code, a section, or a specific answer.

Search, ranking, query encoding, source previews, and IR Lab run on local files and the local MiniLM model. A normal search needs no credentials. A fresh collection from GitHub or Stack Exchange, a model download, or following an original-source link needs network access. Installing dependencies needs network access or a complete local wheelhouse. AI annotation is a separate, explicit evaluation command that can send a pool of excerpts to a configured provider. It plays no part in normal searching.

## 2. Dataset

| Active-release count | Value | What it counts |
| --- | ---: | --- |
| MDN parents | 12,597 | Each admitted documentation page is one parent. |
| Stack Overflow parents | 2,748 | Each admitted question and its saved answers form one parent. |
| Total parents | 15,345 | Pages and threads combined. |
| Saved answers | 3,186 | Answer records attached to 2,621 threads. All 2,381 answers declared accepted in this release are present. |
| MDN segments | 408,171 | Stored blocks, including title, headings, prose, and 40,852 code blocks. |
| Stack Overflow segments | 17,605 | Titles, tag blocks, and legacy question and answer text blocks. |
| Total segments | 425,776 | Stored blocks before dense passage chunking. |
| Dense passages | 197,628 | Text windows with one 384-number vector apiece. One parent can have many windows. |
| Vocabulary | 118,105 | Distinct lexical index terms, including code identifiers, operators, and aliases. |
| Postings and occurrences | 2,650,881 and 8,103,295 | A posting counts a term and document pair. An occurrence counts an indexed position, including aliases. There are 6,596,918 original tokens before aliases. |

The active release uses `data/raw/mdn_documents.json` from pinned MDN revision `df622a2a1c1e9626976cb3c091622d35e799b0cf` and the older root `stackoverflow_documents.json`. The MDN collection report records 12,650 saved pages and zero parse failures. The scope rules rejected 53 of those pages. The active quarantine lists 1,125 Stack Overflow questions with excluded framework or server tags and 458 with insufficient browser-domain evidence. The later Stack Overflow pilot reached 5,000 eligible questions and saved a separate raw export. Its records and structured answer evidence have yet to enter the active release. The older answer records lack some source and profile detail. The manifest marks the legacy export as unattested, which means its source revision and collector identity are unknown.

MDN collection covers configured English directory roots, such as Web APIs, JavaScript, CSS, HTML, HTTP, learning pages, and the glossary. Scope rules also exclude paths such as server-side learning material and selected frameworks. Stack Overflow scope uses tags and, for categories such as HTTP and security, browser cues in extracted text. The current collector fetches accepted answers separately and batches other answers by question, keeping the accepted answer plus high-scoring alternatives within a three-answer limit. This is the current collection policy. The counts above were read from the frozen legacy input as stored in the release.

Canonicalization rejects duplicate IDs, canonical URLs, matching content within a source, and reused answer IDs. The active rejection file has 1,636 rows, all with the scope reasons above. The 85 groups of titles that match after case and punctuation normalization are reported for review. A matching title alone is insufficient for deletion. Browser compatibility metadata enriched 10,234 MDN parents. The release still records unresolved macros and 31,385 reference occurrences whose targets could not be mapped to a local parent. A reference can still link to the original site.

Raw JSON preserves the collector's records for audit and future processing. Canonical JSONL stores one cleaned parent per line, with stable IDs, searchable blocks, normalized links, and a pointer to the source array entry where available. The release manifest records input names and hashes. MDN credits its contributors and links to the original page and applicable source terms. Stack Overflow uses recorded authors, licenses, question and answer links where the input supplies them. [Attribution notes](../ATTRIBUTION.md)

## 3. Preprocessing

- **MDN Markdown and macros.** The collector reads YAML front matter for the title and canonical slug. It parses Markdown into tokens, then handles macros in inline text. Supported references become human-readable labels and recorded link targets. Unsupported macros can leave a readable label and an unresolved record. Plain HTML links and source anchors are retained where available. Fenced code and inline code tokens skip macro expansion. Markdown and HTML structure become ordered headings, paragraphs, lists, table rows, and code blocks.
- **Stack Overflow HTML.** The current collector extracts visible text and links using Beautiful Soup. It preserves code whitespace and answer identities. It applies scope to the extracted document before counting it. The legacy questions in the active release use flat question and answer text and cannot recover missing original code or section boundaries.
- **Scope, identity, and links.** `corpus.normalize` checks language, content, IDs, source hosts, and configured scope. `build_corpus` assigns integer document IDs by sorting stable source IDs, records rejected inputs, and keeps original link references. URLs resolve against a base page, use normalized hosts, and keep fragments in references. MDN alias keys fold case, while display URLs preserve it. MDN redirects, source paths, SO short question URLs, and SO answer URLs can point to a canonical parent. Browser compatibility metadata can enrich a page without adding a new parent.
- **Lexical analysis.** `preprocessing.analyze` finds terms and character offsets with a code-aware pattern and folds case. It retains dotted tokens such as `Promise.all`, compound identifiers, selected HTML tags, CSS custom properties, and operators such as `===`, `?.`, and `=>`. It adds useful splits from dots, underscores, hyphens, and camel case. Ordinary punctuation such as the parentheses in a call can mark boundaries. There is no stopword list or stemmer. The index stores aliases alongside the primary tokens. A normal keyword query analyzes its primary terms and can hit either form on the document side.
- **Positions and passages.** Fields separate title, heading, body, code, question, answer, and tag. A lexical position is a zero-based token number within a segment. Character offsets support highlighting. A phrase requires consecutive original positions in one field and segment. Alias positions and legacy-flat bodies cannot satisfy phrase checks. Legacy titles can. Dense passage building groups adjacent prose within a heading path and answer. Title and code blocks get separate windows, tags are skipped, and long sections use up to 220 model tokens with 28-token overlap. The saved span list maps each window back to segment ordinals and character offsets.

### Real source example

Source is the pinned [MDN Promise.all() page](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all), credited to MDN contributors. In the saved Markdown, the syntax example at line 30 is:

```markdown
```js-nolint
Promise.all(iterable)
```
```

The active parent is document `11823`. Canonical segment `5` has field `code`, heading path `["Syntax"]`, and text `"Promise.all(iterable)\n"`, with the newline written here as an escape. In the intro of the same page, the source macro `{{jsxref("Promise")}}` became the visible word `Promise` and a saved `mdn_macro` reference to the [MDN Promise page](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise).

| Representation | Value checked on the real release |
| --- | --- |
| Primary lexical tokens | `promise.all`, `iterable`. The first has aliases `all` and `promise`. |
| Phrase positions and character spans | Within segment 5, `promise.all` is at position 0 and characters `[0, 11)`. `iterable` is at position 1 and characters `[12, 20)`. Both postings have their original flag set. Alias postings have the flag cleared. |
| Dense passage metadata | Passage row `170240`, parent `11823`, no answer ID, spans `[[5, 0, 21]]`. |
| Embedding input | `Promise.all(iterable)`. Running `chunk_rows` with the saved tokenizer reproduced this exact input from the saved span. The model tokenizer gave IDs `[101, 4872, 1012, 2035, 1006, 2009, 6906, 3468, 1007, 102]` including the start and end markers. The trailing newline is outside the token window. This inspection used the local tokenizer and existing passage metadata. |

The original and processed source text keep their display case. The lexical analyzer and model tokenizer have separate jobs. The lexical positions above are the positions used for phrase search.

## 4. Stored files and indexes

JSONL means one JSON record per line. A byte offset is the recorded location of a line or record in a file. It lets the app seek directly to that record. A **forward index** begins with a document and returns its terms. An **inverted index** begins with a term and returns the documents and positions where it occurs.

| Data | Files and actual size in bytes | When it is used |
| --- | --- | --- |
| Raw JSON arrays | Active MDN input 301,464,785. Active legacy SO input 15,091,917. The later SO raw export is 83,512,500 and is outside this release. | Read for corpus building or provenance checks. The app searches its frozen release. |
| Canonical documents | `documents.jsonl` 268,777,807 and `documents.offsets` 122,768. `catalog.jsonl` 3,880,584 and `aliases.jsonl` 2,251,395. | Startup loads the catalog, stable-to-integer map, offset table, and filter sets. A hit or preview reads its full document by offset. The stored alias table supports link resolution and validation. |
| Forward index | `forward.bin` 15,578,100, `forward.offsets` 122,768, `forward-stats.bin` 613,800. | Startup loads offsets and fixed-size field lengths, indexed length, and TF-IDF norm records. The app seeks to a zlib-compressed per-document term record for feedback and MMR. LSI uses forward data in offline experiments. |
| Positional inverted index | Three pairs of `postings-*.bin` and `lexicon-*.jsonl`. See sizes below. | The live service loads the VB lexicon at startup. It records document frequency, collection frequency, byte location, and bit length. Per-request readers decode the queried postings and reuse them within that query. |
| Passage rows and mappings | `passages.jsonl` 15,434,469, `passages.offsets` 1,581,032, `passage-parents.npy` 790,640. | On first dense use, the service opens the mapping. A passage row maps to a parent integer ID and a list of source spans. |
| Dense vectors | `vectors.npy` 303,556,736 for the full NumPy file. The float32 payload is 303,556,608 bytes. | The service memory-maps the array on first dense use. It reads eligible blocks as needed and encodes the query with the pinned local model. |
| Graph | `edges.jsonl` 3,802,863 and `graph.json` 374,695. | Edges support build and analysis. Startup loads ranks for optional reranking and the manifest supplies graph diagnostics for Lab. |
| Runtime results and feedback | `data/runtime/<prefix>/<session>/<search-id>.json` and optional `feedback.jsonl`. Variable size. | The app saves ranked snapshots for paging and export. Session feedback is read when refinement is requested. Snapshots expire after seven days and are capped at 100 per session. |

The 20 payload files listed in the active release manifest total **952,134,086 bytes**, as shown in Lab. This total omits the manifest file, encoder, raw data, and runtime records. The table above uses complete individual on-disk file sizes unless marked payload. Manifest versions, exact file hashes, build settings, corpus and component fingerprints, and the release ID make the release checkable. The build stages the files, opens and validates the completed release, and then atomically replaces `artifacts/releases/active.json`. The app opens the active release at startup.

| Active codec | Postings payload bytes | Lexicon bytes | Complete postings and lexicon bytes |
| --- | ---: | ---: | ---: |
| Fixed 32-bit integers | 208,834,992 | 4,634,003 | 213,468,995 |
| Variable byte (VB) | 60,841,006 | 4,487,820 | 65,328,826 |
| Elias gamma | 51,993,232 | 4,454,626 | 56,447,858 |

## 5. Search and ranking

A **mode** chooses how to interpret a query and which kinds of evidence to retrieve. A **ranker** scores eligible results. An **execution strategy** controls the order in which the lexical scoring work is done. A **reranker** changes the order of results already retrieved. RRF combines ranked lists, and Rocchio changes the lexical query before retrieval. Several modes use the same lexical rankers and index readers.

### The eight selectable modes

| Mode | Behavior and when to use it | Valid example | Index and implementation | Important limits |
| --- | --- | --- | --- | --- |
| Keyword | Scores matching terms. Good for names and API identifiers. | `Promise.all` | Positional postings and forward stats. `query.parse`, `Matcher.scoring`, `retrieval.lexical`. | Ordinary words are soft matches. Exact field and phrase clauses can still restrict the result. |
| Boolean | Builds a tree of required and excluded terms. Use it to express explicit inclusion. | `promise AND error` | Positional postings and metadata sets. `query.Parser.expression`, `Matcher.match`, then `retrieval.lexical`. | Operators are uppercase. Precedence is NOT, then AND, then OR. Parentheses can override it. Filter-only or pure negative results can have zero scores. |
| Phrase | Requires original adjacent tokens in a block. Use it for a known expression. | `"event bubbling"` | Positional postings. `query.parse` and the phrase branch of `Matcher.match`, followed by lexical scoring. | A phrase cannot cross a field or segment boundary. Flat legacy question and answer text is excluded from phrase matches. |
| Prefix | Expands a trailing asterisk into vocabulary terms that start with the same letters. Use it for partial API names. | `querySelec*` | Sorted lexicon and positional postings. `Matcher.prefix`, `Index.prefix` and `retrieval.lexical`. | Requires at least two word characters and a single trailing asterisk. A prefix over the 20-term expansion limit is rejected. |
| Fuzzy | Uses bounded edit distance for out-of-vocabulary terms. Use it for likely typos. | `addEventListner` in Fuzzy mode | Vocabulary length bins and positional postings. `Matcher.fuzzy`, `query.edit_distance`, `retrieval.lexical`. | No `~1` distance suffix. An eligible misspelled term has 5–35 characters and contains letters, with dots allowed. Existing terms are left as they are. The bound is one edit through length 7 and two for longer terms. Vocabulary and expansion limits apply. |
| Semantic | Looks for passages with similar meaning. Use it for explanations in everyday language. | `wait for several JavaScript promises to finish` | Local MiniLM, vector array and passage mapping. `dense.Dense.rank` and `exact_parent_hits`. The lexical index can enforce hard query clauses. | Requires a local encoder and built vectors. Keeps the best eligible passage per parent above cutoff. Exact scans cost more on larger releases. |
| Hybrid | Combines lexical evidence and semantic passages. Use it for queries mixing concepts and names. | `wait for several JavaScript promises to finish` | Uses both branches and `retrieval.fuse` through `SearchService.search`. | Combines only retained candidates. Explicit Hybrid reports unavailable dense data. Auto can fall back with a warning. |
| Field-specific | Requires matches in a field or metadata set. Use it for source or title restrictions. | `source:mdn title:promise` | Positional postings and metadata sets. `Parser.atom`, `Matcher.match` and `retrieval.lexical`. | Metadata values are exact, so `tag:` acts as a filter. Multiple restrictions are combined with AND outside Boolean mode. |

### Scoring, execution, and automation

Use the query examples below with the named Lab setting. They share the index and helpers described above.

| Feature | Idea, use, and example | Implementation and limit |
| --- | --- | --- |
| BM25 | Rewards rare matches, gives diminishing returns for repeated terms, and accounts for field length. Use Keyword + BM25 on `Promise.all`. | `retrieval.lexical` uses per-field term frequencies and lengths, plus lexicon document frequencies. Defaults `k1=1.2` and `b=0.75` are configurable. |
| TF-IDF cosine | TF is count in the document. IDF gives rarer terms more weight. Cosine compares the direction of weighted vectors, handling length through normalization. Compare Keyword + TF-IDF cosine with BM25 on `Promise.all`. | `retrieval.lexical` and `indexing.tfidf_idf` use weighted linear frequencies, smoothed IDF, and stored document norms. Only lexical features contribute. |
| Field weighting | Matches in important fields can count more. Try Keyword + BM25 on `Promise.all` and inspect the title contribution. | Defaults from `config/default.yaml` are title 3.0, heading 1.6, code 1.25, tag 1.4, and body/question/answer 1.0. BM25 and TF-IDF use these weights. Matching a field restriction changes which postings are scored. |
| Dense cosine | Compares the query vector with each eligible passage vector using a dot product on unit-length vectors. Try Semantic on `wait for several JavaScript promises to finish`. | `dense.exact_parent_hits` scans eligible rows and retains the highest passing score per parent. Default cutoff is 0.39. A high score is similarity evidence, with relevance quality still to be measured. |
| RRF | Reciprocal Rank Fusion gives a hit `1/(k + rank)` per branch, then adds the contributions. Try Hybrid on `wait for several JavaScript promises to finish`. | `retrieval.fuse` uses one-based ranks and defaults to `k=60`. Raw lexical and cosine scores are on different scales and are not summed. The candidate-depth limit affects fusion. |
| Auto | Public Search checks for Boolean operators, field qualifiers, quotes, prefixes, and identifier/operator patterns, in that order. For conceptual words it selects Hybrid. Try `Promise.all` in Search. | `service.auto_mode` uses `query.lex` to choose the mode. When Auto has no lexical candidate, its dense cutoff can rise to 0.56. There is no trained router. |
| TAAT | Term-at-a-time walks each term's postings and accumulates document scores. Try Keyword + BM25 + TAAT on `Promise.all`. | `retrieval.lexical` uses a document score table. Busy terms can create many accumulators. |
| DAAT | Document-at-a-time merges document-ordered postings using a heap. Try Keyword + BM25 + DAAT on `Promise.all`. | `retrieval.lexical` uses the same term contribution and tie-breaking as TAAT for BM25 and TF-IDF. This code does not implement WAND pruning. Dirichlet likelihood only supports TAAT. |
| Query likelihood | Estimates how likely each document is to produce the query. Dirichlet smoothing gives known missing terms a collection background. Try Keyword + Dirichlet likelihood + TAAT on `CORS`. | `retrieval.likelihood` reads term collection counts, postings, and stored indexed document lengths. `mu=1200` by default. Absent vocabulary terms are skipped. It scores eligible documents with a prior even when they miss all known query terms. |

The default candidate depth is 150 and the displayed snapshot is capped at 100 results. Identical scores break by integer document ID. Hard constraints are enforced before retrieval and checked after fusion. Request limits constrain query length, token count, nesting, vocabulary scans, expansions, and the number of posting occurrences decoded.

## 6. Academic experiments

| Feature | Implemented behavior | Actual execution evidence |
| --- | --- | --- |
| Compression | `compression.py` writes fixed little-endian integers, variable-byte groups, or Elias gamma codes. VB and gamma encode document ID gaps. Gamma encodes each nonnegative integer as one higher, then reverses the shift on decode. | All three codecs were built and deep-validated on the active release. Historical lexical releases have measured size and decode comparisons. The active Lab compression panel reports build sizes only. |
| TAAT/DAAT | `experiments.execution_report` compares scores and order with fresh and reused readers, and records timing, work, and traced Python allocation. | Historical files for `6f86fc58d97fad8a0c0ec387` and `a585b9035a3c6cd217a93cbb` each have 24 rows over six queries. Screenshot 15 is a single live BM25 comparison on the active release. Its saved timing report is absent. |
| PageRank | `graph.pagerank` spreads weight through links among admitted MDN pages, with uniform contributions for jump and dangling-page mass. Optional authority reranking moves results among the existing MDN slots in the top 20. | The active build graph has 12,597 pages, 106,261 edges, 53 isolates, and 193 pages without outgoing graph edges. It converged in 76 iterations at residual about `9.42×10⁻⁹`. The independent historical graph report is under the earlier lexical release. |
| Feedback and Rocchio | `feedback.Runtime` records explicit session votes. `rocchio` adds normalized positive term evidence and subtracts negative evidence using eligible forward records. Expansion adds at most six alphabetic terms under frequency rules. | Screenshot 18 shows a successful local vote, HTTP 204, and the refine action. Historical retrieval reports used a declared top-BM25 vector probe for Rocchio. A probe is a controlled input, with no evaluation judgment implied. |
| MMR | `experiments.mmr` reorders the first 35 candidates by rank-based relevance and term-set overlap with already selected hits. It can help show varied results. | Saved retrieval reports on both historical lexical releases compare MMR, authority, likelihood and BM25 over six queries. They measure algorithm behavior. |
| LSI | Latent Semantic Indexing uses a smaller set of hidden dimensions from a sparse TF-IDF sample. `experiments.latent_report` builds the matrix and uses truncated SVD to project documents and queries. | Both historical lexical reports used 2,500 sampled documents and 48 dimensions. The active dense release's main ranking uses MiniLM rather than LSI. |
| K-means | Groups the latent vectors around learned centers. The report includes cluster sizes, inertia (within-cluster spread) and silhouette (a measure of group separation). | The refreshed-MDN lexical report `a585b9035a3c6cd217a93cbb` records 12 effective clusters, inertia 1337.70 and sampled silhouette 0.10283. These are diagnostics for that sample. |

Deferred research includes approximate nearest-neighbor search, smaller float16 or int8 vector storage, HITS link analysis, WAND pruning, cross-encoder reranking, a learned router or ranking model, hierarchical clustering, DBSCAN, and LDA or PLSI topic models. The current project uses exact dense search and rule-based Auto.

## 7. Evaluation and correctness

- **Fixture tests.** The latest recorded full run passed 49 tests, including 16 collector tests and six Chromium tests. Fixtures check collector parsing and retries, Boolean and phrase behavior, codecs, dense row mapping, fusion, feedback isolation, validation against corrupted files, API behavior, and the UI. Fixture success is evidence about controlled examples.
- **Active release validation.** Fresh Windows deep validation checked schema and release fingerprints, file hashes and sizes, canonical and lexical consistency, forward frequencies, lengths and norms, positions across all three codecs, and passage offsets, normalized vectors and source spans. Saved real-release browser tests and this package's screenshots exercise actual results separately.
- **Development and test catalog.** There are 600 authored intent groups, 300 per split and 25 per class per split across 12 classes. A frozen fingerprint and normalized query checks protect repeatability. Development is for choosing settings. The held-out test split uses sealed confirmation and can assess the final settings after judgments exist. Distinct normalized queries can still express similar intent.
- **Saved measurements.** The saved development benchmark for `6f86fc58d97fad8a0c0ec387` ran 300 intents and three repeats. BM25 first-pass p50 was 49.37 ms and p95 was 447.32 ms across 299 successful cases. P50 is the midpoint and p95 is the 95th percentile. One query exceeded a workload limit. Dense and hybrid were unavailable on that lexical release. Readers shared the process and OS cache. On historical release `a585b9035a3c6cd217a93cbb`, the median lookup and decode of the same measured term set was 215.48 ms (uint32), 278.80 ms (VB), and 1,388.28 ms (gamma). Those timings belong to the saved run. Section 4 shows actual active build sizes, and screenshot search times are individual observations.
- **Judgments and metrics are pending.** The saved lexical development-ablation evaluation has zero labels and 7,563 pending pairs. The active release has no saved benchmark or judged pool. Annotation credentials and a model are required for the provider workflow. Judgments are graded relevance labels for a query and a document. P@5/P@10 count the relevant items among the first 5/10 slots. nDCG@10 rewards higher grades and earlier ranks. MRR@10 uses the reciprocal rank of the first relevant hit. Pooled Recall@20 compares retrieved relevant hits with the known relevant items in the judged pool. Results through the required depth must be judged before reporting these metrics. Missing values are pending, including any active dense relevance comparison.

## 8. Course connections

| IR concept | How TechSearch demonstrates it | What supplies the implementation |
| --- | --- | --- |
| Document representation | Parent records, fields, ordered segments, aliases, and dense passages | Project canonicalization and chunking. MarkdownIt, Beautiful Soup, and YAML parse source formats. |
| Indexing | Forward frequency records and position-aware inverted postings | Project external sort, writers, readers, lookup rules, and validation. Python libraries supply file I/O and zlib. |
| Vector-space retrieval | TF-IDF cosine, and exact similarity over learned vectors | Project scoring, filters, parent aggregation, and fusion. NumPy supplies arrays and arithmetic. Sentence Transformers and PyTorch supply the pretrained model and encoding. |
| Probabilistic ranking | BM25 and Dirichlet query likelihood | Project formulas and term statistics. |
| Query processing | Boolean tree, exact field filters, phrase positions, prefix search, typo distance, and Auto | Project lexer, parser, matcher, and routing rules. |
| Compression | Same posting lists stored using fixed-width, VB, and gamma encodings | Project integer stream and codec logic. Python supplies fixed-width binary packing. |
| Link analysis | PageRank on MDN's internal graph and optional authority reranking | Project edge rules, PageRank iteration and reranking. |
| Relevance feedback | Explicit votes, Rocchio expansion, and a controlled vector probe | Project session files and expansion rules. |
| Latent methods and clustering | LSI plus K-means on a sampled term-document matrix | Project sample, term matrix and experiment. SciPy supplies sparse matrices. scikit-learn supplies SVD, K-means and silhouette. |
| Evaluation | Frozen dev/test catalog, repeatable runs, latency, pooled judgments and quality metrics | Project protocol and metrics. The optional configured provider supplies relevance judgments when enabled. |

This is a map of concepts demonstrated by the implementation. Exact course-rubric compliance remains unconfirmed.

## 9. Architecture and call flow

**Build pipeline.** Pinned source and API collectors save source exports and provenance. `pipeline.preprocess` runs canonicalization, adding IDs, offsets and link edges. `pipeline.build` assembles lexical files, graph ranks and, when configured, dense passages and vectors. It can reuse compatible components. It validates release artifacts and updates the active release pointer. Serving only opens the saved release.

**Search request.** The vanilla JavaScript frontend calls FastAPI's `POST /api/v1/search`. The API validates settings and attaches a local session. `SearchService.search` checks requested options. Auto first lexes enough query syntax to choose the mode, then the shared parser produces scoring text and any hard constraints. The matcher intersects source and topic settings with syntax constraints. The service retrieves lexical or dense candidates, translates passage matches to parent documents, and applies RRF or optional reranking where selected. It selects snippets, highlights offsets, and returns ranked hits, a search ID and a trace. See the [real Promise.all trace](SEARCH_WALKTHROUGH.md).

**Pagination and preview.** Pagination loads a saved result by search ID, session cookie and page/size, and slices that ranking. If the snapshot is unavailable, Search can reissue the query. The Search URL keeps query, source, topic and page. Preview uses the result's document ID and release ID to fetch canonical segments locally. It shows the matched section and nearby blocks, preserving code as text. “Open original” uses the source URL.

**Two interfaces.** Search emphasizes the query and readable results. IR Lab uses the same search service to run two sets of settings, expose score and trace details, and display saved reports. The browser UI uses HTML, CSS and JavaScript. FastAPI handles HTTP and request validation. The Lab distinguishes live comparisons, active build diagnostics and saved experiments.

## 10. Current completion and limitations

- **Verified on the active release.** The installed Windows app serves real Search and Lab results. The 18 captures cover all eight selectable modes across Public Search and Lab, source preview, filtering, per-session voting, and available report states. The release passed deep validation. An extracted demo archive also passed Windows keyword, semantic and hybrid API searches with Python socket access and DNS blocked. That check used existing installed dependencies.
- **Coverage.** The current index has refreshed MDN and a legacy SO snapshot. It omits the newer SO pilot. English/browser scope, exclusions, incomplete link resolution and legacy text boundaries limit coverage. Relevance effectiveness and the dense cutoff remain uncalibrated against a fully judged pool.
- **Platform and delivery.** Historical Linux evidence covers earlier releases. The active desktop screenshots, deep check, and offline bundle were verified on Windows. The active archive has yet to be verified in a fresh disconnected installation or on a different OS. The wheelhouse for a clean offline setup is separate.
- **Pending experiments.** The active manifest has compression and graph build statistics. A saved active-release TAAT/DAAT timing report, full benchmark, judged metrics and the research listed in Section 6 remain pending. Historical lexical runs remain useful as release-specific comparisons.

See the [screenshot guide](SCREENSHOT_GUIDE.md) for capture settings and limitations. The [source map](SOURCE_MAP.md) also notes where current code and evidence refine older architecture descriptions.
