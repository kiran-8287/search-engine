import { $, SEARCH_LOCATION_KEY, addOptions, api, createPreview, el, resultItem, showJson, titleCase } from "./shared.js";
import { renderReports } from "./lab-reports.js";

const modes = [["keyword", "Keyword"], ["boolean", "Boolean"], ["phrase", "Phrase"], ["prefix", "Prefix"],
  ["fuzzy", "Fuzzy"], ["semantic", "Semantic"], ["hybrid", "Hybrid"], ["field", "Field-specific"]];
const form = $("#compare");
const status = $("#status");
const panels = [];
const preview = createPreview();
let comparison;
let reportWork;
const query = $("#query");
const labStorageKey = "techsearch.lab";

try {
  const lastSearch = sessionStorage.getItem(SEARCH_LOCATION_KEY);
  if (lastSearch?.startsWith("/?")) $("#return-search").href = lastSearch;
} catch {
  // The Search page handles the fallback link if the saved path is unavailable here.
}

function fields(name, defaultMode, prefix) {
  const container = el("fieldset");
  const controls = el("div", null, "settings");
  const checks = el("div", null, "checks");
  const inputs = {};
  function addControl(key, text, input) {
    const wrapper = el("div", null, "control");
    const label = el("label", text);
    input.id = prefix + "-" + key;
    label.htmlFor = input.id;
    wrapper.append(label, input);
    controls.append(wrapper);
    inputs[key] = input;
  }
  function select(key, label, options, value) {
    const input = addOptions(el("select"), options);
    input.value = value;
    addControl(key, label, input);
  }
  function numeric(key, label, min, max, step, placeholder) {
    const input = el("input");
    Object.assign(input, { type: "number", min, max, step, placeholder });
    addControl(key, label, input);
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
  const reranking = el("details", null, "lab-reranking");
  reranking.append(el("summary", "Authority & diversification"), checks);
  container.append(el("legend", name), controls, reranking);
  $("#configurations").append(container);
  return inputs;
}

panels.push(fields("Method A", "keyword", "method-a"), fields("Method B", "hybrid", "method-b"));

function options(inputs) {
  const result = { query: query.value.trim(), page_size: 10 };
  for (const [key, control] of Object.entries(inputs)) {
    if (control.type === "checkbox") {
      result[key] = control.checked;
    } else if (control.value) {
      result[key] = control.type === "number" ? control.valueAsNumber : control.value;
    }
  }
  return result;
}

function panel(name, data) {
  const cell = el("div", null, "rank-panel");
  cell.append(el("h3", name));
  if (data.error) {
    cell.append(el("p", data.error));
    return cell;
  }
  cell.append(el("p", data.total + " ranked results · " + Math.round(data.timing_ms) + " ms", "rank-meta technical"));
  cell.append(el("p", "Active release " + data.release_id, "report-meta technical"));
  if (!data.total) cell.append(el("p", "No matches."));
  for (const warning of data.warnings) cell.append(el("p", warning, "callout"));
  const exportLink = el("a", "Export ranking");
  exportLink.href = "/api/v1/exports/search/" + data.search_id;
  cell.append(exportLink, showJson("Execution trace", data.trace));
  const list = el("ol", null, "results");
  list.append(...data.results.map((hit) => resultItem(hit, { lab: true, preview })));
  cell.append(list);
  return cell;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  comparison?.abort();
  comparison = new AbortController();
  const { signal } = comparison;
  preview.close({ restoreFocus: false });
  $("#rankings").setAttribute("aria-busy", "true");
  status.classList.remove("error");
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
      status.classList.add("error");
    }
  } finally {
    if (!signal.aborted) $("#rankings").setAttribute("aria-busy", "false");
  }
});


const navigation = [...document.querySelectorAll("#lab-nav a")];
const sectionPicker = $("#lab-section");
const sectionTitle = $("#section-title");
const releasePicker = $("#report-release");
const splitPicker = $("#report-split");
const viewPicker = $("#evaluation-view");
const reportStatus = $("#report-status");
const report = $("#report");
let inventoryRequest;
let inventory;
let state;

function savedLab() {
  try {
    return JSON.parse(sessionStorage.getItem(labStorageKey)) || {};
  } catch {
    return {};
  }
}

const saved = savedLab();
let topicPreferences = panels.map((_panel, index) => saved.methods?.[index]?.topic);

function setControl(control, value) {
  if (control.type === "checkbox") {
    if (typeof value === "boolean") control.checked = value;
    return;
  }
  if (typeof value !== "string") return;
  if (control.tagName === "SELECT" && ![...control.options].some((option) => option.value === value)) return;
  const previous = control.value;
  control.value = value;
  if (!control.checkValidity()) control.value = previous;
}

if (typeof saved.query === "string") query.value = saved.query.slice(0, 512);
for (const [index, panel] of panels.entries()) {
  for (const [key, control] of Object.entries(panel)) {
    if (key !== "topic") setControl(control, saved.methods?.[index]?.[key]);
  }
}

function rememberLab() {
  const methods = panels.map((panel, index) => {
    const values = {};
    for (const [key, control] of Object.entries(panel)) {
      values[key] = control.type === "checkbox" ? control.checked : control.value;
    }
    if (topicPreferences) values.topic = topicPreferences[index];
    return values;
  });
  try {
    sessionStorage.setItem(labStorageKey, JSON.stringify({ state, query: query.value, methods }));
  } catch {
    // Navigation still works when browser storage is unavailable.
  }
}

form.addEventListener("input", rememberLab);
form.addEventListener("change", rememberLab);
api("/filters").then(({ topic }) => {
  const choices = topic.map((value) => [value, titleCase(value)]);
  for (const [index, panel] of panels.entries()) {
    addOptions(panel.topic, choices);
    setControl(panel.topic, topicPreferences[index]);
  }
  topicPreferences = null;
  rememberLab();
}).catch(() => {
  // The unfiltered comparison is available without the topic list.
});

function readLocation(restore) {
  const params = new URLSearchParams(location.search);
  const fallback = restore && params.size === 0 ? (saved.state || {}) : {};
  const section = params.get("section") || fallback.section;
  const release = params.get("release") || fallback.release;
  const split = params.get("split") || fallback.split;
  const view = params.get("view") || fallback.view;
  return {
    section: navigation.some((link) => link.dataset.section === section) ? section : "overview",
    release: typeof release === "string" && /^[a-f0-9]{24}$/.test(release) ? release : "",
    split: split === "test" ? "test" : "dev",
    view: ["features", "protocol"].includes(view) ? view : "relevance",
  };
}

function labUrl(value) {
  const params = new URLSearchParams({ section: value.section });
  if (value.release) params.set("release", value.release);
  if (value.split !== "dev") params.set("split", value.split);
  if (value.view !== "relevance") params.set("view", value.view);
  return "/lab?" + params.toString();
}

function showReportControls() {
  const chooseRelease = state.section !== "overview" && releasePicker.options.length > 1;
  const chooseSplit = ["speed", "evaluation"].includes(state.section);
  const evaluation = state.section === "evaluation";
  $("#report-controls").hidden = !chooseRelease && !chooseSplit && !evaluation;
  $("#release-control").hidden = !chooseRelease;
  $("#split-control").hidden = !chooseSplit;
  $("#evaluation-controls").hidden = !evaluation;
  releasePicker.value = state.release;
  splitPicker.value = state.split;
  viewPicker.value = state.view;
}

function showReleaseChoices(data) {
  releasePicker.replaceChildren(new Option("Active release", ""));
  for (const id of Object.keys(data.releases)) {
    if (id !== data.active_release_id) releasePicker.add(new Option("Historical · " + id, id));
  }
  if (state.release === data.active_release_id) {
    state = { ...state, release: "" };
    history.replaceState(null, "", labUrl(state));
    rememberLab();
  }
  if (state.release && !Object.hasOwn(data.releases, state.release)) {
    releasePicker.add(new Option("Unavailable · " + state.release, state.release));
  }
}

function getInventory() {
  if (!inventoryRequest) {
    inventoryRequest = api("/report-inventory").catch((error) => {
      inventoryRequest = null;
      throw error;
    });
  }
  return inventoryRequest;
}

async function loadReports() {
  reportWork?.abort();
  reportWork = new AbortController();
  const { signal } = reportWork;
  report.replaceChildren();
  reportStatus.textContent = "Loading reports…";
  try {
    inventory = await getInventory();
    if (signal.aborted) return;
    showReleaseChoices(inventory);
    showReportControls();
    const contents = await renderReports(state, inventory, signal);
    if (signal.aborted) return;
    report.replaceChildren(contents);
    reportStatus.textContent = "";
  } catch (error) {
    if (signal.aborted) return;
    reportStatus.textContent = "Could not load reports. " + error.message;
  }
}

function showLab(next, historyAction, focusHeading = false) {
  const changedSection = !state || state.section !== next.section;
  state = next;
  const path = labUrl(state);
  if (historyAction === "push" && path !== location.pathname + location.search) history.pushState(null, "", path);
  if (historyAction === "replace") history.replaceState(null, "", path);
  if (changedSection) {
    preview.close({ restoreFocus: false });
    window.scrollTo(0, 0);
  }
  for (const link of navigation) {
    const isCurrent = link.dataset.section === state.section;
    if (isCurrent) {
      link.setAttribute("aria-current", "page");
      sectionTitle.textContent = link.textContent;
    } else {
      link.removeAttribute("aria-current");
    }
    link.href = labUrl({ ...state, section: link.dataset.section });
  }
  sectionPicker.value = state.section;
  $("#comparison-panel").hidden = state.section !== "compare";
  showReportControls();
  rememberLab();
  if (focusHeading) sectionTitle.focus({ preventScroll: true });
  loadReports();
}

for (const link of navigation) {
  link.addEventListener("click", (event) => {
    if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    showLab({ ...state, section: link.dataset.section }, "push", true);
  });
}
sectionPicker.addEventListener("change", () => showLab({ ...state, section: sectionPicker.value }, "push"));
releasePicker.addEventListener("change", () => showLab({ ...state, release: releasePicker.value }, "push"));
splitPicker.addEventListener("change", () => showLab({ ...state, split: splitPicker.value }, "push"));
viewPicker.addEventListener("change", () => showLab({ ...state, view: viewPicker.value }, "push"));
window.addEventListener("popstate", () => showLab(readLocation(false)));
showLab(readLocation(true), "replace");
