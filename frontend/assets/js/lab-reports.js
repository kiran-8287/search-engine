import { api, el, showJson } from "./shared.js";

const number = new Intl.NumberFormat();
const count = (value) => Number.isFinite(value) ? number.format(value) : "Unavailable";
const bytes = (value) => Number.isFinite(value) ? count(value) + " bytes" : "Unavailable";
const ms = (value) => Number.isFinite(value) ? value.toFixed(2) + " ms" : "Unavailable";
const methods = { auto: "Auto", bm25: "BM25", tfidf: "TF-IDF cosine", dense: "Semantic",
  hybrid: "Hybrid", likelihood: "Dirichlet likelihood", authority: "Auto with MDN authority",
  mmr: "Auto with MMR" };
const labelFor = (name) => methods[name] || name;
const codecs = { uint32: "Fixed-width", vb: "Variable-byte", gamma: "Gamma" };

const statusNames = {
  "available": "Saved report",
  "build-only": "Build statistics",
  "not-run": "Not generated",
  "blocked": "Blocked",
  "partial": "Judgments incomplete",
  "invalid": "Report data unavailable",
};

const groups = [
  ["Compare searches", ["retrieval"]],
  ["Speed & execution", ["taat-daat", "benchmark-dev", "benchmark-test"]],
  ["Compression", ["compression"]],
  ["Link analysis", ["graph"]],
  ["Topics & clusters", ["latent"]],
  ["Evaluation", ["evaluation-dev", "evaluation-test", "ablations-dev", "ablations-test",
    "evaluation-ablations-dev", "evaluation-ablations-test"]],
];

function table(parent, name, headers, rows) {
  if (!rows.length) return;
  const frame = el("div", null, "table-scroll");
  if (headers.length === 2) frame.classList.add("fact-table");
  frame.tabIndex = 0;
  frame.setAttribute("role", "region");
  frame.setAttribute("aria-label", name);
  const element = el("table");
  const header = element.createTHead().insertRow();
  for (const label of headers) {
    const cell = el("th", label);
    cell.scope = "col";
    header.append(cell);
  }
  element.prepend(el("caption", name, "sr-only"));
  const body = element.createTBody();
  for (const values of rows) {
    const row = body.insertRow();
    for (const value of values) row.append(el("td", value ?? "Unavailable"));
  }
  frame.append(element);
  parent.append(frame);
}

function facts(parent, name, rows) {
  table(parent, name, ["Measure", "Value"], rows.filter(([, value]) => value != null));
}

function reportPath(name, releaseId, exportReport = false) {
  return (exportReport ? "/exports/reports/" : "/reports/") + name +
    "?release=" + encodeURIComponent(releaseId);
}

async function readReport(name, releaseId, signal) {
  try {
    const saved = await api(reportPath(name, releaseId), { signal });
    if (saved.release_id === releaseId && saved.name === name) return saved;
    throw new Error("The returned report does not match the selected release.");
  } catch (error) {
    if (signal.aborted) throw error;
    return { name, release_id: releaseId, status: "invalid", error: error.message };
  }
}

function reportBlock(parent, title, saved) {
  const block = el("section", null, "report-block");
  const head = el("div", null, "report-heading");
  const exportLink = el("a", "Export JSON");
  exportLink.href = "/api/v1" + reportPath(saved.name, saved.release_id, true);
  head.append(el("h3", title), exportLink);
  block.append(head);
  const details = [statusNames[saved.status], saved.created_at];
  if (saved.config_fingerprint) details.push("Config " + saved.config_fingerprint);
  block.append(el("p", details.filter(Boolean).join(" · "), "report-meta"));
  parent.append(block);
  return block;
}

function finishReport(block, saved) {
  block.append(showJson("Report details", saved.report));
  if (saved.configuration) block.append(showJson("Saved configuration", saved.configuration));
}

function emptyState(parent, missing, historical, steps) {
  if (!missing.length) return;
  const note = el("div", null, "report-notice");
  for (const [label, saved] of missing) {
    if (saved.status === "not-run") {
      note.append(el("p", label + " has not been generated for " + (historical ? "this historical release." : "the active release.")));
    } else {
      note.append(el("p", label + " is unavailable. " + (saved.error || "Check the saved report.")));
    }
  }
  if (historical) {
    note.append(el("p", "Choose the active release to see its reports and generation steps."));
  } else if (steps?.length) {
    note.append(el("p", "To generate the missing report, run from the project environment."));
    if (steps.some((step) => step.includes("--confirm-sealed"))) {
      note.append(el("p", "Finalize settings on Development before running the held-out Test split."));
    }
    for (const step of steps) {
      const command = el("pre", null, "report-command");
      command.append(el("code", step));
      note.append(command);
    }
  }
  parent.append(note);
}

function present(saved) {
  return saved.status !== "invalid" && saved.status !== "not-run";
}

async function overview(parent, inventory, signal) {
  const index = await api("/index", { signal });
  if (index.release_id !== inventory.active_release_id) throw new Error("The active release changed. Reload the Lab.");
  const dense = index.dense;
  facts(parent, "Index summary", [
    ["Active release", index.release_id],
    ["Documents", count(index.lexical.parents)],
    ["Vocabulary", count(index.lexical.vocabulary)],
    ["Postings", count(index.lexical.postings)],
    ["Passages", dense ? count(dense.passages) : "Unavailable"],
    ["Lexical index", "Available"],
    ["Dense index", dense ? "Available" : "Unavailable"],
    ["Release artifacts", bytes(index.artifact_bytes)],
    ["Vector file (included above)", dense ? bytes(dense.bytes) : null],
  ]);
  parent.append(el("p", "Release size is the sum of the files listed in its manifest. It includes all shipped posting encodings and excludes the manifest itself, the model, raw exports, and run reports.", "lab-intro"));
  parent.append(el("h3", "Active release report status"));
  table(parent, "Saved experiment status", ["Section", "Status"], groups.map(([label, names]) => {
    const statuses = names.map((name) => inventory.releases[index.release_id]?.[name]);
    const notes = [];
    const saved = statuses.filter((status) => status === "available").length;
    if (saved) notes.push(saved + (saved === 1 ? " saved report" : " saved reports"));
    if (statuses.includes("build-only")) notes.push("Build statistics available");
    if (statuses.includes("blocked") || statuses.includes("partial")) notes.push("Judgments pending");
    if (statuses.includes("invalid")) notes.push("Report data unavailable");
    const missing = statuses.filter((status) => !status || status === "not-run").length;
    if (missing) notes.push(missing === names.length ? "No saved reports" : "Some reports not generated");
    return [label, notes.join(" · ")];
  }));
}

function renderCompression(parent, saved, context) {
  const command = "python -m techsearch experiments --suite compression";
  if (!present(saved)) return emptyState(parent, [["Compression comparison", saved]], context.historical, [command]);
  const block = reportBlock(parent, "Posting representations", saved);
  const values = saved.report.codecs || {};
  const entries = Object.entries(codecs).filter(([name]) => values[name]);
  const max = Math.max(1, ...entries.map(([name]) => values[name].artifact_bytes));
  const chart = el("div", null, "chart");
  chart.append(el("p", "Complete size of postings and dictionary"));
  for (const [name, label] of entries) {
    const row = el("div", null, "chart-row");
    const bar = el("progress");
    bar.max = max;
    bar.value = values[name].artifact_bytes;
    bar.setAttribute("aria-label", label + " artifact size");
    row.append(el("span", label), bar, el("span", bytes(bar.value)));
    chart.append(row);
  }
  block.append(chart);
  table(block, "Compression sizes", ["Representation", "Postings payload", "Dictionary", "Complete size"], entries.map(([name, label]) => {
    const stats = values[name];
    return [label, bytes(stats.payload_bytes), bytes(stats.metadata_bytes), bytes(stats.artifact_bytes)];
  }));
  const measured = entries.filter(([name]) => Number.isFinite(values[name].median_lookup_decode_ms));
  if (measured.length) {
    const repeats = count(saved.report.repeats);
    const terms = count(saved.report.terms?.length);
    block.append(el("p", "Saved lookup and decoding measurement · " + terms + " terms · " + repeats + " repeats."));
    table(block, "Lookup and decode timings", ["Representation", "Median"], measured.map(([name, label]) =>
      [label, ms(values[name].median_lookup_decode_ms)]));
  } else {
    emptyState(block, [["The lookup and decode comparison", { status: "not-run" }]], context.historical, [command]);
  }
  finishReport(block, saved);
}

function benchmarkTables(block, report) {
  const outcomes = Object.entries(report.outcomes || {});
  const firstMethod = outcomes[0]?.[1];
  const workload = firstMethod ? (firstMethod.ok ?? 0) + (firstMethod.unavailable ?? 0) : null;
  facts(block, "Benchmark settings", [
    ["Run ID", report.run_id], ["Query groups", count(workload)], ["Repeats", count(report.repeats)],
    ["Candidates per method", count(report.candidate_depth)],
    ["Peak process resident memory", bytes(report.benchmark_peak_process_rss_bytes)],
    ["Query protocol", report.protocol], ["Cache conditions", report.latency_note],
  ]);
  table(block, "Benchmark outcomes", ["Method", "Completed", "Degraded¹", "Unavailable"], outcomes.map(([method, values]) =>
    [labelFor(method), count(values.ok ?? 0), count(values.degraded ?? 0), count(values.unavailable ?? 0)]));
  if (outcomes.length) block.append(el("p", "¹ A degraded query completed using a fallback. It is included in Completed.", "report-meta"));
  const timings = [];
  for (const [method, passes] of Object.entries(report.timing_ms || {})) {
    for (const [pass, stats] of Object.entries(passes)) {
      const condition = pass === "first-query-pass" ? "First pass" : "Later passes";
      timings.push([labelFor(method), condition, ms(stats.p50), ms(stats.p95), count(stats.observations)]);
    }
  }
  table(block, "Repeated benchmark timings", ["Method", "Pass", "Median", "95th percentile", "Samples"], timings);
}

function splitCommand(command, split, ablations = false) {
  return "python -m techsearch " + command + " --split " + split +
    (ablations ? " --ablations" : "") + (split === "test" ? " --confirm-sealed" : "");
}

function renderSpeed(parent, benchmark, traversal, context) {
  parent.append(el("p", "Latency is elapsed search time. The median is the middle observation; the 95th percentile shows the slower end. Memory and work counts describe execution, while judged quality appears under Evaluation.", "lab-intro"));
  const missing = [];
  const commands = [];
  if (present(benchmark)) {
    const block = reportBlock(parent, "Repeated benchmark", benchmark);
    benchmarkTables(block, benchmark.report);
    finishReport(block, benchmark);
  } else {
    missing.push(["The repeated search benchmark", benchmark]);
    commands.push(splitCommand("benchmark", context.split));
  }
  if (present(traversal)) {
    const block = reportBlock(parent, "Term-at-a-time and document-at-a-time", traversal);
    const report = traversal.report;
    block.append(el("p", "This check verifies identical result IDs, order and scores for its own query workload, independent of the selected split. It also measures elapsed time and work for each traversal."));
    facts(block, "Traversal workload", [
      ["Queries", report.queries?.join(" · ")], ["Repeats", count(report.repeats)], ["Reader and cache conditions", report.note],
    ]);
    block.append(el("p", "Postings visited counts entries considered. Accumulators track scores or pending lists. Peak Python memory is the traced allocation for a run."));
    const rows = (report.rows || []).map((row) => [
      row.query, row.condition === "fresh-index-reader" ? "Fresh reader" : "Reused reader",
      row.strategy?.toUpperCase(), ms(row.p50_ms), ms(row.p95_ms),
      count(row.work?.postings_visited), count(row.work?.comparisons), count(row.work?.peak_accumulators),
      bytes(row.traced_python_peak_bytes),
    ]);
    table(block, "Execution timings", ["Query", "Condition", "Strategy", "Median", "95th percentile",
      "Postings visited", "Comparisons", "Peak accumulators", "Peak Python memory"], rows);
    finishReport(block, traversal);
  } else {
    missing.push(["The TAAT/DAAT timing and equivalence check", traversal]);
    commands.push("python -m techsearch experiments --suite taat-daat");
  }
  emptyState(parent, missing, context.historical, commands);
}

function renderRetrieval(parent, saved, context) {
  const secondary = el("details", null, "report-details");
  secondary.append(el("summary", "Saved ranker & feedback experiments"));
  secondary.append(el("p", "These experiments record the effect of authority, diversification (MMR), and a Rocchio query-expansion probe. Live session feedback can be tried on Search.", "lab-intro"));
  if (!present(saved)) {
    emptyState(secondary, [["The saved ranker and feedback comparison", saved]], context.historical,
      ["python -m techsearch experiments --suite retrieval"]);
  } else {
    const block = reportBlock(secondary, "Saved interventions", saved);
    const report = saved.report;
    if (report.label_policy) block.append(el("p", report.label_policy));
    const rows = (report.rows || []).map(({ query, methods: values }) => [
      query, values.bm25?.hits?.[0]?.id, values.likelihood?.hits?.[0]?.id,
      values.pagerank?.hits?.[0]?.id, values.mmr?.hits?.[0]?.id, values.rocchio_probe?.expansion?.join(", ") || "—",
    ]);
    table(block, "Ranking interventions", ["Query", "BM25 first hit", "Likelihood first hit",
      "Authority first hit", "MMR first hit", "Rocchio expansion"], rows);
    finishReport(block, saved);
  }
  parent.append(secondary);
}

function renderLinks(parent, graph, retrieval, context) {
  parent.append(el("p", "PageRank passes weight along links between MDN pages. Optional authority reranking reorders MDN hits within the configured result window. A rank change alone does not establish relevance.", "lab-intro"));
  const missing = [];
  const commands = [];
  if (present(graph)) {
    const block = reportBlock(parent, "MDN link graph", graph);
    const report = graph.report;
    facts(block, "Graph summary", [
      ["MDN pages", count(report.parents)], ["Retained edges", count(report.retained_edges)],
      ["Isolates (no incoming or outgoing links)", count(report.isolates)],
      ["Dangling nodes (no outgoing links)", count(report.dangling)], ["PageRank damping", report.damping],
      ["PageRank iterations", count(report.iterations)], ["Final change", report.residual?.toExponential(3)],
      ["Convergence tolerance", report.tolerance?.toExponential(3)],
    ]);
    finishReport(block, graph);
  } else {
    missing.push(["The link graph", graph]);
    commands.push("python -m techsearch build-graph");
  }
  if (present(retrieval)) {
    const block = reportBlock(parent, "Saved authority comparison", retrieval);
    const rows = (retrieval.report.rows || []).map(({ query, methods: values }) =>
      [query, values.bm25?.hits?.[0]?.id, values.pagerank?.hits?.[0]?.id]);
    table(block, "Authority comparison", ["Query", "BM25 first hit", "BM25 with authority first hit"], rows);
    finishReport(block, retrieval);
  } else {
    missing.push(["The authority comparison", retrieval]);
    commands.push("python -m techsearch experiments --suite retrieval");
  }
  emptyState(parent, missing, context.historical, commands);
}

function renderTopics(parent, saved, context) {
  parent.append(el("p", "These academic experiments use a sample of documents. LSI reduces the term space to fewer dimensions, and K-means groups similar document vectors.", "lab-intro"));
  if (!present(saved)) return emptyState(parent, [["The sampled LSI and K-means report", saved]], context.historical,
    ["python -m techsearch experiments --suite latent"]);
  const block = reportBlock(parent, "Saved LSI and K-means sample", saved);
  const report = saved.report;
  const lsi = report.lsi || {};
  const clusters = report.kmeans || {};
  facts(block, "Topic and cluster diagnostics", [
    ["Sampled documents", count(report.sample_ids?.length)], ["Sample vocabulary", count(report.vocabulary)],
    ["LSI dimensions", count(lsi.dimensions)], ["Explained variance ratio", lsi.explained_variance_ratio?.toFixed(4)],
    ["Requested clusters", count(clusters.clusters)], ["Effective clusters", count(clusters.effective_clusters)],
    ["Inertia (within-cluster spread)", clusters.inertia?.toFixed(3)],
    ["Silhouette (cluster separation)", clusters.silhouette?.toFixed(3) ?? "Unavailable"],
  ]);
  table(block, "Cluster sizes", ["Cluster", "Documents"], Object.entries(clusters.sizes || {}).map(([id, size]) => [id, count(size)]));
  finishReport(block, saved);
}

function evaluationReport(block, saved) {
  const report = saved.report;
  if (saved.status === "blocked" || saved.status === "partial") {
    const notice = el("div", null, "report-notice");
    notice.append(el("p", "Relevance metrics unavailable. " + (report.reason || "The judgment pool is incomplete.")));
    if (Number.isFinite(report.pending)) notice.append(el("p", count(report.pending) + " pending judgments."));
    notice.append(el("p", "Complete the judgment pool for this exact release, split and run before reporting metrics."));
    block.append(notice, showJson("Evaluation status", report));
    if (saved.configuration) block.append(showJson("Saved configuration", saved.configuration));
    return;
  }
  const aggregates = Object.entries(report.aggregates || {});
  const metrics = [...new Set(aggregates.flatMap(([, values]) => Object.keys(values)))];
  block.append(el("p", aggregates.length ? "AI-judged relevance" : "Relevance metrics unavailable."));
  table(block, "Relevance metrics", ["Method", ...metrics], aggregates.map(([method, values]) =>
    [labelFor(method), ...metrics.map((metric) => values[metric]?.toFixed(3))]));
  finishReport(block, saved);
}

function evaluationProtocol(parent, context, inventory) {
  const protocol = inventory.protocol;
  parent.append(el("p", "Use Development to choose settings. Keep Test held out until settings are final. Opening a saved Test report here only reads existing results.", "lab-intro"));
  parent.append(el("h3", "Current local protocol"));
  if (context.historical) parent.append(el("p", "These are the catalog and settings in this workspace. Archived runs record the protocol they actually used.", "lab-intro"));
  facts(parent, "Evaluation protocol", [
    ["Frozen query groups for this split", count(protocol.groups?.[context.split])],
    ["Catalog fingerprint", protocol.fingerprint ?? "Unavailable"],
    ["Judgment pool depth", count(protocol.pool_depth)], ["Pooled recall depth", count(protocol.recall_depth)],
    ["Benchmark repeats", count(protocol.latency_repeats)],
  ]);
  parent.append(el("p", "Relevance requires a completed judgment pool. It measures P@5, P@10, nDCG@10, MRR@10 and pooled recall. Missing judgments leave these metrics unavailable."));
  parent.append(el("h3", "Selected release and split"));
  const availability = inventory.releases[context.releaseId] || {};
  table(parent, "Evaluation report status", ["Report", "Status"], [
    ["Repeated benchmark", "benchmark"], ["Judged relevance", "evaluation"],
    ["Feature comparison run", "ablations"], ["Feature comparison relevance", "evaluation-ablations"],
  ].map(([label, name]) => [label, statusNames[availability[name + "-" + context.split] || "not-run"]]));
}

export async function renderReports(state, inventory, signal) {
  const content = document.createDocumentFragment();
  if (state.section === "overview") {
    await overview(content, inventory, signal);
    return content;
  }

  const releaseId = state.release || inventory.active_release_id;
  const context = { releaseId, split: state.split, historical: releaseId !== inventory.active_release_id };
  const provenance = el("p", (context.historical ? "Historical release " : "Active release ") +
    releaseId, context.historical ? "report-release historical" : "report-release");
  content.append(provenance);
  const get = (name) => readReport(name, releaseId, signal);

  switch (state.section) {
    case "compare":
      renderRetrieval(content, await get("retrieval"), context);
      break;
    case "speed": {
      const reports = await Promise.all([get("benchmark-" + state.split), get("taat-daat")]);
      renderSpeed(content, ...reports, context);
      break;
    }
    case "compression":
      renderCompression(content, await get("compression"), context);
      break;
    case "links": {
      const reports = await Promise.all([get("graph"), get("retrieval")]);
      renderLinks(content, ...reports, context);
      break;
    }
    case "topics":
      renderTopics(content, await get("latent"), context);
      break;
    case "evaluation": {
      if (state.view === "protocol") {
        evaluationProtocol(content, context, inventory);
        break;
      }
      const steps = [];
      const missing = [];
      if (state.view === "features") {
        content.append(el("p", "Feature comparisons (ablations) change one component at a time under the same comparison conditions. Saved execution results and judged relevance measure different things.", "lab-intro"));
        const [run, relevance] = await Promise.all([get("ablations-" + state.split), get("evaluation-ablations-" + state.split)]);
        if (present(run)) {
          const block = reportBlock(content, "Feature comparison execution", run);
          benchmarkTables(block, run.report);
          finishReport(block, run);
        } else {
          missing.push(["The feature comparison run", run]);
          steps.push(splitCommand("benchmark", state.split, true));
        }
        if (present(relevance)) evaluationReport(reportBlock(content, "Feature comparison relevance", relevance), relevance);
        else {
          missing.push(["Judged feature comparison metrics", relevance]);
          steps.push(splitCommand("evaluate", state.split, true));
        }
      } else {
        content.append(el("p", "Relevance metrics measure the quality of results using a completed pool of judgments. Missing judgments leave metrics unavailable.", "lab-intro"));
        const saved = await get("evaluation-" + state.split);
        if (present(saved)) evaluationReport(reportBlock(content, "Judged relevance", saved), saved);
        else {
          missing.push(["The judged relevance report", saved]);
          const available = inventory.releases[releaseId]?.["benchmark-" + state.split];
          if (available !== "available") steps.push(splitCommand("benchmark", state.split));
          steps.push(splitCommand("evaluate", state.split));
        }
      }
      emptyState(content, missing, context.historical, steps);
      break;
    }
  }
  return content;
}
