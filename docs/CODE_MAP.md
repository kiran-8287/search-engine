# TechSearch code map

Start with `SearchService.search` and follow one simple query such as `Promise.all`. The [search walkthrough](pdf-evidence/SEARCH_WALKTHROUGH.md) gives real inputs and results for that query. The [architecture notes](MASTER_ARCHITECTURE.md) explain how the build and serving stages fit together.

## A search request

| Step | Where to read | What to look for |
| --- | --- | --- |
| Browser on Search | [search.js](../frontend/assets/js/search.js) `submit`, `navigate`, `getResults`, `render` | Read the query and filters, request or reuse a ranked snapshot, and display the page. |
| Browser on IR Lab | [lab.js](../frontend/assets/js/lab.js) `options`, `panel`, `showLab` · [lab-reports.js](../frontend/assets/js/lab-reports.js) `renderReports` | Send two sets of search settings, restore navigation and render saved reports for the selected release. |
| Shared browser code | [shared.js](../frontend/assets/js/shared.js) `api`, `resultItem`, `createPreview` | Make local requests, render safe text nodes, and display matched source material. |
| API | [api.py](../src/techsearch/api.py) `SearchRequest`, `create_app` | Validate inputs and attach a session ID. The Search and Compare routes call the same service. |
| Search service | [service.py](../src/techsearch/service.py) `SearchService.search`, `retrieve_candidates`, `lexical_evidence`, `source_excerpt` | Validate options, find eligible parents, run the requested branches, then build results with snippets and provenance. |
| Query syntax | [query.py](../src/techsearch/query.py) `lex`, `parse`, `Parser.expression`, `Matcher.match`, `phrase_documents`, `prefix`, `fuzzy` | Read operators and terms, preserve Boolean precedence, and find original adjacent positions for phrases. |
| Lexical scores | [retrieval.py](../src/techsearch/retrieval.py) `lexical`, `bm25_contribution`, `tfidf_contribution`, `likelihood` | Read term and frequency statistics, then score each match. |
| Ranking order | [retrieval.py](../src/techsearch/retrieval.py) `term_at_a_time`, `document_at_a_time`, `fuse` | TAAT visits one term at a time. DAAT merges lists by document ID with a heap. RRF combines the lexical and dense ranks. |
| Dense similarity | [dense.py](../src/techsearch/dense.py) `Dense.rank`, `exact_parent_hits` | Encode the query, score eligible passage vectors in blocks, and keep the best passage per parent. |
| Optional ranking steps | [feedback.py](../src/techsearch/feedback.py) `Runtime`, `rocchio` · [graph.py](../src/techsearch/graph.py) `rerank_slots` · [experiments.py](../src/techsearch/experiments.py) `mmr` | Session votes can change the query before scoring. Authority and diversity can change the order after scoring. |

## From exports to a release

| Step | Where to read | What to look for |
| --- | --- | --- |
| Collection | [collection.py](../src/techsearch/collection.py) `collect`, `stackoverflow_coverage` · [MDN collector](../collect_mdn.py) · [Stack Overflow collector](../collect_stackoverflow.py) | Keep source evidence, scope checks, and checkpoint progress. |
| Canonical corpus | [corpus.py](../src/techsearch/corpus.py) `normalize`, `build_corpus`, `build_aliases`, `parent_references` | Admit records, assign stable and integer IDs, resolve aliases, and retain original source links. |
| Tokenization | [preprocessing.py](../src/techsearch/preprocessing.py) `analyze` · [indexing.py](../src/techsearch/indexing.py) `analyze_parent` | Preserve identifiers, operators, aliases, and position information. |
| Lexical files | [indexing.py](../src/techsearch/indexing.py) `write_postings`, `forward_records`, `build_indexes` · [compression.py](../src/techsearch/compression.py) `encode`, `decode`, `pack_postings`, `unpack_postings` | Sort positions into posting lists, write per-document counts and lengths, and encode the same postings three ways. |
| Dense and graph files | [dense.py](../src/techsearch/dense.py) `chunk_rows`, `build_dense` · [graph.py](../src/techsearch/graph.py) `build_graph`, `component_sizes`, `pagerank` | Preserve source spans for passage windows and follow links within the MDN graph. |
| Activation and access | [pipeline.py](../src/techsearch/pipeline.py) `preprocess`, `build`, `open_release`, `validate_postings` · [repository.py](../src/techsearch/repository.py) `ByteRecords`, `Documents`, `Passages` | Verify artifacts and activate a release. Seek to records by byte offset and map dense data without reading everything into memory. |

## Measuring the project

- [experiments.py](../src/techsearch/experiments.py) contains `execution_report`, `compression_report`, `retrieval_report`, and `latent_report`. Start with `latent_report` to see how sampled sparse TF-IDF rows become LSI vectors and then K-means groups.
- [evaluation.py](../src/techsearch/evaluation.py) contains `benchmark`, `pool_for`, `evaluate`, and `scores`. Benchmark timings and relevance judgments are separate inputs.
- [cli.py](../src/techsearch/cli.py) contains the command entry points. [default.yaml](../config/default.yaml), [scope.yaml](../config/scope.yaml), and [evaluation.yaml](../config/evaluation.yaml) contain project settings.
- [Tests](../tests/) cover algorithms, local fixture releases, API behavior, and browser interactions. The [implementation status](IMPLEMENTATION_STATUS.md) identifies checks on the real active release and work that is still pending.
