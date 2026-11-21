import { $, addOptions, api, el, resultItem, showJson, titleCase } from "./shared.js";

const modes = [["keyword", "Keyword"], ["boolean", "Boolean"], ["phrase", "Phrase"], ["prefix", "Prefix"],
  ["fuzzy", "Fuzzy"], ["semantic", "Semantic"], ["hybrid", "Hybrid"], ["field", "Field-specific"]];
const form = $("#compare");
const status = $("#status");
const panels = [];
let comparison;
let reportWork;

function fields(name, defaultMode) {
  const container = el("fieldset");
  const controls = el("div", null, "settings");
  const checks = el("div", null, "checks");
  const inputs = {};
  function select(key, label, options, value) {
    const wrapper = el("label", label, "control");
    const input = addOptions(el("select"), options);
    input.value = value;
    wrapper.append(input);
    controls.append(wrapper);
    inputs[key] = input;
  }
  function numeric(key, label, min, max, step, placeholder) {
    const wrapper = el("label", label, "control");
    const input = el("input");
    Object.assign(input, { type: "number", min, max, step, placeholder });
    wrapper.append(input);
    controls.append(wrapper);
    inputs[key] = input;
  }
  function checkbox(key, label) {
    const wrapper = el("label");
    const input = el("input");
    input.type = "checkbox";
    wrapper.append(input, document.createTextNode(" " + label));
    checks.append(wrapper);
    inputs[key] = input;
  }
  select("mode", "Mode", modes, defaultMode);
  select("ranker", "Lexical ranker", [["bm25", "BM25"], ["tfidf", "TF-IDF cosine"], ["likelihood", "Dirichlet likelihood"]], "bm25");
  select("strategy", "Execution", [["taat", "TAAT"], ["daat", "DAAT"]], "taat");
  select("source", "Source", [["", "All sources"], ["mdn", "MDN"], ["stackoverflow", "Stack Overflow"]], "");
  select("topic", "Topic", [["", "All topics"]], "");
  numeric("k1", "BM25 k₁", .01, 5, .01, "1.2");
  numeric("b", "BM25 b", 0, 1, .01, "0.75");
  numeric("cutoff", "Dense cosine cutoff", .01, .99, .01, "Configured");
  numeric("rrf_k", "RRF k", 1, 500, 1, "60");
  numeric("depth", "Candidate depth", 1, 1000, 1, "Configured");
  checkbox("authority", "MDN authority");
  checkbox("diversify", "MMR");
  container.append(el("legend", name), controls, checks);
  $("#configurations").append(container);
  return inputs;
}

panels.push(fields("Method A", "keyword"), fields("Method B", "hybrid"));
api("/filters").then(({ topic }) => {
  panels.forEach((panel) => addOptions(panel.topic, topic.map((value) => [value, titleCase(value)])));
}).catch(() => {});

function options(inputs) {
  const result = { query: $("#query").value.trim(), page_size: 10 };
  for (const [key, control] of Object.entries(inputs)) {
    if (control.type === "checkbox") result[key] = control.checked;
    else if (control.value) result[key] = control.type === "number" ? control.valueAsNumber : control.value;
  }
  return result;
}

function panel(name, data) {
  const cell = el("div", null, "rank-panel");
  cell.append(el("h2", name));
  if (data.error) {
    cell.append(el("p", data.error));
    return cell;
  }
  cell.append(el("p", data.total + " ranked results · " + Math.round(data.timing_ms) + " ms", "meta"));
  if (!data.total) cell.append(el("p", "No matches."));
  for (const warning of data.warnings) cell.append(el("p", warning));
  const exportLink = el("a", "Export ranking");
  exportLink.href = "/api/v1/exports/search/" + data.search_id;
  cell.append(exportLink, showJson("Execution trace", data.trace));
  const list = el("ol", null, "results");
  list.append(...data.results.map((hit) => resultItem(hit, { lab: true })));
  cell.append(list);
  return cell;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  comparison?.abort();
  comparison = new AbortController();
  const { signal } = comparison;
  status.textContent = "Comparing methods…";
  try {
    const result = await api("/compare", { body: { left: options(panels[0]), right: options(panels[1]) }, signal });
    if (signal.aborted) return;
    $("#rankings").replaceChildren(panel("Method A", result.left), panel("Method B", result.right));
    status.textContent = "Comparison ready.";
  } catch (error) {
    if (!signal.aborted) {
      $("#rankings").replaceChildren();
      status.textContent = error.message;
    }
  }
});

const reports = [["index", "Index"], ["compression", "Compression"], ["taat-daat", "TAAT / DAAT"],
  ["graph", "Graph"], ["retrieval", "Rankers / feedback"], ["latent", "LSI / K-means"], ["benchmark-dev", "Dev benchmark"],
  ["evaluation-dev", "Dev metrics"], ["benchmark-test", "Test benchmark"], ["evaluation-test", "Test metrics"],
  ["ablations-dev", "Dev ablations"], ["ablations-test", "Test ablations"],
  ["evaluation-ablations-dev", "Dev ablation metrics"], ["evaluation-ablations-test", "Test ablation metrics"]];

function bytes(value) {
  return new Intl.NumberFormat().format(value) + " bytes";
}

function chart(codecs) {
  const section = el("div", null, "chart");
  section.append(el("p", "Complete postings artifact size"));
  const max = Math.max(1, ...Object.values(codecs).map((item) => item.artifact_bytes));
  for (const [name, stats] of Object.entries(codecs)) {
    const row = el("div");
    const bar = el("progress");
    bar.max = max;
    bar.value = stats.artifact_bytes;
    bar.setAttribute("aria-label", name + " artifact size");
    row.append(el("span", name), bar, el("span", bytes(stats.artifact_bytes)));
    section.append(row);
  }
  return section;
}

async function selectReport(name, label) {
  reportWork?.abort();
  reportWork = new AbortController();
  const { signal } = reportWork;
  const display = $("#report");
  for (const button of $("#report-tabs").children) button.setAttribute("aria-pressed", String(button.dataset.name === name));
  display.replaceChildren(el("p", "Loading " + label.toLowerCase() + "…"));
  try {
    const value = await api(name === "index" ? "/index" : "/reports/" + name, { signal });
    if (signal.aborted) return;
    display.replaceChildren(el("h3", label));
    if (value.status === "not-run") {
      display.append(el("p", "This experiment has not been run for the active release."));
      return;
    }
    if (value.status === "blocked" || value.status === "partial") {
      display.append(el("p", value.report.reason), showJson("Evaluation status", value.report));
      return;
    }
    if (value.status === "build-only") display.append(el("p", "Sizes are available from the index build. The decode comparison has not been run."));
    const report = name === "index" ? value : value.report;
    if (report.codecs) display.append(chart(report.codecs));
    if (name === "index") display.append(el("p", report.lexical.parents + " parents · " + report.lexical.vocabulary + " terms · " + bytes(report.artifact_bytes)));
    if (report.retained_edges !== undefined) display.append(el("p", report.parents + " MDN pages · " + report.retained_edges + " edges · " + report.isolates + " isolates"));
    if (report.aggregates) {
      const list = el("ul");
      for (const [method, metrics] of Object.entries(report.aggregates)) {
        list.append(el("li", method + " · " + Object.entries(metrics).map(([key, val]) =>
          key + " " + (typeof val === "number" ? val.toFixed(3) : "unavailable")).join(" · ")));
      }
      display.append(el("p", "AI-judged relevance"), list);
    }
    display.append(showJson("Report details", report));
    if (name !== "index") {
      const exportLink = el("a", "Export JSON");
      exportLink.href = "/api/v1/exports/reports/" + name;
      display.append(exportLink);
    }
  } catch (error) {
    if (!signal.aborted) display.replaceChildren(el("p", error.message));
  }
}

for (const [name, label] of reports) {
  const button = el("button", label, "secondary");
  button.dataset.name = name;
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => selectReport(name, label));
  $("#report-tabs").append(button);
}
selectReport("index", "Index");
