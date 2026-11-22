# One complete search walkthrough

This trace is for typing `Promise.all` on the real Search homepage and pressing Enter. It corresponds to [02-query-entered](screenshots/02-query-entered.png), [03-search-results](screenshots/03-search-results.png), and [04-source-preview](screenshots/04-source-preview.png), all on release `250a15ecd349951d6c69364c`. The browser supplied the request, trace, top three results, snippets, and Preview response. A read-only local replay and index inspection supplied document numbers, the rest of page 1, and per-field score calculations. The replay matched the captured top three titles and scores.

## 1. Browser input and API request

The starting page is `/`. Typing fills the Search field. The app requests suggestions separately, and the API returned `promise.all`, `promise.allkeyed`, `promise.allsettled` and `promise.allsettledkeyed`. Suggestions do not submit a search. Pressing Enter sends a JSON POST to `/api/v1/search`:

```json
{
  "query": "Promise.all",
  "source": null,
  "topic": null,
  "page_size": 10,
  "apply_feedback": false
}
```

The UI leaves out `mode`, `ranker`, and `strategy`. The API defaults them to `auto`, `bm25`, and `taat`. The response has a random search ID and the app uses a session cookie to save and revisit that ranking. The public search URL records the query.

## 2. Router, parser, and constraints

`service.auto_mode` sees a dotted API identifier and selects **Keyword**. The observed trace rule was `API identifier or operator`, with router version `rules-v1`. The lexer yields one word, `Promise.all`. The parser returns one unfielded scoring atom for that word. There is no Boolean, phrase, prefix, source, topic, or other hard constraint. The trace shows `constraint: null` and **15,345 eligible parents** before term matching.

The lexical analyzer yields `promise.all` at character range `[0, 11)`, with the analyzer aliases `all` and `promise`. For this query, `Matcher.scoring` produced only `("promise.all", no field) → 1.0`. The aliases can be indexed on documents. They were not additional query terms here.

## 3. Retrieval, candidates, and scoring

Only the lexical branch ran. It used the live VB postings and forward length statistics. The posting for `promise.all` had document frequency **57** (57 parents) and collection frequency **202** (202 indexed occurrences). The trace recorded 57 postings visited, 79 scored field contributions and 57 peak score accumulators. The ranker used `k1=1.2`, `b=0.75`, and candidate depth 150. The snapshot contained **57** results and page 1 showed 10.

The first result, document `11823` (`mdn:web/javascript/reference/global_objects/promise/all/index.md`), got the following contributions from the single matched term. The stored posting and field lengths allow the four contributions to be calculated independently with the repo's BM25 formula. The public explanation reports their sum for the term.

| Field | Indexed term count in this field | Field length in original tokens | Field weight | Score contribution |
| --- | ---: | ---: | ---: | ---: |
| Title | 1 | 1 | 3.0 | 24.151139 |
| Heading | 4 | 29 | 1.6 | 11.850717 |
| Body | 16 | 724 | 1.0 | 10.526945 |
| Code | 18 | 801 | 1.25 | 10.255365 |
| Total | 39 | | | 56.784165 |

The term's BM25 inverse document frequency was about 5.586825. The matched text at the top is an outcome of the saved term statistics and settings. It does not establish a relevance grade.

## 4. Passage aggregation, fusion, and reranking

Keyword retrieval already works on parent document IDs. This request had no dense branch, so no passage-to-parent aggregation or dense cutoff was used. Its result has `dense_passage: null`. In Semantic or Hybrid, `exact_parent_hits` keeps the highest qualifying passage score for each eligible parent. Hybrid can then fuse the two parent lists with RRF.

This trace has no fusion, no fallback, no warnings, no query expansions, and an empty reranking list. Feedback refinement, MDN authority and MMR were inactive.

## 5. Final order on page 1

Scores are rounded to six decimals. Integer document numbers belong to this release and can change in a new corpus build.

| Rank | Document number | Stable ID | Title | BM25 score |
| ---: | ---: | --- | --- | ---: |
| 1 | 11823 | `mdn:web/javascript/reference/global_objects/promise/all/index.md` | Promise.all() | 56.784165 |
| 2 | 13890 | `so:30362733` | Handling errors in Promise.all | 23.476296 |
| 3 | 11338 | `mdn:web/javascript/reference/global_objects/array/fromasync/index.md` | Array.fromAsync() | 19.310129 |
| 4 | 14383 | `so:45285129` | Any difference between await Promise.all() and multiple await? | 19.002988 |
| 5 | 11824 | `mdn:web/javascript/reference/global_objects/promise/allkeyed/index.md` | Promise.allKeyed() | 15.575506 |
| 6 | 1091 | `mdn:web/api/absoluteorientationsensor/index.md` | AbsoluteOrientationSensor | 13.849080 |
| 7 | 5379 | `mdn:web/api/orientationsensor/index.md` | OrientationSensor | 13.813805 |
| 8 | 5963 | `mdn:web/api/relativeorientationsensor/index.md` | RelativeOrientationSensor | 13.810171 |
| 9 | 1134 | `mdn:web/api/animation/finished/index.md` | Animation: finished property | 10.994755 |
| 10 | 1545 | `mdn:web/api/cachestorage/keys/index.md` | CacheStorage: keys() method | 9.649894 |

The trace exposes aggregate work and the explanations for returned hits. It does not list the order of internal dictionary updates or every intermediate candidate. The posting count directly establishes term membership in this one-term query.

## 6. Snippet selection and Preview

`SearchService.hit` gathers character matches by segment, prefers matching content outside the title, and breaks equal evidence scores by earlier segment order. The top hit selected **segment 1**, a body paragraph at the start of the page, with `promise.all` as the matched term. The posting marks characters `[4, 15)` in that segment. This is why the snippet starts with “The” followed by highlighted “Promise.all”. The remaining text is normal source text, with an ellipsis for truncation. The title still contributes to ranking.

Clicking the top result's **Preview** called `GET /api/v1/documents/{stable}?release=250a15ecd349951d6c69364c` with that stable ID URL-encoded. The app returned the saved canonical document and source segments. The browser matched ordinal 1, showed the introductory excerpt and nearby text, and displayed the JavaScript demo as code. Section navigation came from actual heading paths. The contributor and source information come from the stored document. “Open original” links to [the MDN page](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all). The local preview did not fetch the live page.

## Toy example for teaching only

The three made-up documents below are separate from the corpus. The chosen document numbers make gaps easy to see.

| Toy ID | Text and zero-based positions | Forward record giving each term's frequency |
| ---: | --- | --- |
| 0 | `promise₀ resolves₁ promise₂` | `promise: 2, resolves: 1` |
| 2 | `resolve₀ promise₁ error₂` | `resolve: 1, promise: 1, error: 1` |
| 5 | `promise₀ error₁` | `promise: 1, error: 1` |

A **forward record** answers “What terms does document 0 contain?” The **inverted postings** answer “Where does this term occur?” Inverting the table gives:

| Term | Document IDs and token positions | Document frequency |
| --- | --- | ---: |
| `promise` | `0:[0,2], 2:[1], 5:[0]` | 3 |
| `error` | `2:[2], 5:[1]` | 2 |
| `resolve` | `2:[0]` | 1 |
| `resolves` | `0:[1]` | 1 |

Term frequency is local to a document. In document 0, the term frequency of `promise` is 2. Document frequency counts documents, so repetitions do not raise it. The phrase `"promise error"` matches documents 2 and 5 because `error` is one position after `promise` in both. The two spellings `resolve` and `resolves` are separate terms.

The sorted document IDs for `promise` are `[0, 2, 5]`. With the project's initial previous value `−1`, their **gaps** are `[1, 2, 3]`. Decoding adds the gaps to the previous ID in order: `−1 + 1 = 0`, `0 + 2 = 2`, and `2 + 3 = 5`. VB and gamma encode these small integers compactly. The fixed-size codec stores the IDs directly. The actual binary format also includes counts, field IDs, positions, character offsets and original-token flags.
