# IR Lab guide

Open [IR Lab](http://localhost:8000/lab) on the local TechSearch server. Pick a section from the left navigation or the **Lab section** selector on a small screen. Back and Forward restore the section, report release, split, and evaluation view. The tab also remembers the comparison query and compatible settings, including when you visit Search and return.

## Where the old tabs went

| Previous tab | New location |
| --- | --- |
| Index | **Overview** · active index counts, component availability and release file sizes |
| TAAT / DAAT | **Speed & execution** · term-at-a-time and document-at-a-time |
| Dev benchmark | **Speed & execution** · Development |
| Test benchmark | **Speed & execution** · Test |
| Compression | **Compression** · posting sizes and any saved lookup/decode measurements |
| Graph | **Link analysis** · graph and PageRank statistics, plus saved authority comparisons |
| Rankers / feedback | **Compare searches** · expand **Saved ranker & feedback experiments** |
| LSI / K-means | **Topics & clusters** · academic sample and cluster diagnostics |
| Dev metrics | **Evaluation** → **Relevance** · Development |
| Test metrics | **Evaluation** → **Relevance** · Test |
| Dev ablations | **Evaluation** → **Feature comparisons** · Development execution |
| Test ablations | **Evaluation** → **Feature comparisons** · Test execution |
| Dev ablation metrics | **Evaluation** → **Feature comparisons** · Development relevance |
| Test ablation metrics | **Evaluation** → **Feature comparisons** · Test relevance |

**Compare searches** runs both methods live on the active release. It keeps eight modes, lexical rankers, TAAT/DAAT, filters, parameters, source previews, explanations, traces, and export links. Expand **Authority & diversification** inside a method to enable those rerankers. The saved experiments below the live results include the Rocchio query-expansion probe. Session feedback remains available on Search. Live timings describe one run, and scores from different rankers use different scales.

## Reading reports

Overview always describes the active index. Other sections let you choose an archive under **Saved report release** when one exists. Archive panels carry a prominent **Historical release** label and the full release ID. An unavailable archive report leaves that panel empty of measurements. Release-specific exports identify the selected release in their JSON and filename. Saved reports display the configuration fingerprint and provide their recorded configuration.

- **Build statistics** come from the active release manifest. Compression shows postings payload, dictionary bytes, and their sum. The size of the complete release is separate and excludes the model, source exports, manifest, and reports.
- **Saved reports** belong to their recorded release and settings. A successful saved TAAT/DAAT report verifies equal IDs, order and scores for its workload. That workload is independent of the Development/Test selector.
- **Not generated** means no matching saved report exists for that release. The panel lists the applicable CLI command for the active release. Lab only reads these reports.
- **Blocked or incomplete** means relevance metrics are unavailable. Any pending count refers to judgments still needed for that release, split, and run. Execution results such as latency can still exist.

Use **Evaluation → Protocol & status** for the frozen query catalog counts and the status of each selected split. Use Development to choose settings. Finalize them before using Test. The existing benchmark and evaluation commands still require `--confirm-sealed` for Test. The Lab can read saved Test reports, and opening the selector does not run those commands.

## Current release

The active release `250a15ecd349951d6c69364c` supplies the index summary, compression sizes, and MDN link graph. Its saved decode timings, TAAT/DAAT report, benchmarks, authority and feedback experiments, latent sample, and evaluation and feature comparison reports have yet to be generated.

Select historical release `6f86fc58d97fad8a0c0ec387` to see its saved Development benchmark and feature comparison execution. Its Development feature comparison relevance report is blocked. Both `6f86fc58d97fad8a0c0ec387` and `a585b9035a3c6cd217a93cbb` have saved traversal, compression, retrieval, and latent experiment results. This workspace has no saved Test measurements.

## Screenshots

These captures use the real saved releases. The historical examples were opened through the archive selector.

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

## API

`GET /api/v1/report-inventory` lists the active ID, report availability by release and the evaluation protocol summary. The existing reports, benchmarks and report exports keep their active-release behavior when called without a release parameter. Pass `?release=<id>` to view a specific release. The API checks saved report names, release IDs and split metadata before serving a report.

## Try a search

Type `Promise.all` in Search and open **Preview** on a result. Try `"event bubbling"` for a phrase or `source:mdn title:promise` for a field constraint. In IR Lab, use **Compare searches** to compare keyword BM25 with TF-IDF. With a dense release, compare Semantic and Hybrid on `wait for several JavaScript promises to finish`. Use **Overview** to check the release and **Saved report release** where offered to choose historical reports.

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
