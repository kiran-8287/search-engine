# IR Lab guide

Open [IR Lab](http://localhost:8000/lab) on the local TechSearch server.
Use [Search](http://localhost:8000/) for normal lookups.

## Model comparison

The Lab opens here. The table compares five retrieval methods on the same
queries and indexes.

| Method | What it compares |
| --- | --- |
| TF-IDF | Lexical cosine scores that weight distinctive terms. |
| BM25 | Lexical scores that account for term frequency and document length. |
| Query likelihood | A lexical language model with Dirichlet smoothing. |
| Semantic | Exact similarity search over dense passage vectors. |
| Hybrid | Reciprocal rank fusion of BM25 and Semantic rankings. |

Auto routes a query to a search mode. TAAT and DAAT execute lexical scoring.
Neither is an extra model in the table. Boolean, phrase, prefix, fuzzy and
field constraints continue to work through the search service.

- **nDCG@10** measures ordering in the first ten results. It uses gains
  of `2^grade − 1` and log position discounts. The ideal ranking uses
  the judged pool for that query.
- **Precision@10** is the number of relevant hits divided by ten.
- **MRR@10** is the reciprocal of the first relevant rank within ten,
  or zero if none of the returned top-ten results is relevant.
- **Median** describes a typical measured search time. The **95th
  percentile** describes the slower end of the sample.

Grades range from 0 to 3. Grades 2 and 3 count as relevant for Precision and
MRR. The Lab leaves quality cells blank with a dash until the matching pooled
evaluation is complete. It then labels the judgment source. An observed lead
belongs to this query set and does not establish a general winner.

The server selects a compatible final Test report if one exists, otherwise
it uses Development. It checks the active index ID, frozen query catalog,
benchmark settings, report schema and method definitions. The evaluation
report must match the exact benchmark run. The dashboard rechecks the
current data when you switch tabs or return to the page, and every 30
seconds while the page is visible. Exports keep the technical identifiers.

## Try a query

Enter one query and choose two methods. The Lab shows the first five
results and the search time for each method. Use **Preview** to inspect
source evidence and attribution. **Advanced options** exposes filters
and settings where they apply. Scores and execution details are collapsed.
Individual query times vary, and raw scores use different scales. A single
comparison helps explain behavior, while quality measurements require a
judged query set.

## Course experiments

- **TAAT versus DAAT** compares the same BM25 queries through fresh readers
  over the warmed filesystem. The median and 95th percentile pool the actual
  timed samples. The experiment also checks equal result IDs, order and
  scores. The current report uses six queries and three timed repeats for
  each query and strategy. There is no separate warm-up. The readers share
  the OS file cache, and Python memory tracing is outside the timings.
- **Compression** shows postings payload and complete representation sizes
  in MiB. Complete size includes dictionary metadata. The decode workload
  looks up the same analyzed terms for each codec. Each codec gets one
  untimed lookup batch. Three measured batches per codec use fresh readers,
  and the codec order rotates. Reader setup is outside the timer. The table
  shows the median total time for a batch.
- **Link authority** compares BM25 to the same BM25 run with MDN PageRank
  reranking. The timed comparison uses their common successful queries.
  Graph size and convergence are available in a disclosure.
- **Feedback** shows a Rocchio expansion using the top BM25 hit as a
  controlled input. That hit is omitted from the displayed before and
  after ranks. This demonstrates rank changes without claiming independent
  improvement.
- **LSI and K-means** explores a sample of documents with truncated SVD and
  K-means. The table shows cluster sizes and terms with the largest weights
  in projected cluster centers after excluding common English filler words
  and terms with no letters. This filter applies only to the labels.
  Silhouette is computed on up to 1,000 of the sampled documents and
  measures separation within that sample.

## Generate Lab measurements

Run these commands in the project environment. The benchmark requires an
existing compatible release and the frozen catalog.

```sh
python -m techsearch benchmark --split dev --lab
python -m techsearch evaluate --split dev --lab
python -m techsearch experiments --suite all
```

The Lab benchmark warms each method once, discards those warm-ups, then
records one complete local search per method and query. The method order
is seeded and shuffled for each query. Semantic and Hybrid times include
query encoding. The interval also includes parsing, retrieval, ranking and
snippet construction. HTTP transfer, saved pagination and cold starts are
outside the timing. All five methods use only their common successful queries
for the displayed percentiles. The summary export counts unavailable and
degraded searches. The full saved run records the affected queries and reasons.

Evaluation pools the candidates from all compared methods and reuses
matching judgments. With the default settings it needs judgments through
rank 20, which covers the displayed rank-10 metrics and the pooled recall
cutoff. Run without `--annotate` to check coverage without calling a
provider. Only use provider annotation if authorized and configured.
After settings are final, `benchmark --split test --lab --confirm-sealed`
and `evaluate --split test --lab --confirm-sealed` use the held-out split.

## Current measurements

The 25 November 2026 Development run (`35b15dbf7ed21e49`) used release
`250a15ecd349951d6c69364c` (15,345 documents) and the unchanged frozen
catalog. All five methods and BM25 + PageRank completed all 300 queries
without unavailable or degraded results. Field-scoped prefix searches
now count terms that occur in the requested field and source scope.
The previously rejected `title:Abort* timeout` query expands to four
title terms. The earlier 299-query run is retained as historical evidence.

The older server expected the earlier benchmark format and rejected the
new report. Restarting it loaded the current compatibility checks and
restored the timing table while evaluation remained pending.

| Method | Median (ms) | 95th percentile (ms) |
| --- | ---: | ---: |
| TF-IDF | 121.71 | 1034.80 |
| BM25 | 127.76 | 1142.17 |
| Query likelihood | 138.36 | 1030.80 |
| Semantic | 257.45 | 1115.99 |
| Hybrid | 285.95 | 1364.33 |

TF-IDF had the lowest median time, and query likelihood had the lowest 95th
percentile. These results describe the Development workload on Windows
with one timed pass per method per query after warm-up, a candidate
depth of 150, and up to 100 returned results. The benchmark used
`OMP_NUM_THREADS=2` and `OPENBLAS_NUM_THREADS=1`.
Small differences are observations from this run on this machine.

- On the six-query BM25 traversal workload, TAAT and DAAT agreed on IDs,
  order and scores. The fresh-reader medians were 155.21 ms and 161.70 ms
  over 18 timings per strategy. Their 95th percentiles were 521.73 ms and
  528.69 ms. The median postings visited was 1,821.5 for both.
- Fixed-width took 203.58 MiB, variable-byte 62.30 MiB and gamma 53.83
  MiB including their dictionaries. Gamma saved 73.6% against
  fixed-width. The median batch lookup and decode times were 208.83 ms
  for fixed-width, 296.94 ms for variable-byte, and 1,628.03 ms for gamma.
  Every batch used `===`, `aria-live`, `cors`, `css`, `delegation`, `event`,
  `grid`, `preflight`, `promise.all` and `value`.
- BM25 + PageRank measured 132.62 ms median and 1059.59 ms at the 95th
  percentile over the same 300 queries and BM25 settings. BM25 alone
  measured 127.76 ms and 1142.17 ms. The graph contains 12,597 MDN pages
  and 106,261 edges and converged after 76 iterations.
- The Rocchio demonstration ran on six queries. The LSI sample used
  2,500 documents, 48 dimensions and 12 clusters. Its sampled
  silhouette was 0.103. The sample and cluster assignments match the earlier
  report. The label for the SVG cluster now uses `svg`, `element`,
  `animated`, `filter` and `attribute`.

**Relevance evaluation is pending.** The matching pool has 12,080
unjudged query/document pairs and zero cached judgments. Both the
annotation key and model are unset. No provider calls were made and
the held-out Test set was left sealed. The speed measurements and rank
changes cannot establish which method is more relevant.

The summary and course reports are under
`artifacts/reports/250a15ecd349951d6c69364c/`. The full run and ranked
CSV export are under `artifacts/runs/250a15ecd349951d6c69364c/`.

## Screenshots

- [Model comparison](../artifacts/execution/lab-measurements/model-comparison.png)
- [Try a query](../artifacts/execution/lab-three-tabs/lab-try-query.png)
- [Course experiments](../artifacts/execution/lab-measurements/course-experiments.png)

The [browser verification record](../artifacts/execution/lab-three-tabs/app-verification.json)
includes the live Semantic/Hybrid comparison, Search checks, and report
export checks.

## API and exports

`GET /api/v1/lab` resolves current measurements. The existing reports,
benchmarks, and ranking exports are still available. Use the explicit
`release` parameter on supported report endpoints for archived research.
Archived measurements stay outside the Lab dashboard. The Lab exports
the matching `lab-dev` or `lab-test` report via its Measurement details.

## Try a search

Type `Promise.all` in Search and open **Preview** on a result. Try `"event bubbling"` for a phrase or `source:mdn title:promise` for a field constraint. In IR Lab, use **Try a query** to compare BM25 with TF-IDF. With a dense release, compare Semantic and Hybrid on `wait for several JavaScript promises to finish`.

The same service is available from the terminal.

```sh
python -m techsearch search "title:Promise.all" --mode field
```

## Tests, experiments, and evaluation

Run these commands after [setting up and activating the project environment](../README.md#set-up-and-run).

### Tests and release checks

Units and integrations use synthetic input and mocked collection calls. Browser tests use a temporary fixture release and loopback server. They can run without preparing a real corpus.

```sh
python -m pytest tests/unit tests/integration
python -m playwright install chromium
python -m pytest tests/browser -m browser
```

If you skipped test dependencies, install them first with `python -m pip install -e ".[test]"`. On Linux, Chromium may need system libraries. Where your platform supports it, use `python -m playwright install --with-deps chromium`. You can also point pytest at a compatible installed Chromium with `--browser-executable=/path/to/chromium`. [Playwright browser setup](https://playwright.dev/python/docs/browsers)

On a real build, run either of the following checks. After launching a dense release, optionally run `python scripts/verify_app.py --base-url http://localhost:8000` in a second terminal. It checks API and browser behavior, saves screenshots and JSON under `artifacts/execution/browser/`, and uses separate session feedback for the smoke test.

```sh
python -m techsearch validate-release
python -m techsearch validate-release --deep
```

### Offline experiments and benchmarks

Run these after setup when you want to measure performance on your release. They can take time. IR Lab can display the resulting release-specific JSON reports.

```sh
python -m techsearch experiments --suite compression
python -m techsearch experiments --suite taat-daat
python -m techsearch experiments --suite retrieval
python -m techsearch experiments --suite latent
```

- **Compression** measures the fixed-width, variable-byte, and gamma postings formats. **TAAT/DAAT** compares term-at-a-time and document-at-a-time execution and their rankings.
- **Retrieval** probes implemented rankers and options such as likelihood, PageRank, diversity, and Rocchio feedback. **Latent** runs sampled latent semantic indexing and K-means with the `research` extra. Use `--suite all` to run the four suites together.
- Each run writes the latest report and a versioned copy to `artifacts/reports/<release-id>/`. The [graph diagnostic command](PROJECT_CONTEXT.md#build-from-raw-exports) saves a separate report.

To run a benchmark and save its results, first freeze the authored query catalog. Start with the development split. The Test split is held out for final measurements.

```sh
python -m techsearch freeze-evaluation
python -m techsearch benchmark --split dev
python -m techsearch benchmark --split dev --ablations
```

`freeze-evaluation` checks the authored query catalog and writes `data/evaluation/frozen.json` with 300 development and 300 test intent groups. It reuses matching frozen groups. The baseline benchmark times Auto, BM25, Semantic, and Hybrid. Dense methods are recorded as unavailable for a lexical-only release. `--ablations` adds TF-IDF, likelihood, graph authority, and diversity comparisons. Runs and reports go under `artifacts/runs/<release-id>/` and `artifacts/reports/<release-id>/`. A rerun measures again. After finalizing settings, use `python -m techsearch benchmark --split test --confirm-sealed` with the same ablation choice.

### Optional judged relevance

A benchmark measures execution and saves rankings. It does not supply judgments. Evaluate the matching saved run for the active release.

```sh
python -m techsearch evaluate --split dev
```

That command uses existing judgments and reports missing pairs. New annotation is an explicit network operation. Only run the following after configuring your annotation key and a model from the configured provider, and when you intend to send pooled excerpts and incur any provider charges.

```sh
python -m techsearch evaluate --split dev --annotate --limit 50
```

`--limit` caps newly judged candidate pairs per invocation. Audit or adjudication can make extra requests per pair. The command caches judgments under `data/evaluation/annotations/` so a rerun can resume the pool. Use the same `--ablations` flag as the benchmark when applicable. For held-out evaluation after finalizing settings, use `python -m techsearch evaluate --split test --confirm-sealed`. A blocked or partial run can return exit code 2 and still write status. Metrics such as nDCG and MRR become available when the pool is judged. Read pending reports as unavailable. A numeric zero is a measured value. Search feedback stays in `data/runtime/` and does not become a benchmark judgment.

## Earlier verification captures

These earlier captures document the former Lab layout on saved releases. The historical examples were opened through the archive selector.

| Section or state | Screenshot |
| --- | --- |
| Overview | [Active index and report status](../artifacts/execution/lab-navigation/lab-overview.png) |
| Compare searches | [Method settings](../artifacts/execution/lab-navigation/lab-comparison.png) · [Live results and exports](../artifacts/execution/lab-navigation/lab-comparison-results.png) |
| Speed & execution | [Active availability](../artifacts/execution/lab-navigation/lab-speed.png) · [Historical benchmark](../artifacts/execution/lab-navigation/lab-historical-speed.png) |
| Compression | [Postings sizes and timing availability](../artifacts/execution/lab-navigation/lab-compression.png) |
| Link analysis | [MDN graph and PageRank](../artifacts/execution/lab-navigation/lab-links.png) |
| Topics & clusters | [Active sample availability](../artifacts/execution/lab-navigation/lab-topics.png) |
| Evaluation | [Active relevance status](../artifacts/execution/lab-navigation/lab-evaluation.png) · [Historical execution and blocked relevance](../artifacts/execution/lab-navigation/lab-historical-evaluation.png) |
| Small screens | [Mobile section selector](../artifacts/execution/lab-navigation/lab-mobile.png) |

The [real-app verification record](../artifacts/execution/lab-navigation/app-verification.json) lists exercised search modes, API checks, report status, and browser errors.
