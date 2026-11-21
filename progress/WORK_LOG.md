# Work log

## Repository intake and source implementation

- Inspected the supplied specification, root collectors, and representative raw records. Kept both collectors at the root and preserved existing exports. No master architecture document was present.
- Wrote project settings, dependencies, a shared ranking service, API, public Search and IR Lab, collection orchestration, evaluation and experiment modules.
- Switched persistence to indexed JSONL, binary postings, NumPy model artifacts, and optional session feedback JSONL. Added atomic activation, artifact fingerprints, a shared repository, fixture data, unit/integration/browser test files, and an authored 600-intent query catalog.
- Added Windows and Linux instructions, setup and launch scripts, local demo packaging, data definitions, and an implementation status table.
- Activity performed consisted of reading workspace files and editing project files. No installation, external acquisition, model download, generated corpus/release, environment creation, test, benchmark, evaluation, or server launch occurred.
- Resume with `scripts/bootstrap.py`, `techsearch doctor`, and `inspect-data`. The existing raw files support the offline `pipeline --resume --lexical-only` route. Run deep validation and the fixture checks before full-corpus measurements or acquisition. Use API credentials only for explicit SO collection and AI annotation.
