# Data dictionary

## Inputs and processed corpus

| Path | Record or format |
| --- | --- |
| `mdn_documents.json` and `stackoverflow_documents.json` | Legacy input arrays supplied in the repository root |
| `data/raw/*.json` | Preferred collector outputs, source-path URL map, collection inventory, browser compatibility metadata |
| `data/raw/history/<sha>/<filename>` | Preserved previous collection outputs |
| `data/manifests/collection-*.json` | Provenance, revision when known, hashes, stages and shortfalls |
| `data/processed/<id>/documents.jsonl` | UTF-8 canonical parent records, one per line |
| `documents.offsets` | Little-endian uint64 byte offsets, one per dense parent ID plus file end |
| `catalog.jsonl` | Dense integer, stable ID, source, topic, title, URL and tags |
| `aliases.jsonl` | Canonical lookup key to dense parent ID |
| `edges.jsonl` | Unique source and destination integer parents |
| `data/quarantine/<id>.json` | Source, raw-array offset and a reason for each rejected record |

Historical Windows corpus manifests are embedded in their release manifests under `artifacts/releases/`. Their rejection reports live under `data/quarantine/`, alongside the same corpus IDs. Use the release manifest's source hashes and provenance to identify its retained inputs.

Parent records contain `id` (source stable ID), `doc` (dense ID), `source`, `topic`, `title`, `url`, `tags`, `metadata`, `segments`, `answers`, and `references`. Original collector segment IDs, explicit anchors, headings, source text and language are kept when available. The local `ordinal` is the dense position in its parent. A segment stores `answer_id` for answer evidence and `field` for ranking. References retain normalized targets, unresolved targets, optional anchors, and cited answer or parent identity. Metadata carries original provenance, content/license fields, and available compatibility enrichment.

### Fixture record

The following abbreviated record is synthetic and exists only to illustrate the canonical shape.

```json
{
  "id": "mdn:web/javascript/fixture-promise/index.md",
  "doc": 0,
  "source": "mdn",
  "topic": "javascript",
  "title": "Fixture Promise.all",
  "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/FixturePromise",
  "tags": [],
  "segments": [{"ordinal": 0, "type": "title", "field": "title", "text": "Fixture Promise.all", "answer_id": null}],
  "metadata": {},
  "answers": [],
  "references": []
}
```

## Index and runtime artifacts

| File | Format |
| --- | --- |
| `forward.bin` | Per-parent zlib blocks containing term → field ID → TF |
| `forward.offsets` | Little-endian uint64 byte positions with terminal sentinel |
| `forward-stats.bin` | Fixed little-endian fields, one uint32 length per lexical field, indexed uint32 length, and float64 weighted norm |
| `postings-{uint32,vb,gamma}.bin` | Independently decodable term payloads |
| `lexicon-{uint32,vb,gamma}.jsonl` | Sorted rows of term, df, cf, start byte, byte count, meaningful bit count |
| `index.json` | Parent/term/posting counts, lengths, codec metrics |
| `vectors.npy` | Two-dimensional little-endian float32 normalized passage matrix |
| `passage-parents.npy` | One little-endian uint32 parent ID per vector row |
| `passages.jsonl` and `passages.offsets` | Passage row, parent, answer and source spans, with random-access offsets |
| `graph.json` | MDN ranks and induced-graph diagnostics |
| `manifest.json` and `active.json` | Release and component fingerprints, source attestations, checksums, sizes and atomic active pointer |
| `data/runtime/<prefix>/<session>/<search>.json` | Saved immutable search output and scope/release/time metadata |
| `data/runtime/<prefix>/<session>/feedback.jsonl` | Optional explicit labels scoped to a snapshot and session |
| `artifacts/runs/<release>/` | Ranked outputs and hardware/configuration context in JSON and CSV |
| `artifacts/reports/<release>/` | Experiment, comparison and metric summaries in JSON and applicable CSV |

Every posting list starts with its document count. Documents are sorted; the fixed baseline stores absolute IDs while compressed payloads store gaps measured from an initial preceding ID of -1. Each document has a field count followed by field ID, TF and tuples of segment ordinal, token ordinal, start offset, end offset, and original-token flag. Ordinals and offsets are zero-based. Offsets index Python Unicode characters and the end is exclusive. Variable byte uses least-significant seven-bit groups with a high-bit terminator. Gamma encodes every stored unsigned value as value plus one and pads the last payload byte with zero bits. Raw text and floats follow their independent representations.

Run metadata is derived only when commands execute. Test fixture records under `tests/fixtures` are isolated from production and from the authored evaluation query catalog.
