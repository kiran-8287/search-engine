# Cleanup report

## 24 November 2026

The audit started on a clean `main` tracking `origin/main`. The full
directory dump recorded 196,810 files, 17,711 directories and one link.
A fresh scan agreed and measured 5,531,548,548 logical bytes. It counted
the managed Python link without following it. The working environment
accounted for 37,743 files and the embedding build cache for 141,437.
Those figures include dependencies and generated artifacts.

### Cleanup ledger

| Path or group | Classification | Evidence and decision | Files | Logical bytes |
| --- | --- | --- | ---: | ---: |
| `artifacts/TechSearch_Full_Directory.txt` | Redundant after verification | The counts above capture the useful findings. The snapshot contains installed libraries, cached embeddings and extracted pages. No project entry point or documentation uses the dump. Remove. | 1 | 33,930,904 |
| `artifacts/models/encoder/embeddings/` | Redundant after verification | Only the dense build stage reads and writes these encodings. Remove after fresh offline Search, release validation and demo packaging succeed without this tree. | 141,437 | 235,351,168 |
| `data/downloads/mdn/df622a2a1c1e9626976cb3c091622d35e799b0cf/mdn-source-f6cc7cd4f799/` | Redundant after verification | Collector extraction cache. Remove after confirming the local archive reproduces every loose file and agrees with the collector and release provenance. | 12,652 | 52,692,230 |
| `src/techsearch/__pycache__/` | Safe generated clutter | CPython bytecode for 21 package modules. The imports and editable-install metadata point to the Python source. Remove. | 21 | 321,505 |
| `artifacts/execution/server-windows-interim.log`, `server-windows-refreshed-mdn.log` | Safe generated clutter | Unreferenced lifecycle and access logs. The PowerShell diagnostic wraps Uvicorn’s startup message. The refreshed log’s 404s concern the former favicon route and a Chromium DevTools probe. Retained the structured API and browser smoke records. Remove. | 2 | 14,118 |
| `artifacts/execution/ui-redesign/serve.err`, `serve.out` | Safe generated clutter | Unreferenced startup, model-load progress and access logs. The redesign verification JSON and screenshots retain the check results. The Visual C++ warning is also recorded in the project work log. Remove. | 2 | 10,610 |
| `artifacts/execution/pytest-windows-final.log`, `pytest-windows-verified.log` | Redundant after verification | The logs recorded 40 and 41 passes on earlier checkouts. A line comparison against the referenced retry log found changes only in the progress indicators, counts and elapsed times. The two durations were 12.66 s and 12.52 s. Remove the two unreferenced logs and retain the referenced 37-pass rerun. | 2 | 5,108 |
| `artifacts/tooling/huggingface/xet/logs/xet_20261122T014824714+0530_10068.log` | Safe generated clutter | Empty transfer log. The offline proof loads the pinned encoder with an empty `HF_HOME`. Remove. | 1 | 0 |
| `artifacts/releases/` and `artifacts/models/encoder/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/` | Required and historical | Both pointers agree with the live release and its pinned model. The three release directories contain 21, 17 and 17 files. The model snapshot contains 27 files, including the 12 manifest entries. Keep the indexes, vectors, passage mappings, weights, tokenizer, pooling configuration and local model metadata. | 84 | 1,917,960,457 |
| Pinned archives under `data/downloads/mdn/` and `data/downloads/bcd/` | Required source evidence | MDN SHA-256 `a19879b97e7e6a3277e46a1db3702618638ffe4692303f09b0da501db173e47c` matched the extraction stamp, collection manifest and active release. ZIP integrity passed across 31,222 entries. SHA-256 matched every selected file, including the redirects file. The stamp was the only extra file. The BCD tarball passed full gzip integrity and had 3,425 entries under revision `1edef63031c8bbc2844b3f48e092433eecc4842e`, including the license. Its SHA-256 `5716921a9ed0514554462d494c1fabee71b7064e657c224e0c8157d2a30fba2e` matched `browser_compat.json`. Keep both archives. | 2 | 77,442,299 |
| `artifacts/execution/screenshots/`, `ui-redesign/screenshots/`, `lab-navigation/`, and `docs/pdf-evidence/` | Historical evidence | The screenshot sets have separate verification or presentation roles. The work log, IR Lab guide and PDF screenshot guide link to them. No two files under `artifacts/execution/` had the same SHA-256. Keep all four sets. | 49 | 3,555,566 |
| `artifacts/TechSearch_PDF_Evidence.zip` and the existing demo ZIP | Required delivery evidence | All 22 PDF ZIP members match the current evidence, packaged for delivery. The 87-entry demo ZIP contains the active release and a pinned encoder and has a separate offline runtime verification record. It predates the latest Lab navigation, which a new package uses. Keep both delivery archives. | 2 | 514,560,979 |
| Remaining `artifacts/execution/` logs and JSON outside the screenshot sets | Historical evidence or uncertain | Keep structured smoke outputs, collection retries, encoder and installation checks, benchmark and experiment diagnostics, and cited test outputs. Content differs from the replacement checks and may be useful for reconstructing earlier runs. | 35 | 590,946 |
| `data/runtime/` | Required or uncertain | Applied the app’s seven-day mtime cutoff and 100-snapshot limit. All 88 snapshots in 14 sessions were recent and within the limit. Ownership could not be determined from the format. Keep them, the two feedback files, and the 14 session locks. Writers coordinate on the first byte of each lock file. | 104 | 7,538,197 |
| `artifacts/reports/`, `artifacts/runs/`, `data/evaluation/` | Required and historical | Historical views read the plain-name reports by explicit release ID. The hash-suffixed names are immutable run copies. The six saved ranking runs, frozen inputs and annotation pool support the evaluation record. The historical blocked review contains zero judgments. Keep the input and output records. | 33 | 28,171,409 |
| Root exports, `stackoverflow_checkpoint.json`, `data/raw/`, `data/manifests/`, `data/quarantine/` | Required and historical | SHA-256 differs across the root, current raw and historical versions. The oldest lexical release uses the root MDN and Stack Overflow bytes. The live and refreshed lexical releases use refreshed MDN and the root Stack Overflow input. The later raw Stack Overflow export and its archived predecessor carry independent source evidence. Keep the original checkpoint, raw provenance, and quarantine decisions. | 13 | 548,291,217 |
| `.venv/`, `artifacts/tooling/python/`, `artifacts/tooling/playwright/`, `artifacts/tooling/uv/`, `src/techsearch.egg-info/` | Required | The editable install uses the managed interpreter and local package metadata. The browser checks use the retained Chromium. The tooling contains uv executables available for setup. The Python link was recorded without traversal. These counts are from the final scan. | 41,875 | 2,088,816,858 |
| Remaining `artifacts/tooling/huggingface/` metadata and empty directories | Uncertain | The local encoder works with an empty `HF_HOME`. The remaining settings and directory layout may support future downloads. Keep the metadata and its contents private. | 1 | 9,285 |

The build cache stores passage encodings for reuse across index builds.
Future builds may have to encode those passages again. The published
release reads its vectors and parent mappings directly from the release
directory. The collector can recreate its scoped extraction from the
verified MDN ZIP.

The cleanup deleted **154,118 files** and **12,914 directories**, for
**322,325,643 logical bytes (307.39 MiB)** of deleted content. The full
workspace went from **196,810 to 42,693 files** and **17,711 to 4,797
directories**. One managed Python link remains. A UTF-16 codec bytecode
file was generated in the managed interpreter during log inspection.
The scan includes it in the final count and leaves it with the
interpreter. Logical file sizes measure content, independent of NTFS
allocation and background activity.

### Code and dependency audit

- The MDN collector ran a recursive list search whose loop had no
  effect. The existing direct-child traversal already processes nested
  sections through their list items. Removed the no-op loop. Heading
  extraction now reuses the section anchor it already computed. The
  private segment helper had one caller that supplied that same value.
- The Stack Overflow answer selector iterated over ID and document
  pairs and used only the document. It now iterates over the values.
  Existing files and their recorded collector provenance were retained.
  A direct replay against Git HEAD matched nested HTML extraction,
  anchors, code, links, answer ordering, and all four availability states.
- Checked Python imports, command dispatch, FastAPI routes and test
  callbacks, HTML module references, JavaScript imports and dynamically
  assigned CSS classes. All frontend assets had consumers. Kept ranking
  methods, configuration fields and dependencies used by optional and
  academic workflows.
- Added ignore rules for coverage output and interrupted MDN extraction
  directories. The existing ignores cover local data, releases,
  installed dependencies, logs and bytecode.

| Workflow | Dependencies and entry points retained |
| --- | --- |
| Search and all seven Lab sections | `scripts/start.py`, the CLI `serve` command, FastAPI/Uvicorn and Pydantic, the vanilla frontend, YAML config, active corpus/index/graph, file-backed snapshots, and saved report routes. |
| All eight modes | Shared Search service, query parser, postings and rankers, NumPy, active passage index, and the pinned local MiniLM weights, tokenizer and pooling files through the `dense` extra. |
| Collection and resumption | Both root collectors, Requests, Beautiful Soup, MarkdownIt, Python dotenv and YAML, the source archives, raw history and resumption checkpoint. |
| Academic experiments and evaluation | Dynamic CLI commands, three postings codecs, graph and retrieval experiments, SciPy/scikit-learn for latent and cluster runs, versioned reports/runs, and frozen queries and the annotation pool. |
| Offline demo and verification | Bundler, release manifest and local model, existing Windows interpreter and editable distribution, installed Chromium, pytest/Playwright, and the real-app HTTPX verification script. |

### Verification on Windows

| Check | Observed result |
| --- | --- |
| Baseline `python -m pytest -q --tb=short -p no:cacheprovider` | 53 passed in 40.19 s, with two dependency deprecation warnings. Standard and deep validation also passed on the baseline. |
| Focused collector and dense storage tests | `python -m pytest tests/unit/test_collectors.py tests/integration/test_dense_repository.py -q --tb=short -p no:cacheprovider` passed all 18 tests in 2.59 s. |
| Final full suite | The baseline command passed all 53 tests in 25.06 s, including fixture browser coverage. The existing Starlette HTTPX and pytest fixture deprecation warnings remained. |
| Active release validation | `python -m techsearch validate-release` and `python -m techsearch validate-release --deep` both passed after cleanup on release `250a15ecd349951d6c69364c`. Deep validation checked all three postings codecs against the canonical corpus, document offsets and passage mappings. The dense manifest and vector array agree on 197,628 passages and 384 dimensions for 15,345 documents. |
| Imports, CLI and environment | Imported 22 project modules. `python -m techsearch --help` listed all commands. `python -m pip check` found no broken requirements. `python -m techsearch doctor --offline` reported lexical readiness and 100 Semantic results. |
| Before-and-after active search replay | Matched all 11 responses exactly after excluding generated search IDs and timings. Cases covered `Promise.all`, `promise AND error`, `"event bubbling"`, `querySelec*`, Fuzzy `addEventListner`, `source:mdn title:promise`, the conceptual query “wait for several JavaScript promises to finish” in Semantic and Hybrid, and extra source/topic, DAAT and TF-IDF cases. IDs, scores, order, snippets, evidence, constraints and page slices matched. |
| Fresh offline processes with the build cache isolated and after deletion | Both processes returned 100 results each for Semantic and Hybrid with the expected branches and no fallback. TCP and DNS control probes were blocked, with zero application socket attempts. The active pointer and 12 encoder files passed manifest checks. The temporary 96-entry demo ZIP passed a full ZIP integrity check and contained the active release, encoder and latest Lab module. The already verified delivery archive was preserved. |
| Real Search and Lab | `scripts/verify_app.py` ran against a fresh loopback server on active release `250a15ecd349951d6c69364c`. Chromium 159 exercised eight modes, ranking comparisons, filters, pagination, Preview, disposable feedback, all seven Lab sections, mobile layouts and browser navigation. It reported zero JavaScript errors. The favicon returned HTTP 200. Temporary browser output was discarded after the check. |
| Historical reports and exports | Verified both historical lexical releases by manifest and opened and exported all 12 saved reports through the API. Report data and attachment names matched the selected release, and an unknown release returned HTTP 404. Active relevance evaluation remained `not-run`. The older blocked evaluation still has zero judgments. |
| Preserved evidence | Rechecked nine raw export and checkpoint SHA-256 values, both delivery ZIP hashes and both active pointers. `git check-ignore` covered the generated paths and `git diff --check` passed. |

The offline checks used the installed Windows environment. Clean disconnected
dependency installation and other operating systems remain unverified.

### Final project tree

```text
search-engine/
├── .env, .env.example, .gitignore, README.md, pyproject.toml
├── .git/ and .venv/
├── collect_mdn.py and collect_stackoverflow.py
├── mdn_documents.json, stackoverflow_documents.json, stackoverflow_checkpoint.json
├── config/                     Search, source scope, evaluation and query inputs
├── frontend/                   Search and Lab pages, styles, modules and favicon
├── src/techsearch/             API, CLI, storage, retrieval, build and research code
├── src/techsearch.egg-info/     Editable install metadata
├── scripts/                    Setup, launch, demo packaging and verification
├── tests/                      Unit, integration, browser and fixtures
├── data/
│   ├── downloads/              Pinned MDN ZIP and browser-compat tarball
│   └── raw/, manifests/, quarantine/, evaluation/, runtime/
├── artifacts/
│   ├── releases/               Active pointer, dense release and two historical releases
│   ├── models/encoder/         Local pinned encoder and model pointer
│   ├── reports/, runs/, execution/, tooling/
│   └── TechSearch_PDF_Evidence.zip and techsearch-demo-250a15ecd349951d6c69364c.zip
├── docs/                       Project documentation and PDF evidence
└── progress/WORK_LOG.md
```

## 22 November 2026

Cleanup ran on 22 November 2026 in `D:\Projects\search-engine`. The initial `git status --short --branch` showed a clean `main` tracking `origin/main`. The audit covered the repository instructions, README, implementation status, configuration, active manifest, Python imports, CLI dispatch, API route registrations, frontend references, tests and release dependencies. There were no applicable `AGENTS.md` files.

## Removed local files

| Removed | Files | Bytes | Reason |
| --- | ---: | ---: | --- |
| `artifacts/execution/windows-legacy-root/` and `windows-mdn-root/` | 30 | 690,020,134 | Staged config and source copies matched the retained originals by SHA-256. The processed corpus files matched their retained releases, and the staged manifests matched the embedded corpus manifests. The two unique quarantine reports were copied and verified before removal. |
| `artifacts/tooling/pip-cache/` and `uv-cache/` | 398 | 277,692,794 | Temporary installer caches. Python resolves through the retained managed interpreter, and installed distributions live in `.venv`. The uv cache held only empty markers and cache bookkeeping. |
| `artifacts/tooling/uv-windows.zip` | 1 | 15,567,875 | All three executable files matched the extracted copies in `artifacts/tooling/uv/` by SHA-256. |
| `artifacts/execution/search-windows-interim.png` and `lab-windows-interim.png` | 2 | 209,201 | The current redesign screenshots cover both views. Repo documentation and the saved interim browser report contain no references to these filenames. |
| Project `__pycache__/` directories and `.pytest_cache/` | 35 | 617,356 | Generated bytecode and pytest state in the root, package and test folders. These were outside the protected environment. |

The displaced reports are now `data/quarantine/b1bddfda4e413b0e8d06ea0a.json` and `data/quarantine/1a1a58867f0b20556402c331.json`. Their combined size is 279,197 bytes. The cleanup deleted 984,107,360 logical bytes across 466 files and reclaimed **983,828,163 net logical bytes (938.25 MiB)** after preserving those reports. Available space on `D:` increased by 984,891,392 bytes between the two readings. That drive-level figure also reflects filesystem allocation and background activity.

## Source cleanup

- Removed the unused `write_jsonl` import from the repository and the unused `json` import from collector tests.
- Shared the session-scoped snapshot lookup and 404 handling between search pagination and JSON export. Route URLs, session rules and response formats stay the same.
- Added ignore rules for loose Python bytecode, abandoned `.techsearch-*` temporary paths, and common Python tool caches. The frontend entry points load all six current frontend files. Route, CLI and test references account for the academic algorithms.

## Retained files and evidence

- The active release is `250a15ecd349951d6c69364c`, with 15,345 documents and 197,628 passages. The pinned MiniLM revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` and its tokenizer files remain at the location checked by the loader. The embedding cache supports reuse on future builds.
- Both older releases remain available. Release `6f86fc58d97fad8a0c0ec387` has benchmark runs, experiment reports and documentation references. Release `a585b9035a3c6cd217a93cbb` has separate lexical experiment reports. Both passed manifest and artifact verification.
- Both root exports contain distinct source evidence. MDN hashes are `81a1a01235061fba7e99e8619cc88af76bc493a2fb3da549ce9597bb82810312` at the root and `3583d7537a91981558d5f19871944dc76bfa8112532fb80b0a345da4c5c3c722` under `data/raw/`. Stack Overflow hashes are `56bb335e55504df86d8348438d65dc23c0f9009aba67809b9c26ea0953361a6d` at the root and `d3db8c11b685b39383e4333565b48b9e73d6b7d8c508a2a2320c7fe917d39a7d` under `data/raw/`. The active release records the root Stack Overflow export as its input. The older lexical release records both legacy inputs.
- Kept the root collectors, checkpoint, pinned downloads, raw history, evaluation catalog and results, runtime snapshots, source attribution, and verification logs. The seven current UI screenshots and the historical screenshot directory cited in the work log remain available.
- The Windows virtual environment depends on the managed Python under `artifacts/tooling/python/`. Browser verification uses `artifacts/tooling/playwright/`. The extracted uv binaries support Python setup. The small Hugging Face tooling directory was left intact because the ownership of its workspace metadata was uncertain. The root `.env` and `.git` stayed outside the cleanup targets.

## Checks

| Check | Result |
| --- | --- |
| `python -m pip check` | Passed. All installed dependency requirements were satisfied after the installer cache was removed. |
| Import and CLI checks | Imported 20 package modules, ran top-level and search help, and retrieved the MDN `Promise.all` page through the field-search CLI. |
| Pinned encoder files | Verified SHA-256 for all 12 files listed in the active model manifest, including tokenizer files. |
| `python -m techsearch validate-release` | Passed for active release `250a15ecd349951d6c69364c`. |
| `python -m techsearch validate-release --deep` | Passed for the same active release. Verified corpus records, canonical token positions, all three posting encodings, and dense vector and passage consistency. |
| Archived release verification | Both retained lexical releases passed checksum and structural verification. |
| Live browser smoke | Chromium 159 passed Search, source preview, the IR Lab lexical comparison and compression chart checks against the existing active release, with zero uncaught JavaScript errors. |
| Collector baseline | Before edits, six collector tests passed and five failed. The failures concern absent scoped MDN extraction, Stack Exchange throttle handling, batching and extracted-text scope behavior in the current collector scripts. |
| Full suite after cleanup | 39 passed, five failed. The failing tests are the same five from the collector baseline. Browser tests used the retained Chromium installation. |
| Git whitespace check | `git diff --check` passed. Windows reported its line-ending conversion notices. |
