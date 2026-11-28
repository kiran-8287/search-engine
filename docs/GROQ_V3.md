# Groq v3 evidence and blind review

The repaired protocol is ready for human review. V1 and v2 are historical diagnostic runs. Their 100 provisional records are excluded from this review and from its comparison.

## Review the complete Development study

1. Open [the offline study review](../artifacts/techsearch-study-review.html) in a browser. No server is needed.
2. Select one of the 50 queries. Its list shows unique documents from the saved top ten of all six methods. Open a title to read the complete indexed source.
3. Add an optional comment and choose grade 0–3 or **Cannot judge**. The choice saves immediately. Reopen a document and select a grade again to edit it.
4. Use **Next unjudged** to continue and **Export review JSON** to save a backup. Attach `techsearch-study-review.json` here when all pairs have a numeric grade.

The page saves progress in the current browser. **Import review JSON** restores an export on another browser. An identical reimport creates no new judgments. Conflicting grades stay in place until reviewed and edited. **Cannot judge** stays pending and does not count as grade 0.

The same document can appear under different queries. Each query–document pair needs its own grade, and that grade applies to every method that retrieved it. The pool has 2,703 top-ten entries, 1,085 pairs, and 1,037 distinct documents.

Chromium verified the complete study page offline, including document previews, edits, reload persistence, next-unjudged navigation, and JSON import and export. Synthetic checks covered a repeated document under different queries, duplicate and conflicting imports, and the partial-export scoring gate. The full suite passed 92 tests. [Study review browser receipt](../artifacts/execution/groq-dev50/study-review-browser/verification.json)

Compatible exports from the earlier [50-pair pilot page](../artifacts/techsearch-human-review.html) can be imported. Compatibility checks bind those pair identities to the same release, frozen study, and interpretation protocol. The earlier page and its files remain available.

To regenerate the study page from the saved rankings, use the offline preparation command.

```powershell
.\.venv\Scripts\python.exe -m techsearch prepare-review
```

## Compare the complete review

```powershell
.\.venv\Scripts\python.exe -m techsearch compare-review techsearch-study-review.json
```

Provide the path to the exported JSON. The command verifies pair identity and reports counts for partial files. It waits for numeric grades on all 1,085 pairs before saving `evaluation-lab-groq-dev50-human.json` in the active release’s report directory. The comparison uses the same 50 queries and all six saved methods. It writes a separate human report.

- **nDCG@10** uses graded gains of `2^grade - 1` and the ideal order within the judged pool.
- **Precision@10** and **MRR@10** count grades 2 and 3 as relevant. Precision uses a denominator of ten.
- Queries with no grades 2–3 stay in the average and contribute zero Precision and MRR. A grade of 1 can still contribute to nDCG. If the ideal gain is zero, nDCG is zero.
- Successful empty lists stay in the comparison with zero scores. The frozen study has no excluded queries. Unjudged pairs and abstentions have no numeric grade.

## Evidence and judgment

The v3 selector reserves nonempty answer material before long questions fill the packet. It keeps question context, whole code lines, neighboring explanation, answer IDs, and clipping positions. A packet that cannot fit a useful answer block reports insufficient context. The complete indexed source is available on the review page.

The payload distinguishes exact identifiers and operators using original token positions. Phrase constraints use consecutive original tokens within one field and segment, including code comments. Metadata and Boolean checks reuse the retrieval matcher. A fact distinguishes the full source from visible excerpts. It describes a lexical match, while the grade measures how much the evidence helps satisfy the query.

The rubric uses 0 for an unrelated, unusable, or incompatible result, 1 for little help, 2 for substantial but incomplete help, and 3 for direct and sufficient help. An abstention indicates missing essential evidence. A related API can be useful when the source helps with the specific need. Inputs and expected output alone do not establish a solution. The exact prompt and source policy are in [judging_v3.py](../src/techsearch/judging_v3.py).

The earlier v3 diagnostic batch used the existing 50 v2 pairs. Its identity binds the prompt, evidence policy, positional analyzer, interpretations, and source artifacts. The complete study review reuses those interpretations and the same Development release, and grades each verified pair once. [Study manifest](../data/evaluation/groq-dev50-study-review.json)

## Verification and next gate

Offline replay checked the primary and expanded payloads for all 50 pairs. All five v2 examples that had lost their answers now contain answers in both packets. Fourteen explicit constraints matched the active index. The replay verified that `querySelectorAll` does not establish an exact `querySelector` match, retained `fileSizeInBytes /= 1024`, and located `form data` in both the code comment and the answer text that v2 adjudication overlooked. [Offline evidence receipt](../artifacts/execution/groq-dev50/v3-evidence-verification.json)

All 90 tests passed. Release validation passed. Chromium checked offline review save, reload, export, import, and mobile layout. It also verified Search, Preview, pagination, all three IR Lab tabs, and report exports on the active release. The browser used synthetic form inputs for verification. [Review browser receipt](../artifacts/execution/groq-dev50/human-review-browser/verification.json) · [Active release smoke checks](../artifacts/execution/groq-dev50/v3-app-browser/app-verification.json)

The shared ledger has 126 attempts, including all 69 v1 and 57 v2 attempts, and 124,342 reported tokens. No provider requests were made to prepare the study review. All 1,085 pairs are pending until human judgments are supplied.

The human comparison runs locally with a complete export. Any separate Groq comparison requires its own authorization. Test stays sealed.
