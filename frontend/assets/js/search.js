import { $, addOptions, api, el, resultItem, titleCase } from "./shared.js";

const input = $("#query");
const form = $("#search");
const source = $("#source");
const topic = $("#topic");
const status = $("#status");
const section = $("#results-section");
let current;
let request;
let completion;
let timer;
let lastOptions;

api("/filters").then(({ topic: values }) => addOptions(topic, values.map((value) => [value, titleCase(value)])))
  .catch(() => {});

function render(data, signal, feedback = false) {
  current = data;
  $("#warnings").replaceChildren(...data.warnings.map((warning) => el("p", warning)));
  const suggestions = $("#suggestions");
  suggestions.replaceChildren();
  if (data.suggestions.length) {
    suggestions.append(el("span", "Try a related spelling"));
    for (const suggestion of data.suggestions) {
      const button = el("button", suggestion, "secondary");
      button.addEventListener("click", () => { input.value = suggestion; form.requestSubmit(); });
      suggestions.append(button);
    }
  }
  section.hidden = data.total === 0;
  status.textContent = data.total ? data.total + " ranked results · " + Math.round(data.timing_ms) + " ms" :
    "No matches in this snapshot. Try different terms or filters.";
  if (!data.total) return;
  const list = $("#results");
  list.start = (data.page - 1) * data.page_size + 1;
  list.replaceChildren(...data.results.map((hit) => resultItem(hit, {
    judge: async (document, value) => {
      try {
        await api("/feedback", { body: { search_id: data.search_id, document, value } });
        if (signal.aborted) return false;
        status.textContent = "Feedback saved for this search.";
        $("#refine").hidden = false;
        return true;
      } catch (error) {
        if (!signal.aborted) status.textContent = error.message;
        return false;
      }
    },
  })));
  $("#export").href = "/api/v1/exports/search/" + data.search_id;
  if (data.page === 1) $("#refine").hidden = !feedback;
  const pages = $("#pages");
  const last = Math.ceil(data.total / data.page_size);
  pages.replaceChildren();
  if (last <= 1) return;
  for (const [label, page] of [["Previous", data.page - 1], ["Page " + data.page + " of " + last, null], ["Next", data.page + 1]]) {
    const element = page === null ? el("span", label) : el("button", label, "secondary");
    if (page !== null) {
      element.disabled = page < 1 || page > last;
      element.addEventListener("click", () => paginate(page));
    }
    pages.append(element);
  }
}

async function execute(path, body, feedback = false) {
  request?.abort();
  request = new AbortController();
  const { signal } = request;
  status.textContent = "Searching…";
  section.setAttribute("aria-busy", "true");
  try {
    const result = await api(path, { body, signal });
    if (!signal.aborted) render(result, signal, feedback);
  } catch (error) {
    if (!signal.aborted) {
      section.hidden = true;
      status.textContent = error.message;
      $("#warnings").replaceChildren();
      $("#suggestions").replaceChildren();
    }
  } finally {
    if (!signal.aborted) section.setAttribute("aria-busy", "false");
  }
}

function paginate(page) {
  if (!current) return;
  execute("/search/" + current.search_id + "?page=" + page + "&size=" + current.page_size);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  completion?.abort();
  clearTimeout(timer);
  $("#completions").replaceChildren();
  lastOptions = { query: input.value.trim(), source: source.value || null, topic: topic.value || null };
  execute("/search", lastOptions);
});
$("#refine").addEventListener("click", () => {
  if (lastOptions) execute("/search", { ...lastOptions, apply_feedback: true }, true);
});
input.addEventListener("input", () => {
  clearTimeout(timer);
  completion?.abort();
  const value = input.value.trim();
  $("#completions").replaceChildren();
  if (!/^[\w.-]{2,40}$/.test(value)) return;
  timer = setTimeout(async () => {
    completion = new AbortController();
    const { signal } = completion;
    try {
      const data = await api("/suggestions?q=" + encodeURIComponent(value), { signal });
      if (!signal.aborted) $("#completions").replaceChildren(...data.suggestions.map((match) => new Option(match, match)));
    } catch {
      // Search remains available when completion is unavailable.
    }
  }, 220);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey &&
      !(event.target instanceof Element && event.target.closest("input, textarea, select, dialog, [contenteditable]")) && !$("#viewer").open) {
    event.preventDefault();
    input.focus();
  }
});
