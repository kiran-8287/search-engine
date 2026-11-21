# Local demo run sheet

1. Install with `scripts/bootstrap.py` on the presentation OS. For a disconnected installation supply `--wheelhouse`. Use the environment Python for all `-m techsearch` commands.
2. Start with a validated release. For a bundled release, unpack into a writable directory and run `python -m techsearch doctor --offline`. For an original workspace, follow the README acquisition or legacy-export path and generate the release first.
3. Run `python scripts/start.py --host 127.0.0.1 --port 8000`. Open the local Search page and show a query such as `Promise.all`. Open evidence, inspect source attribution, and demonstrate paging against the same snapshot.
4. Search `source:mdn "Promise.all"` to show a hard source and a phrase-safe title match in this export. Body/answer text in the legacy exports lacks reliable segment boundaries and is excluded from phrase matching. Vote relevant according to your own assessment and apply session feedback on a lexical query. In IR Lab, try `promsie.all` in Fuzzy mode and `querySel*` in Prefix mode.
5. Open IR Lab. Compare Keyword BM25 to Hybrid on a conceptual query. Use the execution trace and score explanations to show which branches ran. A lexical-only release can demonstrate the explicit missing-dense state.
6. Present index and graph data from the active release. Prepare TAAT/DAAT, compression decode, and latent reports with `python -m techsearch experiments --suite all` beforehand. Evaluation cards display saved results only after the runs and judgments exist.
7. For export and portability, run `python -m techsearch package-demo` and keep the extracted source notices with the bundle. Verify the bundle using the offline command and launch on the destination computer in advance.

Actual execution and limitations are documented in [the execution report](EXECUTION_REPORT.md). The current OS is Linux; validate the destination OS separately. Relevance quality remains unmeasured until a properly judged pool is available.
