# Project context

TechSearch targets a local CPU laptop demonstration for English web-development information retrieval. Search results are actual source parents with evidence and attribution. The same production ranking code drives Search, Lab, CLI, and offline benchmarks.

The workspace began with two collectors and two legacy root exports. Those root JSON files were inspected for shape without changing them. The newer collector schemas support structured evidence that cannot be inferred when the older exports flattened it. A fresh, explicit acquisition is the route to recovering that source structure.

There was no existing master architecture file in the workspace at inspection. [The architecture](MASTER_ARCHITECTURE.md) records the supplied specification and the subsequent file-storage design.

For the first run, use the [getting-started guide](../README.md).

## Git workflow

You can clone the original repository directly if you only plan to run it. If you forked it and want to pull updates from the original, add this remote once from your clone.

```bash
git remote add upstream https://github.com/kiran-8287/search-engine.git
```

## Detailed setup

You need **Python 3.11 or 3.12** with `venv` and `pip` available, plus a web browser. Git is needed to clone. The app uses plain HTML, CSS, and JavaScript served by FastAPI/Uvicorn. It needs no Node.js, Docker, database server, or GPU.

| Dependency group | What it provides |
| --- | --- |
| Core | The web server, API, JSON and array handling, YAML settings, and collector libraries. Declared in `pyproject.toml`. |
| `dense` | CPU PyTorch, Sentence Transformers, and Hugging Face helpers. Install this for Semantic and Hybrid. The pretrained model files are a separate download. |
| `research` | SciPy and scikit-learn for latent semantic indexing and clustering. Bootstrap includes this group. |
| `test` | pytest and the Playwright pytest plugin. Install Chromium separately, or ask bootstrap to install it with `--browsers`. |

**Example sizes measured on Windows.** The legacy inputs total 38 MiB. The active dense release takes about 908 MiB, its portable encoder 87 MiB, and the saved demo ZIP 490 MiB. The Windows environment took about 1.13 GiB on disk and the Playwright installation occupied about 743 MiB. A previous local search check, including dense queries, peaked at about 895 MiB of process memory.

**Planning estimate.** Allow around 8 GiB of free disk and 8 GiB of system RAM for a first dense build of the documented corpus if you also want tests. A build temporarily keeps staging files, processed documents, the release, and sometimes a passage encoding cache. Keeping several releases or collecting a larger corpus takes more space. Initial download size varies by platform and dependencies. The Windows collection example downloaded a 72 MiB MDN archive and a 1.9 MiB compatibility archive in addition to dependencies, model files, and API responses.

### Windows PowerShell

```powershell
py -3.12 --version
py -3.12 scripts/bootstrap.py
.\.venv\Scripts\Activate.ps1
python --version
```

If you installed Python 3.11, use `py -3.11` in the first two lines. If `py` is missing, substitute the location of your Python 3.11 or 3.12 executable in these commands, then activate the environment as shown above.

```powershell
& "C:\Path\To\Python312\python.exe" --version
& "C:\Path\To\Python312\python.exe" scripts/bootstrap.py
```

### Linux or macOS

The commands below follow the supported shell and environment layout. This guide's Windows checks used an existing environment. A clean Linux or macOS installation has not been verified for this guide.

```sh
python3.12 --version
python3.12 scripts/bootstrap.py
source .venv/bin/activate
python --version
```

Use `python3.11` if that is the version you installed. On Linux, install the matching `venv` package if your distribution separates it from Python. If the bootstrap CPU wheel index lacks a wheel for your platform, use `python3.12 scripts/bootstrap.py --lexical-only`, activate the environment, then install dense dependencies with `python -m pip install -e ".[dense]"` using the normal package index. Wheel availability depends on the OS, CPU architecture, and Python version. [PyTorch installation guide](https://pytorch.org/get-started/locally/)

Bootstrap creates or reuses `.venv/`, installs the project in editable mode with the extras above, and runs `pip check`. Add `--no-tests` to skip installing test packages or `--lexical-only` to skip installing dense packages. Add `--wheelhouse PATH` to install from a complete local wheel directory for your OS, architecture, and Python version. A disconnected installation needs all dependencies and build wheels, including CPU PyTorch for a dense setup. Prepare Chromium separately for offline browser testing.

The commands below assume the project environment is active. In a new terminal, activate it again. You can also replace `python` with `.\.venv\Scripts\python.exe` on Windows or `./.venv/bin/python` on Linux or macOS.

### Configure `.env`

Bootstrap copies `.env.example` to `.env` when `.env` is absent. To make that copy yourself without replacing an existing file, use the command for your shell.

```powershell
if (!(Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

```sh
[ -e .env ] || cp .env.example .env
```

Open `.env` in a text editor. Leave the credential fields blank to run Search, build from exports, or run local experiments.

| Setting | When to set it |
| --- | --- |
| `STACKEXCHANGE_API_KEY` | Set to your own application key only for Stack Overflow collection. Sign in and register or open your app in [Stack Apps](https://stackapps.com/apps/oauth/register). |
| `TECHSEARCH_ANNOTATION_API_KEY` | Set only if you explicitly request AI annotation. Use a key for the configured provider. |
| `TECHSEARCH_CFG__EVALUATION__ANNOTATION__MODEL` | Set to an available model ID from that provider before annotation. The default model is unset. `TECHSEARCH_CFG__EVALUATION__ANNOTATION__ENDPOINT` can select a compatible HTTPS chat-completions endpoint. |

Existing process environment variables take precedence over `.env`. Keep keys in your local environment and out of Git and demo archives. [Evaluation configuration](../config/evaluation.yaml)

## Build from raw exports

A Git clone already includes the two legacy exports at the project root. Those files are enough to build a searchable corpus with both sources. If someone gives you newer structured exports, place them in the preferred paths shown in the [data table](DATA_DICTIONARY.md#data-files-and-placement). Each export must be a JSON array of collector records. The application chooses each source independently. It accepts one source if the other is missing, but results will only contain the available source.

For a first **dense** build with the exports from the clone, run the following after bootstrap. Use the stated order. The first model download needs internet access. If `status` already shows the intended pinned model installed, skip that download.

```sh
python -m techsearch doctor
python -m techsearch inspect-data
python -m techsearch download-model
python -m techsearch preprocess
python -m techsearch build-indexes
python -m techsearch validate-release
python -m techsearch doctor --offline
```

Look for the intended paths and eligible counts in `inspect-data`. The build output should have a `release_id` and a non-null `dense` section. `validate-release` should return `"status": "validated"`. `doctor --offline` should report that the encoder and exact search are available. Then [start the server](../README.md#start-again-later).

| Step | Inputs, outputs, and reruns |
| --- | --- |
| `doctor` or `status` | Reports the environment, current pointers, and which source files are visible. Plain `doctor` does not require a built release. `doctor --offline` requires a release and runs a local lexical check and a dense check when the release includes vectors. Both are read-only checks. |
| `inspect-data` | Reads the selected raw exports and scope rules. Prints schemas, file paths, and acceptance counts. Writes `data/manifests/raw-inspection.json`. Rerunning refreshes that report. |
| `download-model` | Resolves and downloads the configured encoder and records its revision and file hashes in `artifacts/models/encoder/active.json`. The default is All-MiniLM-L6-v2. It can resolve a newer revision when unpinned. To select a known revision, set `TECHSEARCH_CFG__DENSE__REVISION` in `.env` before running it. Skip this command when the intended valid snapshot is already present. |
| `preprocess` | Reads selected exports, optional metadata, and `config/scope.yaml`. Normalizes documents, rejects out-of-scope records and duplicates, and writes canonical JSONL, byte offsets, aliases and link edges under `data/processed/<corpus-id>/`. It updates `data/processed/current.json` and writes rejection details under `data/quarantine/` when needed. The same source hashes and scope reuse a verified snapshot. |
| `build-indexes` | Reads that canonical snapshot. In one command it builds the forward term index and positional inverted index in fixed-width, variable-byte, and gamma encodings. It also builds the MDN link graph and PageRank. With a compatible local encoder it chunks source segments into passages and writes `vectors.npy`, `passage-parents.npy`, and passage metadata. The release is written to `artifacts/releases/<release-id>/`. Existing matching releases and verified compatible components can be reused. |
| Release activation | A successful build validates the release and atomically updates `artifacts/releases/active.json`. `status` reports the selected ID. The next server start reads that pointer. The Lab's report-release selector only selects saved reports. It does not change the Search release. |
| `validate-release` | Verifies the active manifest, file hashes and layout. Add `--deep` to also scan documents, cross-check compressed postings, and verify dense passage mappings. It can take several minutes on the full corpus. It leaves the release files in place. |

After model preparation, `python -m techsearch pipeline --resume` is a shortcut for `preprocess` followed by `build-indexes`. It reuses available inputs and artifacts and does not fetch sources or a model. The optional `python -m techsearch build-graph` recomputes graph diagnostics for the active release and writes a saved graph report and ranks to `artifacts/reports/<release-id>/`. The main build already provides a graph for the app.

**Lexical-only build.** Add `--lexical-only` to bootstrap if you want to skip PyTorch and the encoder packages. Skip `download-model` and use the following in place of the dense build commands.

```sh
python -m techsearch inspect-data
python -m techsearch pipeline --resume --lexical-only
python -m techsearch validate-release
python -m techsearch doctor --offline
```

Keyword, Boolean, Phrase, Prefix, Fuzzy, and field constraints work on a lexical release. Auto uses lexical fallback when it would need dense search. Explicit Semantic and Hybrid are unavailable. The readiness endpoint shows `"dense_index": false`. To add them later, install the `dense` extra, prepare the model, and build and validate without `--lexical-only`.

## Collect from sources

Run the default bootstrap and configure your own `STACKEXCHANGE_API_KEY` first. A fresh collection needs GitHub access for MDN and optional Browser Compatibility Data, and Stack Exchange API access for Stack Overflow. These commands use the root collectors through the CLI.

```sh
python -m techsearch doctor
python -m techsearch collect --source mdn
python -m techsearch collect --source stackoverflow --target 5000 --resume
python -m techsearch collect-compat
python -m techsearch inspect-data
```

- **MDN** pins a full commit of `mdn/content`. The first run resolves `main` when no revision is supplied. Later runs reuse the recorded requested revision. Supply `--revision` followed by a full lowercase commit SHA to select a snapshot. The collector stores its ZIP, scoped extraction, export, URL map, inventory, and provenance. A rerun can reuse the pinned download and recreate the extraction.
- **Stack Overflow** starts with the 5,000 eligible-question milestone. The other configured milestones are 20,000 and 50,000. These are targets and depend on API limits, scope, and answer availability. The collector automatically loads `stackoverflow_checkpoint.json` when it exists. The documented `--resume` flag is accepted, and checkpoint loading also happens without it. Keep the checkpoint, use the same target after a quota pause or Ctrl+C, and run a single collector at a time. The collector backs off when asked by the API and stops starting new requests at low quota. [Stack Exchange throttles](https://api.stackexchange.com/docs/throttle)
- **Browser Compatibility Data** is optional enrichment. `collect-compat` pins a commit, caches its tarball, and writes browser support metadata keyed by MDN URL. A rerun reuses the recorded revision and archive. Use `--revision` with a full lowercase SHA to change it. [Browser Compatibility Data source](https://github.com/mdn/browser-compat-data)

Check `data/manifests/collection-mdn.json` and `data/manifests/collection-stackoverflow.json` for `complete`, `partial`, or `blocked`. The Stack Overflow manifest reports remaining shortfall and pending answer work. A partial export may contain usable results. `inspect-data` shows which records qualify. Before replacing an existing raw export, the collection wrapper preserves the old copy in `data/raw/history/<sha256>/`. Once you are happy with the inputs, continue with the [build steps](#build-from-raw-exports). For a dense build, start with model preparation if the encoder is still missing.

## Server readiness

The server reads the active pointer at startup and verifies the selected index files. Restart it to load a build activated after startup. The encoder loads on the first query that needs dense retrieval. The [readiness endpoint](http://localhost:8000/api/v1/readiness) shows the selected release and dense index availability. Use `python -m techsearch doctor --offline` to check the local encoder.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `Use Python 3.11 or 3.12.` or `py` / `python3.12` is missing | Install one of the supported versions. Verify it with the corresponding `--version` command. On Linux, install matching `venv` support if it is packaged separately. |
| `Project environment missing` or `No module named techsearch` | Run bootstrap from the project root with a supported interpreter. If `py` is missing on Windows, use the full executable path shown in [Detailed setup](#detailed-setup). Activate the environment or use the project-local Python path. `python -m pip check` checks installed requirements. Create a new environment on the destination OS instead of copying another machine's `.venv`. |
| PowerShell blocks `Activate.ps1` | Replace `python` in the commands with `.\.venv\Scripts\python.exe`. |
| `Raw collector exports are missing. Run inspect-data.` | Run `python -m techsearch inspect-data`. Check the exact paths in the [data table](DATA_DICTIONARY.md#data-files-and-placement). Restore the tracked exports from a clean clone, place your collected exports under `data/raw/`, or [collect from sources](#collect-from-sources). A demo only needs raw data if you want to rebuild it. |
| `Canonical snapshot missing` or `Canonical snapshot is stale` | Run `python -m techsearch preprocess` before `build-indexes`, or rerun `pipeline --resume` with your intended dense or lexical-only flags. Inspect selected raw paths first. |
| `No active release`, `Release artifact missing or inconsistent`, or an incompatible release | Run `python -m techsearch status` and `python -m techsearch validate-release`. If you received a demo, re-extract the matching code, config, and release together. For a rebuild, check raw inputs and re-run the build sequence. Keep old releases and checkpoints. A damaged pre-existing release folder can also block reuse, so use a separate clean checkout if a rebuild cannot validate that folder. |
| Semantic or Hybrid is unavailable | Check `/api/v1/readiness` and run `python -m techsearch doctor --offline`. If vectors are missing, prepare the model and build without `--lexical-only`. If the release has vectors but its model files are missing or mismatched, restore the exact encoder recorded in the release manifest. Use `download-model` with that revision pinned when retrieval is allowed. |
| Collection is `partial`, `blocked`, or paused by quota | Check the collection manifest, the key setting, and connectivity to GitHub or Stack Exchange. Respect the reported backoff or quota reset and rerun the same command for the same stage. Preserve `stackoverflow_checkpoint.json` and existing exports. If a writer lock is reported, confirm the earlier writer has exited before removing a stale lock. |
| The port is already in use | Stop your earlier server with Ctrl+C, or rerun the launch command with `--port 8001` and open `http://localhost:8001/` or `http://localhost:8001/lab`. |
| Playwright cannot find Chromium | Install the test extra and run `python -m playwright install chromium` in the same environment. If Chromium is already installed through Playwright in a custom location, set `PLAYWRIGHT_BROWSERS_PATH` to that directory. For a separate browser executable, pass `--browser-executable` to the browser tests. |
| Evaluation reports missing judgments | Run `freeze-evaluation` and the matching benchmark on the current release, then `evaluate` without annotation to inspect status. The matching split, release, ablation choice, and annotation configuration matter. Incomplete coverage leaves metrics unavailable. |

## Project layout and maintenance

```text
search-engine/
├── README.md, pyproject.toml, .env.example
├── collect_mdn.py, collect_stackoverflow.py
├── mdn_documents.json, stackoverflow_documents.json
├── config/                 Search settings, corpus scope, evaluation catalog
├── frontend/               Search, IR Lab, and browser assets
├── src/techsearch/         Python CLI, API, collection, storage, and retrieval
├── scripts/                Bootstrap, server launch, demo packaging, verification
├── tests/                  Unit, integration, browser tests, and fixtures
├── data/                   Local raw exports, canonical records, runtime, evaluation
├── artifacts/              Local releases, encoders, reports, runs, and demo ZIPs
├── docs/                   Course and maintenance documentation
└── progress/WORK_LOG.md     Changes and verification evidence
```

Git tracks source, config, tests, docs, and the two supplied legacy exports. Local `.env` files can contain credentials. Environments and large generated data are machine-specific or expensive to duplicate. Keep them out of Git along with model downloads, newly collected exports, checkpoints, and runtime feedback. Keep backups of raw exports, provenance, and required checkpoints. Canonical JSONL and binary indexes are derived from those inputs. The build can regenerate encoder passage caches when needed, and a later build may take longer after cleanup.

For code orientation, see the [code map](CODE_MAP.md). For reports and modes, see the [IR Lab guide](IR_LAB.md). For presentations, see the [demo run sheet](DEMO_RUN_SHEET.md). Keep the original source links, author and license metadata, and attribution notices with excerpts and demo copies. Review the source terms before redistributing an export or bundle. [Source attribution](ATTRIBUTION.md)
