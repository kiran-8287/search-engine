import { api, el } from "./shared.js";

export const METHODS = { tfidf: "TF-IDF", bm25: "BM25", likelihood: "Query likelihood", dense: "Semantic", hybrid: "Hybrid" };
const integer = new Intl.NumberFormat();
const dash = "—";
const fixed = (value, places = 2) => Number.isFinite(value) ? value.toFixed(places) : dash;
const count = value => Number.isFinite(value) ? integer.format(value) : dash;
const mib = bytes => Number.isFinite(bytes) ? fixed(bytes / 1048576) : dash;
export const milliseconds = value => Number.isFinite(value) ? fixed(value) + " ms" : dash;

function table(label, columns, rows) {
  const scroller = el("div", null, "table-scroll");
  scroller.tabIndex = 0;
  scroller.setAttribute("role", "region");
  scroller.setAttribute("aria-label", label);
  const grid = el("table");
  grid.setAttribute("aria-label", label);
  const header = grid.createTHead().insertRow();
  for (const name of columns) {
    const th = el("th", name);
    th.scope = "col";
    header.append(th);
  }
  const body = grid.createTBody();
  for (const values of rows) {
    const row = body.insertRow();
    values.forEach((value, index) => {
      const cell = el(index === 0 ? "th" : "td", value);
      if (!index) cell.scope = "row";
      row.append(cell);
    });
  }
  scroller.append(grid);
  return scroller;
}

function detail(label, ...children) {
  const details = el("details", null, "report-details");
  details.append(el("summary", label), ...children);
  return details;
}

function chart(title, bars, maximum, format) {
  const figure = el("figure", null, "chart");
  figure.append(el("figcaption", title));
  for (const [label, value] of bars) {
    const row = el("div", null, "chart-row");
    const bar = el("progress");
    bar.max = maximum || 1;
    bar.value = value;
    bar.setAttribute("aria-label", label);
    row.append(el("span", label), bar, el("span", format(value)));
    figure.append(row);
  }
  return figure;
}

const metricKeys = ["nDCG@10", "P@10", "MRR@10"];
function validQuality(run, quality) {
  return Boolean(run && quality && ["AI-judged", "human", "mixed"].includes(quality.label_type) &&
    Object.keys(METHODS).every(key => quality.sample_counts?.[key] === run.paired_queries &&
      metricKeys.every(metric => {
        const value = quality.aggregates?.[key]?.[metric];
        return Number.isFinite(value) && value >= 0 && value <= 1;
      })));
}

function leaders(entries, places, descending) {
  const rounded = entries.map(([name, value]) => [name, Number(value.toFixed(places))]);
  const best = (descending ? Math.max : Math.min)(...rounded.map(([, value]) => value));
  return rounded.filter(([, value]) => value === best).map(([name]) => name);
}

export function models({ documents, measurement: run, quality, search_settings: settings }) {
  const content = el("div");
  const rated = validQuality(run, quality);
  const timings = run?.timing_ms || {};
  const methods = Object.entries(METHODS);
  if (run) {
    const split = run.split === "test" ? "Final test" : "Development";
    const judged = rated ? { "AI-judged": "AI-judged", human: "Human judgments", mixed: "Mixed judgments" }[quality.label_type]
      : "Quality evaluation is pending";
    content.append(el("p", [
      count(documents) + " documents", count(run.paired_queries) + " of " + count(run.query_count) + " queries",
      split, run.created_at.slice(0, 10), judged,
    ].join(" · "), "measurement-note"));
  } else {
    content.append(el("p", "No compatible measurements are available for the current search data.", "measurement-note"));
  }

  const timing = (key, stat) => timings[key]?.warm?.[stat];
  content.append(table("Retrieval methods", ["Method", "nDCG@10 ↑", "Precision@10 ↑", "MRR@10 ↑", "Median time (ms) ↓", "95th percentile (ms) ↓"],
    methods.map(([key, label]) => [
      label, ...metricKeys.map(metric => fixed(rated ? quality.aggregates[key][metric] : null, 3)),
      fixed(timing(key, "p50")), fixed(timing(key, "p95")),
    ])));

  const scores = rated ? methods.map(([key, label]) => [label, quality.aggregates[key]["nDCG@10"]]) : [];
  const speed = methods.filter(([key]) => Number.isFinite(timing(key, "p50")))
    .map(([key, label]) => [label, timing(key, "p50")]);
  if (scores.length || speed.length) {
    const charts = el("div", null, "metric-charts");
    if (scores.length) charts.append(chart("Ranking quality by method (nDCG@10)", scores, 1, value => fixed(value, 3)));
    if (speed.length) charts.append(chart("Median search time by method", speed, Math.max(...speed.map(([, value]) => value)), milliseconds));
    content.append(charts);
  }

  if (speed.length === methods.length) {
    const fastest = leaders(speed, 2, false);
    const findings = el("div", null, "lab-findings");
    findings.append(el("p", "Lowest measured median time · " + fastest.join(" and ") + "."));
    const tail = methods.filter(([key]) => Number.isFinite(timing(key, "p95")))
      .map(([key, label]) => [label, timing(key, "p95")]);
    if (tail.length === methods.length) {
      const lowestTail = leaders(tail, 2, false);
      if (lowestTail.join() !== fastest.join()) {
        findings.append(el("p", "Lowest measured 95th-percentile time · " + lowestTail.join(" and ") + "."));
      }
    }
    if (rated) {
      const highest = leaders(scores, 3, true);
      findings.append(el("p", "Highest measured nDCG@10 · " + highest.join(" and ") + "."));
      if (highest.length === 1 && fastest.length === 1 && highest[0] !== fastest[0]) {
        findings.append(el("p", "The method with the highest observed ranking quality took " +
          milliseconds(speed.find(([name]) => name === highest[0])[1] - speed.find(([name]) => name === fastest[0])[1]) +
          " longer at the median than the fastest method."));
      }
      findings.append(el("p", "These are observations on this query set. Small differences can vary across runs.", "rank-meta"));
    }
    content.append(findings);
  }

  content.append(detail("What the metrics mean",
    table("Metric definitions", ["Metric", "Meaning"], [
      ["nDCG@10", "How well the first ten results are ordered. More relevant results count more near the top."],
      ["Precision@10", "The proportion of the first ten results graded relevant."],
      ["MRR@10", "How early the first relevant result appears within the top ten."],
      ["Median time", "Typical measured search time."],
      ["95th percentile", "The slower end of the measured search times."],
    ]),
    el("p", "Judges grade relevance from 0 to 3. Grades 2 and 3 count as relevant for Precision and MRR.")));
  if (run) {
    const machine = run.machine || {};
    const coverage = quality ? count(quality.labeled ?? quality.candidates) + " judged pairs, " + count(quality.pending ?? 0) + " pending" : "No matching judgment report";
    const exportLink = el("a", "Export measurements");
    exportLink.href = "/api/v1/exports/reports/lab-" + run.split;
    const body = [
      el("p", run.latency_note),
      el("p", [machine.platform, machine.cpu, machine.logical_cores ? machine.logical_cores + " logical CPU cores" : "", machine.python ? "Python " + machine.python : ""].filter(Boolean).join(" · ")),
      el("p", count(run.repeats) + (run.repeats === 1 ? " timed search" : " timed searches") +
        " per method per query · candidate depth " + count(run.candidate_depth) + " · " + coverage),
      el("p", settings ? "Up to " + count(settings.max_results) + " results per search. TAAT for lexical scoring, BM25 k₁ " +
        settings.k1 + " and b " + settings.b + ", fusion constant " + settings.rrf_k + "." :
        "The lexical methods use TAAT and the same query set."),
      table("Search coverage", ["Method", "Successful", "Unavailable", "Degraded"],
        methods.map(([key, label]) => {
          const outcome = run.outcomes[key] || {};
          return [label, count((outcome.ok ?? 0) - (outcome.degraded ?? 0)), count(outcome.unavailable ?? 0), count(outcome.degraded ?? 0)];
        })),
      el("p", "Timing uses only queries completed by all five methods. The saved run records each excluded query and its reason."),
      exportLink,
    ];
    content.append(detail("Measurement details", ...body));
  }
  return { content, signature: JSON.stringify([documents, run?.run_id, quality?.pending, quality?.candidates,
    rated ? quality.aggregates : null]) };
}

function midpoint(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length ? (sorted[middle] + sorted[Math.floor((sorted.length - 1) / 2)]) / 2 : null;
}

function traversal(report) {
  if (!report?.rows?.length) return [el("p", "Traversal measurements are unavailable.")];
  const fresh = report.rows.filter(row => row.condition === "fresh-index-reader");
  const rows = ["taat", "daat"].map(strategy => {
    const selected = fresh.filter(row => row.strategy === strategy);
    const durations = selected.flatMap(row => row.timings_ms || []).sort((a, b) => a - b);
    const postings = selected.map(row => row.work?.postings_visited).filter(Number.isFinite);
    return [strategy.toUpperCase(), fixed(midpoint(durations)), fixed(durations[Math.ceil(durations.length * .95) - 1]),
      count(midpoint(postings))];
  });
  return [
    el("p", "Both strategies run BM25 on the same " + count(report.queries.length) + " queries."),
    table("Traversal comparison", ["Strategy", "Median (ms)", "95th percentile (ms)", "Median postings visited"], rows),
    el("p", report.equivalent ? "Result IDs, order, and scores agreed on these queries. Timing can vary by workload."
      : "Result agreement is unavailable for this measurement."),
  ];
}

function compression(report) {
  const baseline = report?.codecs?.uint32?.artifact_bytes;
  if (!baseline) return [el("p", "Compression measurements are unavailable.")];
  const labels = { uint32: "Fixed-width", vb: "Variable-byte", gamma: "Gamma" };
  const rows = Object.entries(labels).map(([key, label]) => {
    const codec = report.codecs[key];
    if (!codec) return [label, dash, dash, dash, dash];
    return [label, mib(codec.payload_bytes), mib(codec.artifact_bytes),
      fixed(100 * (baseline - codec.artifact_bytes) / baseline, 1) + "%", fixed(codec.median_lookup_decode_ms)];
  });
  return [
    table("Index compression", ["Encoding", "Postings (MiB)", "Complete (MiB)", "Space saved", "Lookup and decode (ms)"], rows),
    el("p", "Complete size includes the dictionary. Savings use fixed-width as the baseline. The smallest encoding can take longer to decode."),
  ];
}

function authority(run, quality, graph) {
  const timing = run?.authority_timing_ms;
  const judged = validQuality(run, quality) && quality.authority_paired?.queries * run.repeats === timing?.bm25?.observations;
  const methods = [["bm25", "BM25"], ["pagerank", "BM25 + PageRank"]];
  const content = [
    el("p", "PageRank reorders MDN results in the candidate window. Both runs use the same BM25 settings."),
    table("Link authority comparison", ["Method", "nDCG@10", "Median time (ms)", "95th percentile (ms)"], methods.map(([method, name]) => [
      name, fixed(judged ? quality.authority_paired[method] : null, 3), fixed(timing?.[method]?.p50), fixed(timing?.[method]?.p95),
    ])),
  ];
  if (Number.isFinite(timing?.bm25?.p50) && Number.isFinite(timing?.pagerank?.p50)) {
    const change = timing.pagerank.p50 - timing.bm25.p50;
    const qualityChange = judged ? " The observed nDCG@10 change was " + fixed(quality.authority_paired.pagerank - quality.authority_paired.bm25, 3) + "." : " Quality evaluation is pending.";
    content.push(el("p", "PageRank median time change · " + (change > 0 ? "+" : "") + fixed(change) + " ms." + qualityChange));
  }
  if (graph) {
    content.push(detail("Graph details", table("MDN link graph", ["Measure", "Value"], [
      ["Pages", count(graph.parents)], ["Links", count(graph.retained_edges)], ["Isolates", count(graph.isolates)],
      ["Iterations", count(graph.iterations)], ["Final residual", Number.isFinite(graph.residual) ? graph.residual.toExponential(2) : dash],
    ])));
  }
  return content;
}

function feedback(report) {
  const pairs = (report?.rows || []).filter(row => row.methods.rocchio_probe?.probe_document).map(row => {
    const probe = row.methods.rocchio_probe;
    const withoutProbe = hits => hits.filter(hit => hit.id !== probe.probe_document);
    return { row, probe, before: withoutProbe(row.methods.bm25.hits), after: withoutProbe(probe.hits) };
  });
  if (!pairs.length) return [el("p", "The feedback demonstration is unavailable.")];
  const example = pairs.find(pair => pair.before[0]?.id !== pair.after[0]?.id) || pairs[0];
  return [
    el("p", "Demonstration using “" + example.row.query + "”. Rocchio expands the query using the top BM25 result as a test input. That input is omitted below."),
    table("Feedback before and after", ["Rank after omitting the input", "Before", "After"], [0, 1, 2].map(i => [
      String(i + 1), example.before[i]?.title ?? dash, example.after[i]?.title ?? dash,
    ])),
    el("p", "The change shows how feedback can affect a ranking. Independent relevance judgments would be needed to measure an improvement."),
  ];
}

function clusters(report) {
  if (!report?.kmeans || !report?.lsi) return [el("p", "The sampled document exploration is unavailable.")];
  const { kmeans, lsi } = report;
  return [
    el("p", count(report.sample_ids?.length) + " sampled documents · " + count(lsi.dimensions) + " LSI dimensions · silhouette " + fixed(kmeans.silhouette, 3)),
    table("Document clusters", ["Cluster", "Documents", "Representative terms"], Object.entries(kmeans.sizes).map(([key, size]) => [
      "Cluster " + (Number(key) + 1), count(size), kmeans.representative_terms?.[key]?.join(", ") || dash,
    ])),
    el("p", "This explores document groupings. Silhouette measures separation within the sample."),
  ];
}

export async function courseExperiments(context, signal) {
  const content = el("div", null, "course-sections");
  const kinds = ["taat-daat", "compression", "graph", "retrieval", "latent"];
  const replies = await Promise.allSettled(kinds.map(kind => api("/reports/" + kind, { signal })));
  const reports = replies.map(({ value }, index) => {
    if (value?.release_id !== context.release_id) return null;
    if (value.status === "build-only" || kinds[index] === "graph" || value.config_fingerprint === context.configuration ||
      (context.experiment_settings && value.report?.lab_settings === context.experiment_settings)) return value;
    return null;
  });
  const [taat, codecs, graph, retrieval, latent] = reports.map(value => value?.report);
  const sections = [
    ["TAAT versus DAAT", traversal(taat), true],
    ["Compression", compression(codecs), true],
    ["Link authority", authority(context.measurement, context.quality, graph)],
    ["Feedback", feedback(retrieval)],
    ["LSI and K-means", clusters(latent)],
  ];
  for (const [title, body, open] of sections) {
    const disclosure = detail(title, ...body);
    disclosure.open = Boolean(open);
    content.append(disclosure);
  }
  return { content, signature: JSON.stringify([reports.map(value => value?.created_at ?? value?.status),
    context.measurement?.run_id, context.quality?.candidates]) };
}
