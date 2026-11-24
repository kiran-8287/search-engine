# Local demo run sheet

The demo archive is `artifacts/techsearch-demo-250a15ecd349951d6c69364c.zip`. Keyword, semantic and hybrid searches passed from an extracted copy on Windows with Python socket access and DNS blocked. See the [verification record](../artifacts/execution/offline-demo-250a15ecd349951d6c69364c.json) for the archive checksum and search results.

1. Unpack the ZIP into a writable directory and work from that directory. The archive includes the active release, frontend, source notices, and local encoder. Keep the notices with the bundle.
2. Run `python scripts/bootstrap.py --no-tests` with Python 3.11 or 3.12 on the presentation OS. For a disconnected installation, add `--wheelhouse PATH` with a wheelhouse prepared for that OS and Python version, including CPU PyTorch and the build dependencies. The ZIP supplies the runtime assets. Verify dependency installation separately on the destination machine.
3. Run `python -m techsearch doctor --offline` using the new environment's Python (`.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on Linux/macOS). This checks the release and the bundled encoder. The extracted demo can run from its frozen artifacts.
4. Run `python scripts/start.py --host localhost --port 8000`. Open Search at `http://localhost:8000/`. Search for `CORS`, open evidence, inspect attribution, and demonstrate paging. Use `source:mdn "Promise.all"` to show a source constraint and a phrase-safe title match. Legacy flat Stack Overflow bodies and answers still lack reliable phrase boundaries.
5. At `http://localhost:8000/lab`, open **Compare searches** and compare Keyword BM25 to Hybrid on `browser event propagation`. Use the execution trace to show which branches ran. **Overview** and **Link analysis** show active release metadata. Use **Saved report release** to view archived experiments. See the [IR Lab guide](IR_LAB.md) for report availability and the Development/Test controls.
6. To package an updated active release, run `python -m techsearch package-demo` in its workspace. Verify the resulting ZIP on the destination before presenting.

See the [execution report](EXECUTION_REPORT.md) for the verified release and evidence scope.
