import { $, SEARCH_LOCATION_KEY, addOptions, api, createPreview, el, resultItem, showJson, titleCase } from "./shared.js";
import { METHODS, models, courseExperiments, milliseconds } from "./lab-reports.js";

const requestMethods = {
  tfidf: { mode: "keyword", ranker: "tfidf" },
  bm25: { mode: "keyword", ranker: "bm25" },
  likelihood: { mode: "keyword", ranker: "likelihood" },
  dense: { mode: "semantic" },
  hybrid: { mode: "hybrid", ranker: "bm25" },
};
const form = $("#compare");
const query = $("#query");
const status = $("#status");
const rankings = $("#rankings");
const preview = createPreview();
const navigation = [...document.querySelectorAll("#lab-nav a")];
const storageKey = "techsearch.lab.v2";
let comparison, reportWork, section, dataset, displayed;

function restore() {
  try {
    const lastSearch = sessionStorage.getItem(SEARCH_LOCATION_KEY);
    if (lastSearch?.startsWith("/?")) $("#return-search").href = lastSearch;
    return JSON.parse(sessionStorage.getItem(storageKey)) || {};
  } catch {
    return {};
  }
}

const saved = restore();
if (typeof saved.query === "string") query.value = saved.query.slice(0, 512);

function methodControls(side, initial, previous = {}) {
  const panel = el("fieldset");
  const prefix = "method-" + side.toLowerCase();
  const advanced = el("details", null, "lab-advanced");
  const settings = el("div", null, "settings");
  const inputs = {};
  function control(key, label, input, target = settings) {
    const wrapper = el("div", null, "control");
    const caption = el("label", label);
    input.id = prefix + "-" + key;
    caption.htmlFor = input.id;
    wrapper.append(caption, input);
    target.append(wrapper);
    inputs[key] = input;
    return input;
  }
  function select(key, label, options, initialValue = "", target = settings) {
    const input = addOptions(el("select"), options);
    input.value = options.some(([value]) => value === previous[key]) ? previous[key] : initialValue;
    return control(key, label, input, target);
  }
  function number(key, label, min, max, step) {
    const input = el("input");
    Object.assign(input, { type: "number", min, max, step, value: previous[key] || "" });
    if (!input.checkValidity()) input.value = "";
    return control(key, label, input);
  }
  function check(key, label) {
    const input = el("input");
    input.type = "checkbox";
    input.checked = previous[key] === true;
    const caption = el("label", " " + label);
    caption.prepend(input);
    checks.append(caption);
    inputs[key] = input;
  }
  panel.append(el("legend", "Method " + side));
  const method = select("method", "Retrieval method " + side, Object.entries(METHODS), initial, panel);
  const source = select("source", "Source", [["", "All sources"], ["mdn", "MDN"], ["stackoverflow", "Stack Overflow"]]);
  select("topic", "Topic", [["", "All topics"]]);
  select("strategy", "Execution", [["taat", "TAAT"], ["daat", "DAAT"]], "taat");
  number("k1", "BM25 k₁", .01, 5, .01);
  number("b", "BM25 b", 0, 1, .01);
  number("cutoff", "Semantic similarity cutoff", .01, .99, .01);
  number("rrf_k", "Fusion rank constant", 1, 500, 1);
  const checks = el("div", null, "checks");
  check("authority", "MDN authority");
  check("diversify", "Diversify results");
  advanced.append(el("summary", "Advanced options"), settings, checks);
  panel.append(advanced);
  $("#configurations").append(panel);

  function update() {
    const value = method.value;
    const usesBM25 = ["bm25", "hybrid"].includes(value);
    const usesDense = ["dense", "hybrid"].includes(value);
    const applicability = {
      strategy: ["tfidf", "bm25", "hybrid"].includes(value),
      k1: usesBM25, b: usesBM25, cutoff: usesDense, rrf_k: value === "hybrid",
      authority: source.value !== "stackoverflow",
    };
    for (const [key, applies] of Object.entries(applicability)) {
      inputs[key].disabled = !applies;
      inputs[key].parentElement.hidden = !applies;
    }
  }
  method.addEventListener("change", update);
  source.addEventListener("change", update);
  update();
  return inputs;
}

const panels = [methodControls("A", "bm25", saved.methods?.[0]), methodControls("B", "hybrid", saved.methods?.[1])];

function remember() {
  try {
    const methods = panels.map(inputs => Object.fromEntries(Object.entries(inputs).map(([key, control]) => [
      key, control.type === "checkbox" ? control.checked : control.value,
    ])));
    sessionStorage.setItem(storageKey, JSON.stringify({ query: query.value, methods }));
  } catch {
    // This page operates normally when session storage is disabled.
  }
}

form.addEventListener("input", remember);
api("/filters").then(({ topic }) => {
  const options = topic.map(value => [value, titleCase(value)]);
  panels.forEach((inputs, i) => {
    addOptions(inputs.topic, options);
    const previous = saved.methods?.[i]?.topic;
    if (options.some(([value]) => value === previous)) inputs.topic.value = previous;
  });
}).catch(() => {
  // The other controls can still be used when the topic list is unavailable.
});

function options(inputs) {
  const result = { query: query.value.trim(), page_size: 5, ...requestMethods[inputs.method.value] };
  for (const [key, control] of Object.entries(inputs)) {
    if (key === "method" || control.disabled) continue;
    if (control.type === "checkbox") {
      if (control.checked) result[key] = true;
    } else if (control.value) {
      result[key] = control.type === "number" ? control.valueAsNumber : control.value;
    }
  }
  return result;
}

function ranking(name, data) {
  const panel = el("div", null, "rank-panel");
  panel.append(el("h3", name));
  if (data.error) {
    panel.append(el("p", data.error));
    return panel;
  }
  panel.append(el("p", milliseconds(data.timing_ms) + " search time", "rank-meta"));
  if (!data.results.length) panel.append(el("p", "No matches."));
  for (const warning of data.warnings) panel.append(el("p", warning, "callout"));
  const list = el("ol", null, "results");
  list.append(...data.results.map(hit => resultItem(hit, { lab: true, preview })));
  const exportLink = el("a", "Export ranking");
  exportLink.href = "/api/v1/exports/search/" + data.search_id;
  panel.append(list, exportLink, showJson("Execution details", data.trace));
  return panel;
}

function clearRanking(message = "") {
  comparison?.abort();
  preview.close({ restoreFocus: false });
  rankings.replaceChildren();
  rankings.removeAttribute("aria-busy");
  status.classList.remove("error");
  status.textContent = message;
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!query.value.trim()) {
    status.textContent = "Enter a query to compare.";
    return;
  }
  clearRanking("Comparing methods…");
  comparison = new AbortController();
  const { signal } = comparison;
  const names = panels.map(inputs => METHODS[inputs.method.value]);
  rankings.setAttribute("aria-busy", "true");
  try {
    const { left, right } = await api("/compare", { body: { left: options(panels[0]), right: options(panels[1]) }, signal });
    if (signal.aborted) return;
    const releases = new Set([left.release_id, right.release_id].filter(Boolean));
    if (releases.size > 1 || (dataset && [...releases].some(id => id !== dataset.release_id))) {
      clearRanking("The search data changed. Run the comparison again.");
      refresh();
      return;
    }
    rankings.replaceChildren(ranking(names[0], left), ranking(names[1], right));
    status.textContent = left.error && right.error ? "The searches could not run." : "Comparison ready.";
  } catch (error) {
    if (!signal.aborted) {
      status.textContent = error.message;
      status.classList.add("error");
    }
  } finally {
    if (!signal.aborted) rankings.removeAttribute("aria-busy");
  }
});

function readSection() {
  const value = new URLSearchParams(location.search).get("section");
  if (["query", "compare"].includes(value)) return "query";
  if (["experiments", "speed", "compression", "links", "topics", "evaluation"].includes(value)) return "experiments";
  return "models";
}

async function refresh() {
  reportWork?.abort();
  reportWork = new AbortController();
  const { signal } = reportWork;
  const target = section;
  const statusNode = target === "models" ? $("#model-status") : $("#experiment-status");
  try {
    const next = await api("/lab", { signal });
    if (signal.aborted) return;
    if (dataset && (dataset.release_id !== next.release_id || dataset.configuration !== next.configuration)) {
      clearRanking("The search data changed. Run the comparison again.");
      $("#models-report").replaceChildren();
      $("#experiments-report").replaceChildren();
      displayed = null;
    }
    dataset = next;
    if (target === "query") return;
    const view = target === "models" ? models(next) : await courseExperiments(next, signal);
    if (signal.aborted) return;
    if (displayed?.section !== target || displayed.signature !== view.signature) {
      $("#" + target + "-report").replaceChildren(view.content);
      displayed = { section: target, signature: view.signature };
    }
    statusNode.textContent = "";
  } catch (error) {
    if (signal.aborted) return;
    if (target === "query") {
      clearRanking("Could not verify the current search data.");
    } else {
      $("#" + target + "-report").replaceChildren();
      statusNode.textContent = "Could not load measurements for the current search data. " + error.message;
      displayed = null;
    }
  }
}

function show(target, focus = false) {
  if (section && section !== target) {
    if (rankings.hasAttribute("aria-busy")) clearRanking();
    preview.close({ restoreFocus: false });
  }
  section = target;
  for (const link of navigation) {
    const current = link.dataset.section === target;
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
    $("#" + link.dataset.section + "-panel").hidden = !current;
  }
  if (focus) $("#" + target + "-title").focus();
  refresh();
}

for (const link of navigation) {
  link.addEventListener("click", event => {
    if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (link.dataset.section !== section) history.pushState(null, "", link.href);
    show(link.dataset.section, true);
  });
}
window.addEventListener("popstate", () => show(readSection()));
window.addEventListener("pageshow", event => { if (event.persisted) refresh(); });
window.addEventListener("focus", () => { if (!document.hidden) refresh(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
setInterval(() => { if (!document.hidden) refresh(); }, 30000);
show(readSection());
