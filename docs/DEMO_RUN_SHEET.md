# Course demo run sheet

Use the locally prepared **techsearch-course-demo-groq-dev50.zip**. It contains the
three-tab Lab, current Search and source code, prepared lexical and dense
indexes, the pinned local encoder, compatible Lab report summaries and
course experiments, configuration, source attribution, and a blank
credential template. Keep the attribution notices with the bundle.
The Lab includes the fixed 50-query Groq timing report, the original
300-query timing export, and pending relevance status. Test remains sealed.

## Start the prepared demo

1. Extract the ZIP into a writable directory and open a terminal there.
2. Use Python 3.11 or 3.12 to install dependencies. Initial dependency
   installation needs internet access or a suitable local wheelhouse.
3. Run the existing server start command. Model and corpus preparation
   are already done in this prepared demo.

### Windows PowerShell

```powershell
py -3.12 scripts/bootstrap.py --no-tests
.\.venv\Scripts\python.exe -m techsearch doctor --offline
.\.venv\Scripts\python.exe scripts/start.py --host localhost --port 8000
```

### Linux or macOS

```sh
python3.12 scripts/bootstrap.py --no-tests
./.venv/bin/python -m techsearch doctor --offline
./.venv/bin/python scripts/start.py --host localhost --port 8000
```

On Windows, an explicit path to an installed Python 3.12 interpreter also
works if the `py` launcher is unavailable. Keep the terminal open. Use
Ctrl+C to stop the server.

## Present the project

- Open [Search](http://localhost:8000/). Search for `Promise.all`, open a
  Preview, and use the next page.
- Search for `source:stackoverflow title:"handling errors in promise.all" code:arrayOfValuesOrErrors`.
  The Preview shows code from the accepted answer and its attribution.
- Open [IR Lab](http://localhost:8000/lab). Under **Model comparison**,
  show the saved Development timings and the separate quality status.
  Under **Try a query**, compare Semantic and Hybrid for `wait for several JavaScript promises to finish`.
  Under **Course experiments**, show codec sizes, TAAT/DAAT and the
  exploratory clusters.

## Package and history

Package an updated compatible release with a new output filename.

```sh
python -m techsearch package-demo --with-lab-reports --output artifacts/techsearch-course-demo-groq-dev50.zip
```

The public clone includes the legacy raw exports for an independent build.
The prepared course demo contains different, already-built source data.
The selected raw files and counts are in the [course report](PROJECT_REPORT.md).

The previous `techsearch-course-demo.zip` and
`techsearch-demo-250a15ecd349951d6c69364c-share.zip` remain as historical evidence.
The earlier `techsearch-demo-250a15ecd349951d6c69364c.zip` is
**unsafe to distribute**. Its adjacent warning records why. Both older
archives are outside the course bundle.

## Setup evidence

The original preparation check used an independent Windows Python 3.12.16 environment,
the checked-in 16-parent fixture data and the verified local encoder.
It exercised input inspection, preprocess, dense index build, deep validation and Semantic search.
The clean fixture used a copied pinned encoder, so it did not test a new model download.

The 25 November archive check installed fresh Windows dependencies and served
the prepared release. The evaluation-ready archive uses the same corpus and encoder.
Other operating systems and disconnected dependency installation were outside
those setup checks.

[Original clean Windows setup](../artifacts/execution/course-final/clean-setup.json)

## Groq Development archive receipt

`techsearch-course-demo-groq-dev50.zip` contains 104 files and is 646,458,080 bytes.
Its SHA-256 is `9e2a5ebcb97e15a2db5c26e3144b1ea465526bed3589605227d17827e03f2f18`.
ZIP integrity, configured-credential scanning, all eight frontend files, and
33 release and encoder files passed verification. The archive has the frozen
50-query profile and the original and subset timing exports. Its relevance
export records zero judgments and 1,085 pending pairs from before the pilot.
The live repository records the later [pilot reviews](GROQ_STUDY.md#pilot-outcome-on-28-november-2026) and the [blind human review](GROQ_V3.md). The final-results archive will be rebuilt after the evaluation is accepted.

On Windows, the extracted app passed `doctor --offline` and Chromium smoke
checks for Search, Semantic, Hybrid, the three Lab tabs, Preview, charts, and
the current exports. The server ran with the previously installed Windows
dependencies and a guard that blocked external DNS and TCP. The browser
reported zero external page requests and zero JavaScript errors. Fresh or
disconnected dependency installation and other operating systems remain
unverified for this archive.

[Archive receipt](../artifacts/execution/groq-dev50/bundle-contents.json) ·
[Extracted browser checks](../artifacts/execution/groq-dev50/extracted-browser/app-verification.json)

## Evaluation-ready archive receipt

The preceding `techsearch-course-demo-evaluation-ready.zip` remains available
locally. It has 100 files and the original 300-query timing and relevance
status reports. Its SHA-256 is
`52fa3407e005aee524a753ed6aadff7c4bab2a519579cd70358c65b8fa7d6441`.
[Historical archive receipt](../artifacts/execution/evaluation-ready-2026-11-27/bundle-contents.json)
