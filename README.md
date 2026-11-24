# TechSearch

TechSearch searches a frozen English corpus of MDN pages and Stack Overflow threads about JavaScript, HTML, CSS, accessibility, browser APIs, HTTP, security, and performance. Each hit is an original page or thread with source excerpts and attribution. The public interface routes searches automatically. The IR Lab exposes all eight modes, ranker settings, explanations, release statistics, and offline experiment reports.

The active release `250a15ecd349951d6c69364c` has 15,345 documents and 197,628 dense passages. It passed release validation on Windows. The separate fixture suite passed 49 tests. See [execution results](docs/EXECUTION_REPORT.md), [status](docs/IMPLEMENTATION_STATUS.md), and [the work log](progress/WORK_LOG.md) for evidence about each release.

## Start the TechSearch server

One local server serves both **Search** and **IR Lab**. Open a terminal in the repository root and run the command for your OS. These commands use the existing `.venv` and saved active release. If `.venv` is missing, see [first-time setup](#first-time-setup).

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe scripts/start.py --host localhost --port 8000
```

### Linux

```sh
./.venv/bin/python scripts/start.py --host localhost --port 8000
```

### Open the app

- [Search](http://localhost:8000/)
- [IR Lab](http://localhost:8000/lab)
- [Readiness check](http://localhost:8000/api/v1/readiness) shows the loaded release ID and whether its dense index is available.

Keep the terminal open while using the app. Press **Ctrl+C** in that terminal to stop the server. To load a newly activated release, stop the server and run the same startup command again.

### First-time setup

If the project environment is missing, run `py -3.12 scripts/bootstrap.py` on Windows or `python3.12 scripts/bootstrap.py` on Linux from the repository root. Bootstrap supports Python 3.11 and 3.12. It installs the CPU encoder, research, and test dependencies. Add `--no-tests` to skip the test dependencies or `--wheelhouse PATH` to install from a complete offline wheel directory for your OS.

Return to the startup command for your OS after setup. To check the saved release and its local encoder from the terminal, run `python -m techsearch doctor --offline` with the project environment's Python.

## Browser checks

To exercise the optional browser checks, run `python -m playwright install chromium` in the project environment and then `python -m pytest -m browser`. Those checks use an isolated, synthetic corpus and a loopback server.

To reuse the Chromium installed in this Windows workspace, set `$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) 'artifacts/tooling/playwright'` before running the browser tests or verification script. The existing `.venv` uses the local interpreter under `artifacts/tooling/python/`.

On Linux hosts that need an OS-installed Chromium, use `python -m pytest tests/browser -m browser --browser-executable=/usr/bin/chromium-browser`. With a dense release active and the server running, `python scripts/verify_app.py --browser-executable /usr/bin/chromium-browser` checks all eight modes, API constraints, pagination, session feedback, and the IR Lab sections on desktop and mobile. It records which reports exist and saves screenshots and JSON under `artifacts/execution/browser/`. The feedback check uses a browser session separate from benchmark relevance labels.

## Data acquisition and dense search

Run these optional stages before `preprocess` when you want to refresh or enrich the supplied corpus. The stages that need network access are explicit. The unqualified `python` in the remaining examples refers to the project environment.

1. `python -m techsearch collect --source mdn` resolves and records a content commit. Add `--revision <full-sha>` to select a different snapshot. The legacy moving-main cache remains separate.
2. Set `STACKEXCHANGE_API_KEY` in `.env` or your environment for SO collection. Run `python -m techsearch collect --source stackoverflow --target 5000 --resume`. Optional staged expansion uses `--target 20000`, then `--target 50000` when the coverage report justifies it. Keep the root checkpoint and rerun the same command after a quota pause or interruption.
3. `python -m techsearch collect-compat` pins a browser-compat-data revision and extracts MDN URL mappings for metadata. An explicit revision is available through `--revision`.
4. `python -m techsearch download-model` resolves a full model revision and caches only the portable encoder files and attribution. The configured starting model is `sentence-transformers/all-MiniLM-L6-v2`. You can set `TECHSEARCH_CFG__DENSE__REVISION=<full-sha>` for a predetermined revision.
5. `python -m techsearch inspect-data` inventories the available source schemas and eligibility. `python -m techsearch preprocess` writes or reuses an immutable JSONL snapshot. `python -m techsearch build-indexes` builds and activates a release using the local encoder if available. `python -m techsearch build-graph` exports an independent recomputation of the release's graph diagnostics. `python -m techsearch validate-release --deep` verifies payload and offset consistency. `python -m techsearch doctor --offline` checks readiness.
6. If acquisition is unnecessary, `python -m techsearch pipeline --resume` resumes the offline preprocess/build stages as a pair. Raw files under `data/raw/` take precedence over the corresponding legacy root JSON. Collection stores prior raw versions under `data/raw/history/`. Collection status can be partial even when the current export is usable.

The Stack Exchange key is used only by the SO collector. Optional AI relevance annotation needs `TECHSEARCH_ANNOTATION_API_KEY` and `TECHSEARCH_CFG__EVALUATION__ANNOTATION__MODEL`. The configured HTTPS annotation endpoint can be overridden. Search and app startup use local artifacts and require no credentials.

## Retrieval and evaluation

| Mode | Input or behavior |
| --- | --- |
| Keyword | Soft token matching using the chosen lexical ranker |
| Boolean | Uppercase operations with NOT, AND, OR precedence and explicit parentheses |
| Phrase | Original neighboring tokens in the same segment |
| Prefix | Bounded vocabulary expansion using a trailing asterisk |
| Fuzzy | Bounded edit distance for eligible misspellings, weighted below original terms |
| Semantic | Exact cosine retrieval from normalized passage vectors |
| Hybrid | Reciprocal rank fusion over eligible parent lists |
| Field-specific | Hard field constraints such as `title:Promise.all` or `source:mdn` |

Use quotes for phrases. Escape a metacharacter with a backslash or enclose literal code in backticks. Source, topic, and tag constraints are exact. Supported text fields are title, heading, body, code, question, and answer. Names outside the declared fields pass through the text analyzer. Source and topic selectors work in addition to inline constraints.

Run `python -m techsearch search "title:Promise.all" --mode field` for CLI access to the same service. See [the architecture](docs/MASTER_ARCHITECTURE.md) for ranking formulas, artifact formats, and evaluation policy.

1. `python -m techsearch experiments --suite all` measures codec sizes and lookup times, TAAT/DAAT equivalence and performance, LSI retrieval, K-means diagnostics, likelihood, PageRank and MMR reranking, and a declared Rocchio vector probe. The probe is a controlled algorithm intervention; it creates no relevance judgments or quality metrics. Individual suites include `compression`, `taat-daat`, `latent`, and `retrieval`.
2. `python -m techsearch freeze-evaluation` freezes 300 authored development and 300 authored test intent groups. Use only the development split when making ranking and cutoff decisions.
3. `python -m techsearch benchmark --split dev` saves runs for Auto, BM25, dense, and hybrid. `--ablations` adds TF-IDF, likelihood, graph authority, and MMR, and also exports the four baseline methods as a labeled subset of those same observations. No extra baseline execution is implied.
4. `python -m techsearch evaluate --split dev` checks pool coverage and publishes metrics when fully judged. To explicitly send blind pooled excerpts to the configured provider, add `--annotate --limit 50` and rerun as needed. The limit counts newly judged candidate pairs. Audit/adjudication can add requests within each pair.
5. After finalizing settings, use `benchmark --split test --confirm-sealed` and `evaluate --split test --confirm-sealed` for the held-out split. Run the same ablation flags for benchmarking and evaluation. The source catalog is included for reproducibility, so sealing depends on the experimental protocol.
6. `python -m techsearch package-demo` writes a local presentation archive with the active release, frontend, launch scripts, and pinned encoder when available. Use a separate platform-specific wheelhouse for a disconnected dependency installation. The current archive and Windows offline search evidence are listed in the [demo run sheet](docs/DEMO_RUN_SHEET.md). See also the [source notices](docs/ATTRIBUTION.md).

## Project references

- [IR Lab navigation and reports](docs/IR_LAB.md)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)
- [Storage and data dictionary](docs/DATA_DICTIONARY.md)
- [Decisions and known limits](docs/DECISIONS.md)
- [Cleanup and artifact retention](docs/CLEANUP_REPORT.md)
- [Recent work and resume checkpoint](progress/WORK_LOG.md)
