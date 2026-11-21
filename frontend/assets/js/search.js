import { $, SEARCH_LOCATION_KEY, addOptions, api, createPreview, documentFor, el, resultItem, showAccepted, titleCase } from "./shared.js";

const home = $("#home");
const resultsView = $("#results-view");
const panel = $("#results-panel");
const form = $("#search-form");
const query = $("#query");
const clear = $("#clear-query");
const completions = $("#completions");
const sourceTabs = $("#source-tabs");
const tabs = [...sourceTabs.querySelectorAll("button")];
const topic = $("#topic");
const status = $("#status");
const title = $("#results-title");
const warnings = $("#warnings");
const suggestions = $("#suggestions");
const results = $("#results");
const pages = $("#pages");
const exportLink = $("#export");
const refine = $("#refine");
const preview = createPreview({ sidebar: true });

const PAGE_SIZE = 10;
const votes = new Map();
let state;
let snapshot;
let work;
let completion;
let timer;

function fromLocation() {
  const params = new URLSearchParams(location.search);
  const value = params.get("source");
  const number = params.get("page");
  return {
    query: (params.get("q") || "").trim(),
    source: tabs.some((tab) => tab.dataset.source === value) ? value : "",
    topic: params.get("topic") || "",
    page: /^\d+$/.test(number || "") ? Math.max(1, Math.min(1000, Number(number))) : 1,
  };
}

const hasSearch = (view) => Boolean(view.query || view.source || view.topic);

function updateHistory(mode, view, searchId) {
  const params = new URLSearchParams();
  if (view.query) params.set("q", view.query);
  if (view.source) params.set("source", view.source);
  if (view.topic) params.set("topic", view.topic);
  if (view.page > 1) params.set("page", view.page);
  const path = params.size ? "/?" + params.toString() : "/";
  const entry = searchId ? { searchId } : null;
  if (mode === "push" && path !== location.pathname + location.search) history.pushState(entry, "", path);
  else history.replaceState(entry, "", path);
  try { sessionStorage.setItem(SEARCH_LOCATION_KEY, path); } catch { /* Storage can be disabled. */ }
}

function setTopic(value) {
  topic.querySelectorAll("[data-pending]").forEach((option) => option.remove());
  if (value && !Array.from(topic.options).some((option) => option.value === value)) {
    const option = new Option(titleCase(value), value);
    option.dataset.pending = "";
    topic.append(option);
  }
  topic.value = value;
}

function showView(view) {
  const searching = hasSearch(view);
  const slot = searching ? $("#header-search") : $("#home-search");
  const hadFocus = form.contains(document.activeElement);
  if (form.parentElement !== slot) slot.append(form);
  $("#header-search").hidden = !searching;
  home.hidden = searching;
  resultsView.hidden = !searching;
  query.value = view.query;
  clear.hidden = !query.value;
  if (hadFocus && document.activeElement !== query) query.focus({ preventScroll: true });
  for (const tab of tabs) {
    const selected = tab.dataset.source === view.source;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected) panel.setAttribute("aria-labelledby", tab.id);
  }
  setTopic(view.topic);
  title.replaceChildren(document.createTextNode(view.query ? "Results for " : "Results"));
  if (view.query) title.append(el("strong", view.query));
}

function setStatus(message, { error = false } = {}) {
  status.textContent = message;
  status.classList.toggle("error", error);
}

function clearCompletions() {
  clearTimeout(timer);
  completion?.abort();
  completions.replaceChildren();
}

async function getResults(view, searchId, signal, applyFeedback) {
  const pageFrom = (id, page) => api("/search/" + encodeURIComponent(id) + "?page=" + page + "&size=" + PAGE_SIZE, { signal });
  if (searchId && !applyFeedback) {
    try {
      const stored = await pageFrom(searchId, view.page);
      const last = Math.max(1, Math.ceil(stored.total / stored.page_size));
      return stored.page > last ? await pageFrom(searchId, last) : stored;
    } catch (error) {
      if (error.status !== 404) throw error;
    }
  }
  const first = await api("/search", {
    body: { query: view.query, source: view.source || null, topic: view.topic || null, page_size: PAGE_SIZE, apply_feedback: applyFeedback },
    signal,
  });
  const last = Math.max(1, Math.ceil(first.total / first.page_size));
  const page = Math.min(view.page, last);
  return page === 1 ? first : pageFrom(first.search_id, page);
}

function pagination(data) {
  const last = Math.ceil(data.total / data.page_size);
  pages.replaceChildren();
  pages.hidden = last < 2;
  if (pages.hidden) return;

  const control = (number, label, name) => {
    const button = el("button", label);
    button.type = "button";
    if (name) button.setAttribute("aria-label", name);
    button.disabled = number < 1 || number > last;
    if (!name && number === data.page) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => {
      if (number !== state.page) navigate({ ...state, page: number }, { record: "push", searchId: data.search_id, focus: true });
    });
    return button;
  };
  pages.append(control(data.page - 1, "← Previous", "Previous"));
  const visible = Array.from({ length: last }, (_, i) => i + 1)
    .filter((n) => last <= 5 || n === 1 || n === last || Math.abs(n - data.page) <= 1);
  let previous = 0;
  for (const number of visible) {
    if (previous && number - previous > 1) {
      const gap = el("span", "…", "pagination-gap");
      gap.setAttribute("aria-hidden", "true");
      pages.append(gap);
    }
    pages.append(control(number, String(number)));
    previous = number;
  }
  pages.append(control(data.page + 1, "Next →", "Next"));
}

function enrichVisible(hits, signal) {
  if (!hits.size) return;
  const observe = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting || signal.aborted) continue;
      const row = entry.target;
      observe.unobserve(row);
      documentFor(hits.get(row), signal).then((data) => {
        if (!signal.aborted) showAccepted(row, data);
      }).catch(() => { /* Offer the preview even when supplemental metadata fails. */ });
    }
  }, { rootMargin: "100px 0px" });
  signal.addEventListener("abort", () => observe.disconnect(), { once: true });
  for (const row of hits.keys()) observe.observe(row);
}

function render(data, signal) {
  snapshot = data.search_id;
  state = { ...state, page: data.page };
  updateHistory("replace", state, snapshot);
  warnings.replaceChildren(...(data.warnings || []).map((warning) => el("p", warning)));
  if (data.suggestions?.length) {
    suggestions.append(el("span", "Try a related spelling"));
    for (const suggestion of data.suggestions) {
      const button = el("button", suggestion, "button secondary");
      button.type = "button";
      button.addEventListener("click", () => submit(suggestion));
      suggestions.append(button);
    }
  }
  if (!data.total) {
    setStatus("No matches in this snapshot. Try different terms or filters.");
    return;
  }

  const savedVotes = votes.get(snapshot) || new Map();
  const judge = async (document, value) => {
    try {
      await api("/feedback", { body: { search_id: data.search_id, document, value } });
      savedVotes.set(document, value);
      votes.set(data.search_id, savedVotes);
      if (signal.aborted) return false;
      setStatus("Feedback saved for this search.");
      refine.hidden = false;
      return true;
    } catch (error) {
      if (!signal.aborted) setStatus(error.message, { error: true });
      return false;
    }
  };

  const supplemental = new Map();
  for (const hit of data.results) {
    const row = resultItem(hit, { judge, vote: savedVotes.get(hit.id), preview });
    results.append(row);
    if (hit.source === "stackoverflow") supplemental.set(row, hit);
  }
  enrichVisible(supplemental, signal);
  results.start = (data.page - 1) * data.page_size + 1;
  exportLink.href = "/api/v1/exports/search/" + data.search_id;
  exportLink.hidden = false;
  refine.hidden = !savedVotes.size;
  setStatus(data.total + (data.total === 1 ? " result" : " results") +
    (data.total > data.page_size ? " · Page " + data.page + " of " + Math.ceil(data.total / data.page_size) : ""));
  pagination(data);
}

async function navigate(view, { record, searchId, applyFeedback = false, focus = false } = {}) {
  work?.abort();
  preview.close({ restoreFocus: false });
  clearCompletions();
  work = new AbortController();
  const { signal } = work;
  snapshot = undefined;
  state = view;
  if (record) updateHistory(record, view, searchId);
  showView(view);
  results.replaceChildren();
  pages.replaceChildren();
  pages.hidden = true;
  warnings.replaceChildren();
  suggestions.replaceChildren();
  exportLink.hidden = true;
  refine.hidden = true;
  panel.setAttribute("aria-busy", String(hasSearch(view)));
  if (record === "push") window.scrollTo(0, 0);
  if (!hasSearch(view)) {
    setStatus("");
    return;
  }
  if (focus) title.focus({ preventScroll: true });
  setStatus("Searching…");
  try {
    const result = await getResults(view, searchId, signal, applyFeedback);
    if (!signal.aborted) render(result, signal);
  } catch (error) {
    if (!signal.aborted) setStatus(error.message, { error: true });
  } finally {
    if (!signal.aborted) panel.setAttribute("aria-busy", "false");
  }
}

function submit(value) {
  navigate({ ...state, query: value.trim(), page: 1 }, { record: "push" });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submit(query.value);
});
clear.addEventListener("click", () => {
  query.value = "";
  clear.hidden = true;
  clearCompletions();
  query.focus();
});
for (const example of document.querySelectorAll(".example")) {
  example.addEventListener("click", () => {
    submit(example.textContent);
    query.focus({ preventScroll: true });
  });
}
for (const tab of tabs) {
  tab.addEventListener("click", () => {
    if (state.source !== tab.dataset.source) {
      navigate({ ...state, source: tab.dataset.source, page: 1 }, { record: "push" });
    }
  });
}
sourceTabs.addEventListener("keydown", (event) => {
  const index = tabs.indexOf(event.target);
  if (index < 0) return;
  const target = { ArrowLeft: (index - 1 + tabs.length) % tabs.length, ArrowRight: (index + 1) % tabs.length, Home: 0, End: tabs.length - 1 }[event.key];
  if (target === undefined) return;
  event.preventDefault();
  tabs[target].focus();
  tabs[target].click();
});
topic.addEventListener("change", () => {
  navigate({ ...state, topic: topic.value, page: 1 }, { record: "push" });
});
refine.addEventListener("click", () => {
  if (snapshot) navigate({ ...state, page: 1 }, { record: "replace", applyFeedback: true, focus: true });
});

query.addEventListener("input", () => {
  clear.hidden = !query.value;
  clearCompletions();
  const value = query.value.trim();
  if (!/^[\w.-]{2,40}$/.test(value)) return;
  timer = setTimeout(async () => {
    completion = new AbortController();
    const { signal } = completion;
    try {
      const data = await api("/suggestions?q=" + encodeURIComponent(value), { signal });
      if (!signal.aborted) completions.replaceChildren(...data.suggestions.map((match) => new Option(match, match)));
    } catch {
      // Search stays usable when autocomplete is unavailable.
    }
  }, 220);
});

document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.altKey || $("#preview").matches(":modal")) return;
  const editing = event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable]");
  const shortcut = event.key.toLowerCase() === "k" && (event.ctrlKey || event.metaKey);
  const slash = event.key === "/" && !event.ctrlKey && !event.metaKey && !editing;
  if (shortcut || slash) {
    event.preventDefault();
    query.focus();
  }
});

window.addEventListener("popstate", (event) => navigate(fromLocation(), { searchId: event.state?.searchId }));
navigate(fromLocation(), { searchId: history.state?.searchId });
api("/filters").then(({ topic: topics }) => {
  topic.querySelectorAll("option:not(:first-child)").forEach((option) => option.remove());
  addOptions(topic, topics.map((value) => [value, titleCase(value)]));
  setTopic(state.topic);
}).catch(() => {
  // Search works without the optional topic list.
});
