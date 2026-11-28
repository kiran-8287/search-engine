# Groq Free Development study

The `groq-dev50` profile uses the frozen Development catalog and the saved rankings for the active release. It selects four groups from each class and one extra from each of two classes with seed 2741. The extra classes are CSS/HTML and no-match. The profile records all 50 IDs in catalog order. [Frozen profile](../data/evaluation/groq-dev50.json)

The union of the six methods' top ten contains **1,085 unique pairs** from **2,703 entries**. All 50 queries have at least one candidate in the union. An individual method can still return no results. The fixed pilot has 50 pairs, spans all 12 classes, and contains 25 MDN and 25 Stack Overflow pairs. [Selection and coverage evidence](../artifacts/execution/groq-dev50/preflight.json)

Grades range from 0 to 3. Grades 2 and 3 count as relevant for Precision@10 and MRR@10. Precision divides by ten. The ideal ranking for nDCG@10 comes from the shared judged pool, with gains of `2^grade - 1` and log position discounts. The three metrics require complete top-ten pool coverage, and an empty successful result list gets measured zeros once evaluation is complete. The study does not report Recall@20. The full Development pool and the sealed Test split are outside this study.

## Current 50-query timings

The saved 300-query run lacked per-query durations. The study remeasured the same 50 queries with all six configurations in one process, with one untimed warm-up per method. Every measured top ten matched the corresponding saved ranking. The original 300-query timing report remains separately exportable.

| Method | Median ms | p95 ms | nDCG@10 / Precision@10 / MRR@10 |
| --- | ---: | ---: | --- |
| TF-IDF | 162.19 | 1,977.39 | Unavailable |
| BM25 | 189.74 | 1,860.62 | Unavailable |
| Query likelihood | 158.41 | 1,710.47 | Unavailable |
| Semantic | 365.08 | 1,630.48 | Unavailable |
| Hybrid | 410.57 | 2,415.35 | Unavailable |
| BM25 + PageRank | 184.23 | 1,706.17 | Unavailable |

Query likelihood had the lowest observed median. Semantic had the lowest observed p95. Quality–speed trade-offs remain unknown.

## Pilot outcome on 28 November 2026

Groq listed `openai/gpt-oss-120b` for the configured key, and the pilot responses came from that model. Live response headers reported **1,000 requests per day** and **8,000 tokens per minute**. The final response showed 943 daily requests and 1,485 minute tokens remaining. The headers do not expose a daily token limit. [Groq rate headers](https://console.groq.com/docs/rate-limits#rate-limit-headers)

The run saved **50 provisional grades** in **69 generation attempts** under the 75-attempt cap. Initial pacing encountered short minute-limit responses. Header-based pacing resumed the cached pilot and completed the remaining 32 pairs in 35 calls with zero retries. Groq reported 40,842 prompt tokens and 9,565 completion tokens across 58 responses. The remaining 1,035 pairs are unjudged.

AI review confirmed saved pair identity and evidence for all 50 records, then checked representative rationales and all six audited pairs. Counts by grade were 25 at 0, three at 1, six at 2, and 16 at 3. One audit disagreed with the primary grade. The answer about a SortableJS spacer ignored the unmatched term `vulnexo`. The primary gave 3, the audit gave 0, and adjudication gave 0.

**The pilot failed AI review.** An HTML void-elements answer received 2 for the JavaScript `void 0` query. A website-hijacking answer received 2 for shipping an offline-capable site because it mentioned browser caching. An unrelated view-transition example received 3 for calling `document.querySelector` without explaining it. Code checking `complete` and `naturalWidth` supported the grade of 3 for diagnosing broken images. The pilot grades remain provisional and all three relevance metrics are unavailable. [Pilot review record](../artifacts/execution/groq-dev50/pilot-review.json)

V2 used 57 additional attempts and 73,935 reported tokens to complete its 50-pair pilot. AI review found unsupported grades and an adjudication that missed a phrase present in its evidence. The offline human review now covers all 1,085 pairs from the 50-query study. [V2 review](../artifacts/execution/groq-dev50/v2-pilot-ai-review.json) · [Study review instructions](GROQ_V3.md)

## Groq Free pilot and resumption

Confirm the selected organization is on Groq Free in the Groq Console. Add `GROQ_API_KEY` privately in local `.env` and set `TECHSEARCH_GROQ_FREE=1` after confirming the plan. The existing `TECHSEARCH_ANNOTATION_API_KEY` setting also works when its format, configured endpoint, and configured model match the Groq profile. The profile pins `openai/gpt-oss-120b`. See [Groq billing](https://console.groq.com/docs/billing-faqs), [account rate limits](https://console.groq.com/docs/rate-limits), and the [API reference](https://console.groq.com/docs/api-reference).

The judge uses the Groq HTTPS Chat Completions endpoint, strict JSON schema, low reasoning effort, hidden reasoning content through `include_reasoning=false`, and a 512-token completion bound. It gets the query, source metadata, and text or code evidence without method, rank or score. The client checks the returned model, pair identity, rationale, grade, and finish status. Insufficient evidence stays pending. See [Groq structured outputs](https://console.groq.com/docs/structured-outputs) and [GPT-OSS reasoning settings](https://console.groq.com/docs/reasoning).

The following commands document how the pilot runs from the project environment. The current v1 pilot is already complete, and its rejection blocks full judging.

```sh
python -m techsearch evaluate --split dev --lab --profile groq-dev50 --check-model
python -m techsearch evaluate --split dev --lab --profile groq-dev50 --annotate --pilot --limit 50 --max-requests 75
```

The 75-attempt pilot ceiling persists across runs. Inspect the saved pair records in `data/evaluation/annotations/`. Check representative exact API, conceptual, code, Boolean, field, no-match and related-only cases against the shown evidence. Record the actual reviewer's type only after checking the pilot. Automated and IDE-agent review are AI review.

```sh
python -m techsearch evaluate --split dev --lab --profile groq-dev50 --pilot-review AI
python -m techsearch evaluate --split dev --lab --profile groq-dev50 --annotate --limit 200 --max-requests 250
```

Use `human` in the review command only if a human performed the review. If a passing run pauses for quota, retry the same phase command after a quota reset with the same key and model. The ceiling is 4,000 total generation attempts across the study, including pilot, audits, adjudication and retries. The provider records usage and stops on daily or ambiguous quota exhaustion. The 300-query timing and quality workflows remain separate.
