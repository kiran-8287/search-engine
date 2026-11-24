# TechSearch simplification report

This refactor makes the data and control flow easier to follow while keeping the existing project structure. The [code map](CODE_MAP.md) is a reading guide for someone learning the implementation.

## What changed

| Area | What made it hard to follow | How to read it now |
| --- | --- | --- |
| Lexical ranking | Six-position tuples mixed query settings, frequencies, and posting lists. Two traversals and several formulas sat inside one function. | Read `QueryPosting` for the inputs, then the BM25 and TF-IDF calculations. `term_at_a_time` walks one term's list at a time. `document_at_a_time` separately merges lists in document order using a heap. Both share the same term contribution. |
| Query and search | Phrase-position checks were nested inside a comprehension. The search method mixed retrieval and source excerpt formatting. | `Matcher.phrase_documents` builds possible starting positions and intersects them. `SearchService.search` validates and prepares a query, `retrieve_candidates` runs the branches, and `source_excerpt` formats the evidence. |
| Collection and indexing | Alias resolution, reference mapping, forward records, and checkpoint coverage were embedded in long build or collection functions. | Read `build_aliases`, `parent_references`, `forward_records`, and `stackoverflow_coverage` as separate steps. The root collectors still handle acquisition and resumability. |
| Codec and dense algorithms | Bit packing, decoding, and posting assembly shared one block. Dense loops used short positional names for tokens, passages, and parents. | Named VB and gamma functions show what each codec does. The posting reader validates each five-value position. Dense code labels token-window boundaries and keeps NumPy batch scoring. |
| Graph and experiments | Link construction and the connected-component walk were intertwined. MMR and LSI calculations used dense expressions for several distinct steps. | Read graph construction, component sizing, and PageRank separately. MMR names the base relevance and maximum overlap. The latent experiment shows the sparse matrix, SVD projection, and K-means steps in order. |
| Feedback and metrics | Short names and nested set expressions obscured which results could affect a query or a measurement. | Rocchio names the normalized term weights and expansion terms. Pooling explicitly includes successful runs, and the metric calculations name their cutoffs and denominators. |
| Browser | History recovery, pagination, local feedback and rendering were interleaved with request callbacks. | Named functions handle snapshot pages, feedback, result reset, snippets and preview blocks. The Lab's Search link can restore the previous query and filters even when its comparison script is delayed or blocked. |

### Before and after

**TAAT traversal.** The original loop needed knowledge of the tuple layout.

```python
for row in rows:
    for doc, fields in row[5].items():
        score = contribution(doc, fields, row)
        if score:
            scores[doc].append((row[0], score))
```

The posted documents and the term now have names at the point they are used.

```python
for posting in postings:
    for document_id, fields in posting.documents.items():
        score = contribution(document_id, fields, posting)
        if score:
            scores[document_id].append((posting.term, score))
```

**Phrase constraints.** The original matcher created a list of position sets in a nested comprehension and intersected them at the end. The current loop expresses the same test one word at a time. The offset is the word's position in the phrase.

```python
if original:
    starts.add((field, segment, position - offset))

if common_starts is None:
    common_starts = starts
else:
    common_starts.intersection_update(starts)
if not common_starts:
    break
```

**Snapshot paging.** The original `getResults` created a local request function and computed the page bound inline.

```javascript
const stored = await pageFrom(searchId, view.page);
const last = Math.max(1, Math.ceil(stored.total / stored.page_size));
return stored.page > last ? await pageFrom(searchId, last) : stored;
```

`snapshotPage` now builds the request, and `lastPage` supplies the bound to fetch and render code. A missing snapshot still falls back to running the query again.

```javascript
const stored = await snapshotPage(searchId, view.page, signal);
const last = lastPage(stored);
if (stored.page > last) return await snapshotPage(searchId, last, signal);
return stored;
```

## Complexity kept for a reason

- The Boolean parser uses recursion because the query has a tree structure. Phrase safety and field, segment, and token positions preserve the difference between an exact phrase and a group of terms.
- The DAAT heap, external sort for postings, byte-offset readers, and NumPy memory mapping bound how much data the app has to process or load at once. The three custom codecs still use their existing bit layouts and corruption checks.
- Release staging, atomic activation, hashes, source provenance, and the collection checkpoint and quota logic protect saved data. FastAPI's input models and search work limits guard the entry points.
- Dense encoding, sparse matrix math, and statistical routines still use the existing libraries. Ranking retains exact dense similarity, parent aggregation, RRF, BM25, TF-IDF, Dirichlet likelihood, PageRank, Rocchio, MMR, LSI, and K-means.
- Browser session IDs, request cancellation, modal focus, and text-only source rendering preserve isolation, accessible navigation, and safe previews.

## Verification

Git status was clean on `main` at intake. The baseline suite reported **48 passed and 1 failed**. The failure was the existing Chromium Search-to-Lab return test. It could follow the default home link while Lab's JavaScript was still loading. The refactor adds a fallback link that Search resolves before rendering, plus a regression test that blocks the Lab script on purpose. The original assertions stayed in place.

| Check | Actual result |
| --- | --- |
| Ranking module, then query/service changes | 25 focused tests passed for the ranking module. After the query and service work, all 27 algorithm, release, and dense repository tests passed. |
| Codecs, dense, graph, and experiments | The same 27 tests passed after this group. |
| Browser fixtures | 7 passed, including the blocked-Lab-script case. |
| Data and evaluation fixtures | 43 unit and integration tests passed. Reading the saved Stack Overflow checkpoint reproduced all nine saved coverage fields. The old list format gave the same result as the keyed format. |
| Final full suite | **50 passed** in 25.25 seconds. Two dependency deprecation warnings were reported. |
| Real release validation | Standard and deep validation passed for `250a15ecd349951d6c69364c`, including the saved positions in all three codecs and dense source spans. |
| Real browser smoke | Chromium 159 passed Search, pagination, source preview and attribution, MDN filtering, feedback and refinement, Semantic/Hybrid Lab comparison, and return navigation. The smoke used a temporary loopback server and isolated runtime storage. |

The search comparison covered the requested `Promise.all`, `promise AND error`, `"event bubbling"`, `querySelec*`, `addEventListner` in Fuzzy mode, `source:mdn title:promise`, and the conceptual query `wait for several JavaScript promises to finish` in Semantic and Hybrid. It also covered a combined source/topic filter, BM25 and TF-IDF with both traversals, query likelihood, authority with MMR, a filter-only search, and a negative Boolean search.

All 16 searches matched the clean baseline exactly on the same release. The comparison excluded generated search IDs and elapsed times. It kept result IDs, order, numeric scores, snippets, evidence, warnings, and the rest of the trace. BM25 and TF-IDF each produced the same ordered scores with TAAT and DAAT. Six sampled terms in each of the three codecs round-tripped to identical positions and reproduced the saved bytes. The two versions also agreed on all 46 text windows and source spans for the sampled MDN and Stack Overflow parents, and on a 32-document LSI/K-means sample with six dimensions and four requested clusters.

### Small performance check

Separate before/after runs varied enough to warrant a closer check on `Promise.all`, the Boolean query, and CSS ranking. A follow-up alternated the baseline and refactored code in one process, using the same saved artifacts. Each number is the median wall-clock time of 12 warm searches.

| Case | Before | After |
| --- | ---: | ---: |
| `Promise.all` | 17.09 ms | 16.87 ms |
| `promise AND error` | 93.46 ms | 86.33 ms |
| `CSS grid`, Keyword | 109.12 ms | 97.44 ms |
| `CSS grid`, authority and MMR | 147.13 ms | 137.13 ms |

The first apparent slowdowns did not repeat in the alternating check. In the separate processes across all 16 cases, including dense search, the observed peak working set was about 895 MiB in both versions. These are smoke measurements on this Windows workspace. They cover warm searches and a small sample of cases.

## Remaining difficult areas

The main learning gaps are the codec bit buffers, Boolean operator precedence, byte and token offsets, dense cache validation, collector resumption, and pooled relevance evaluation. Each combines an algorithm with an important correctness rule. The code map points to a small entry point for each area. The existing corpus, releases, and vectors were reused for the real-data checks.
