# Local demo run sheet

Use `artifacts/techsearch-demo-250a15ecd349951d6c69364c-share.zip` for
release `250a15ecd349951d6c69364c` with the current seven-section IR Lab.
The archive is local. Ask the maintainer for the ZIP and its SHA-256.
The ZIP supplies already built search assets. Use the repository clone if you
want to work with the raw source exports or build indexes yourself.

| Detail | Value |
| --- | --- |
| Archive size | 513,370,800 bytes |
| ZIP members | 92 |
| SHA-256 | `ac34fb0c8b4eafb73b161e0e92d85841204fb2294f7822bffb6cfeace1e0821a` |
| Release | `250a15ecd349951d6c69364c` with 15,345 documents and 197,628 passages |
| Encoder | All-MiniLM-L6-v2 revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |

**Unsafe to distribute:** the earlier
`artifacts/techsearch-demo-250a15ecd349951d6c69364c.zip` contains a
populated Stack Exchange credential field. The file and its
[historical verification](../artifacts/execution/offline-demo-250a15ecd349951d6c69364c.json)
are retained as private evidence. The original ZIP has an adjacent
`.UNSAFE-TO-DISTRIBUTE.txt` notice.

The share ZIP includes the current frontend, app code, portable configuration,
blank `.env.example`, source attribution, active indexes and passage vectors,
and the pinned encoder. Raw exports, checkpoints, private runtime records,
saved experiment or annotation reports, and other archives stay in the source
workspace. The Lab's live comparisons and build statistics are available in
the demo.

The share ZIP passed CRC verification and was extracted to a temporary
directory. The eight frontend files matched the checkout byte for byte,
and the release and 12 encoder files matched their manifests. Keyword
Search, Semantic, and Hybrid returned 57, 100, and 100 results for the smoke
queries. Chromium checked Preview, all seven Lab sections, a live
Semantic/Hybrid comparison and ranking export. The Python process and browser
page requests were restricted to loopback. The checks used the existing
Windows dependencies and Chromium. A clean dependency installation and
Linux and macOS runs remain unverified. The local record is
`artifacts/execution/share-demo-250a15ecd349951d6c69364c.json`.

The credential audit found no configured TechSearch key in the share ZIP.
Two example PEM blocks inside the frozen corpus match the pinned MDN
Web Crypto documentation. The original source excerpts remain intact.

1. Unpack the ZIP into a writable directory and work from that directory. The archive includes the active release, frontend, source notices, and local encoder. Keep the notices with the bundle.
2. Run `python scripts/bootstrap.py --no-tests` with Python 3.11 or 3.12 on the presentation OS. For a disconnected installation, add `--wheelhouse PATH` with a wheelhouse prepared for that OS and Python version, including CPU PyTorch and the build dependencies. The ZIP supplies the runtime assets. Verify dependency installation separately on the destination machine.
3. Run `python -m techsearch doctor --offline` using the new environment's Python (`.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on Linux/macOS). This checks the release and the bundled encoder. The extracted demo can run from its frozen artifacts.
4. Run `python scripts/start.py --host localhost --port 8000`. Open Search at `http://localhost:8000/`. Search for `CORS`, open evidence, inspect attribution, and demonstrate paging. Use `source:mdn "Promise.all"` to show a source constraint and a phrase-safe title match. Legacy flat Stack Overflow bodies and answers still lack reliable phrase boundaries.
5. At `http://localhost:8000/lab`, open **Compare searches** and compare Semantic and Hybrid on `browser event propagation`. Use the execution trace to show which branches ran. **Overview** and **Link analysis** show active release metadata. The source workspace has the historical reports. See the [IR Lab guide](IR_LAB.md) for the report and Development/Test controls.
6. To package an updated active release, run `python -m techsearch package-demo --output artifacts/techsearch-demo-current.zip` using the project environment and a new filename. Verify the resulting ZIP on the destination before presenting.

See the [execution report](EXECUTION_REPORT.md) for the verified release and evidence scope.
