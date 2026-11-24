export const $ = (selector, root = document) => root.querySelector(selector);
export const SEARCH_LOCATION_KEY = "techsearch.last-search";

export function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

const sourceName = (source) => source === "mdn" ? "MDN Web Docs" : "Stack Overflow";
const abbreviations = new Set(["api", "aria", "css", "dom", "html", "http", "https", "svg", "url", "webgl"]);

export function titleCase(value) {
  return String(value ?? "").split(/[-_\s]+/).filter(Boolean).map((word) => {
    const lower = word.toLowerCase();
    if (lower === "javascript") return "JavaScript";
    return abbreviations.has(lower) ? lower.toUpperCase() : word[0].toUpperCase() + word.slice(1);
  }).join(" ");
}

export function link(label, url) {
  const node = el("a", label);
  try {
    const parsed = new URL(url);
    if (["http:", "https:"].includes(parsed.protocol) && !parsed.username && !parsed.password) {
      node.href = parsed.href;
      node.target = "_blank";
      node.rel = "noopener noreferrer";
    }
  } catch {
    // A source label can still be displayed when its URL is missing.
  }
  return node;
}

export async function api(path, { body, signal } = {}) {
  const request = { method: "GET", signal };
  if (body) {
    request.method = "POST";
    request.headers = { "Content-Type": "application/json" };
    request.body = JSON.stringify(body);
  }
  const response = await fetch("/api/v1" + path, request);
  if (response.status === 204) return undefined;
  const value = await response.json().catch(() => null);
  if (!response.ok || value === null) {
    const detail = value?.detail;
    let message = "The search service returned an unexpected response.";
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      message = detail.map((item) => item.msg).join(". ");
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return value;
}

export function addOptions(select, values) {
  values.forEach(([value, label]) => select.append(new Option(label, value)));
  return select;
}

export function showJson(label, value) {
  const result = el("details", null, "diagnostic");
  const content = el("pre", JSON.stringify(value, null, 2));
  content.tabIndex = 0;
  result.append(el("summary", label), content);
  return result;
}

function sourceLabel(source) {
  const label = el("span", null, "source-label");
  const icon = el("span", source === "mdn" ? "M" : "", "source-icon" + (source === "mdn" ? "" : " so"));
  icon.setAttribute("aria-hidden", "true");
  label.append(icon, el("span", sourceName(source)));
  return label;
}

function breadcrumb(hit) {
  if (hit.source === "mdn") {
    try {
      const paths = new URL(hit.url).pathname.split("/").filter(Boolean);
      const docs = paths.indexOf("docs");
      if (docs >= 0 && paths.length > docs + 2) {
        return paths.slice(docs + 1, -1).slice(0, 4)
          .map((part) => titleCase(decodeURIComponent(part))).join(" / ");
      }
    } catch {
      // The topic is available independently of the source URL.
    }
    return titleCase(hit.topic);
  }
  return ["Questions", titleCase(hit.topic)].filter(Boolean).join(" / ");
}

function attribution(item) {
  const body = el("div", null, "attribution-content");
  if (item?.author) {
    body.append(item.author_url ? link(item.author, item.author_url) : el("span", item.author));
  }
  const license = item?.content_license || item?.license;
  if (license) body.append(el("span", license));
  if (!body.childElementCount) body.append(el("span", "Author and license details are unavailable."));
  return body;
}

function disclosure(label, content, className) {
  const wrapper = el("details", null, className);
  wrapper.name = "result-tools";
  const summary = el("summary", label);
  content.classList.add("disclosure");
  wrapper.append(summary, content);
  wrapper.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && wrapper.open) {
      event.stopPropagation();
      wrapper.open = false;
      summary.focus();
    }
  });
  return wrapper;
}

document.addEventListener("pointerdown", (event) => {
  for (const details of document.querySelectorAll(".result-actions details[open]")) {
    if (!details.contains(event.target)) details.open = false;
  }
});

const documents = new Map();

export async function documentFor(hit, signal) {
  const key = (hit.release_id || "") + "/" + hit.id;
  if (documents.has(key)) return documents.get(key);
  const revision = hit.release_id ? "?release=" + encodeURIComponent(hit.release_id) : "";
  const data = await api("/documents/" + encodeURIComponent(hit.id) + revision, { signal });
  if (documents.size >= 24) documents.delete(documents.keys().next().value);
  documents.set(key, data);
  return data;
}

export function showAccepted(row, data) {
  const label = $(".accepted", row);
  if (label && data.answers?.some((answer) => answer.is_accepted === true)) label.hidden = false;
}

function feedbackControl(hit, judge, vote) {
  const controls = el("div");
  const menu = disclosure("⋯", controls, "feedback");
  $("summary", menu).setAttribute("aria-label", "Feedback for " + hit.title);
  for (const [value, label] of [[1, "Relevant"], [-1, "Not relevant"]]) {
    const button = el("button", label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(value === vote));
    button.addEventListener("click", async () => {
      const buttons = controls.querySelectorAll("button");
      for (const peer of buttons) peer.disabled = true;
      const saved = await judge(hit.id, value);
      for (const peer of buttons) {
        peer.disabled = false;
        if (saved) peer.setAttribute("aria-pressed", String(peer === button));
      }
    });
    controls.append(button);
  }
  return menu;
}

function resultSnippet(hit) {
  const text = el("p", null, "snippet");
  let content = text;
  if (hit.evidence?.field === "code") {
    text.classList.add("is-code");
    content = el("code");
    text.append(content);
  }
  for (const piece of hit.snippet || []) {
    const node = piece.match ? el("mark", piece.text) : document.createTextNode(piece.text);
    content.append(node);
  }
  return text;
}

export function resultItem(hit, { lab = false, judge, vote, preview } = {}) {
  const row = el("li", null, "result");
  const header = el("div", null, "result-header");
  const origin = el("div", null, "result-origin");
  origin.append(sourceLabel(hit.source));
  const path = breadcrumb(hit);
  if (path) {
    const crumb = el("span", path, "breadcrumb");
    crumb.title = path;
    origin.append(crumb);
  }
  const actions = el("div", null, "result-actions");
  actions.append(disclosure("Attribution", attribution(hit), "attribution"));
  if (judge) actions.append(feedbackControl(hit, judge, vote));
  header.append(origin, actions);

  const heading = el(lab ? "h3" : "h2", null, "result-title");
  heading.append(link(hit.title, hit.url));
  const text = resultSnippet(hit);
  const metadata = el("div", null, "result-meta");
  if (lab) metadata.append(el("span", "#" + hit.rank + " · " + hit.score.toFixed(5), "technical"));
  if (hit.source === "stackoverflow") {
    const accepted = el("span", "✓ Accepted answer", "accepted");
    accepted.hidden = true;
    metadata.append(accepted);
  }
  for (const tag of hit.tags?.slice(0, 3) || []) metadata.append(el("code", tag, "tag"));
  if (preview) {
    const button = el("button", "Preview", "preview-button");
    const arrow = el("span", " ↗");
    arrow.setAttribute("aria-hidden", "true");
    button.append(arrow);
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", "preview");
    button.addEventListener("click", () => preview.open(hit, button, row));
    metadata.append(button);
  }
  row.append(header, heading);
  if (text.textContent) row.append(text);
  row.append(metadata);
  if (lab) row.append(showJson("Score explanation", { contributions: hit.explanation, evidence: hit.evidence }));
  return row;
}

function sourceSections(segments) {
  const groups = [];
  for (const segment of segments) {
    const path = (segment.heading_path || []).filter(Boolean);
    const answerId = segment.answer_id ?? null;
    const pathKey = JSON.stringify([answerId, path]);
    let group = groups.at(-1);
    if (!group || group.key !== pathKey || segment.field === "heading") {
      const label = segment.field === "heading" ? segment.text : path.at(-1);
      group = { key: pathKey, label, answerId, segments: [] };
      groups.push(group);
    }
    group.segments.push(segment);
  }
  return groups;
}

function sourceBlock(segment) {
  if (segment.field !== "code") return el("p", segment.text);
  const pre = el("pre");
  pre.tabIndex = 0;
  pre.append(el("code", segment.text));
  return pre;
}

export function createPreview({ sidebar = false } = {}) {
  const dialog = $("#preview");
  const title = $("#preview-title");
  const source = $("#preview-source");
  const status = $("#preview-status");
  const body = $("#preview-body");
  const footer = $("#preview-footer");
  const dismiss = $(".preview-close", dialog);
  const wide = matchMedia("(min-width: 58rem)");
  let active;

  function show() {
    if (sidebar && wide.matches) dialog.show();
    else dialog.showModal();
    dismiss.focus({ preventScroll: true });
  }

  function close({ restoreFocus = true } = {}) {
    if (!active) return;
    const { controller, button, row } = active;
    active = undefined;
    controller.abort();
    dialog.close();
    row.classList.remove("is-previewed");
    button.setAttribute("aria-expanded", "false");
    if (restoreFocus && button.isConnected) button.focus({ preventScroll: true });
  }

  dismiss.addEventListener("click", () => close());
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog || !dialog.matches(":modal")) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close();
  });
  document.addEventListener("keydown", (event) => {
    if (active && !dialog.matches(":modal") && event.key === "Escape" && !event.defaultPrevented) close();
  });
  if (sidebar) wide.addEventListener("change", () => {
    if (!active) return;
    const scroll = dialog.scrollTop;
    dialog.close();
    show();
    dialog.scrollTop = scroll;
  });

  function setFooter(url, item) {
    const original = link("Open original ↗", url);
    original.className = "button primary";
    original.setAttribute("aria-label", "Open original source");
    footer.replaceChildren();
    if (original.hasAttribute("href")) footer.append(original);
    footer.append(attribution(item));
  }

  function render(hit, data) {
    title.textContent = data.title || hit.title;
    source.replaceChildren(sourceLabel(data.source || hit.source));
    status.textContent = "";
    const groups = sourceSections(data.segments || []);
    const matched = groups.find((group) => group.segments.some((segment) => segment.ordinal === hit.evidence?.ordinal));
    const detail = el("p", "Source excerpt", "preview-type");
    const excerpt = el("section", null, "preview-excerpt");
    body.replaceChildren(detail, excerpt);

    let headings = [];
    function select(group, useMatchedEvidence) {
      excerpt.replaceChildren();
      const ordinal = useMatchedEvidence ? hit.evidence?.ordinal : undefined;
      const index = Math.max(0, group?.segments.findIndex((segment) => segment.ordinal === ordinal) ?? 0);
      const segment = group?.segments[index];
      const answer = group?.answerId == null ? null : data.answers?.find((item) => item.answer_id === group.answerId);
      detail.textContent = "Source excerpt" + (segment?.field === "code" ? " · Code" : "");
      if (answer?.is_accepted === true) detail.append(el("span", " · Accepted answer", "accepted"));
      let target = data.url;
      if (useMatchedEvidence) {
        target = hit.evidence?.url;
      } else if (answer?.url) {
        target = answer.url;
      } else if (segment?.source_anchor) {
        target = data.url.split("#")[0] + "#" + encodeURIComponent(segment.source_anchor);
      }
      setFooter(target || data.url || hit.url, answer || data.metadata || hit);
      headings.forEach(([button, section]) => {
        if (section === group) button.setAttribute("aria-current", "location");
        else button.removeAttribute("aria-current");
      });
      if (!group) {
        excerpt.append(el("p", "The matched excerpt is unavailable in this document."));
        return;
      }
      if (group.label) excerpt.append(el("h3", group.label));
      const start = segment?.field === "code" ? Math.max(0, index - 1) : index;
      for (const item of group.segments.slice(start, index + 3)) {
        if (item.field === "heading" && item.text === group.label) continue;
        excerpt.append(sourceBlock(item));
      }
    }

    const sections = groups.filter((group) => group.label);
    if (sections.length) {
      const nav = el("nav", null, "preview-sections");
      nav.setAttribute("aria-label", "In this document");
      nav.append(el("h3", "In this document"));
      const list = el("ul");
      headings = sections.map((group) => {
        const item = el("li");
        const button = el("button", group.label);
        button.type = "button";
        const arrow = el("span", "→");
        arrow.setAttribute("aria-hidden", "true");
        button.append(arrow);
        button.addEventListener("click", () => {
          select(group, false);
          excerpt.tabIndex = -1;
          excerpt.focus({ preventScroll: true });
          dialog.scrollTo({ top: excerpt.getBoundingClientRect().top - dialog.getBoundingClientRect().top + dialog.scrollTop - $(".preview-top", dialog).offsetHeight });
        });
        item.append(button);
        list.append(item);
        return [button, group];
      });
      nav.append(list);
      body.append(nav);
    }
    select(matched, Boolean(matched));
  }

  async function open(hit, button, row) {
    if (active?.button === button) {
      close();
      return;
    }
    close({ restoreFocus: false });
    const controller = new AbortController();
    const { signal } = controller;
    active = { button, row, controller };
    title.textContent = hit.title;
    source.replaceChildren(sourceLabel(hit.source));
    body.replaceChildren();
    status.textContent = "Loading source excerpt…";
    status.classList.remove("error");
    setFooter(hit.evidence?.url || hit.url, hit);
    row.classList.add("is-previewed");
    button.setAttribute("aria-expanded", "true");
    const previousScroll = window.scrollY;
    show();
    if (window.scrollY !== previousScroll) window.scrollTo(0, previousScroll);
    dialog.scrollTop = 0;
    try {
      const data = await documentFor(hit, signal);
      if (signal.aborted) return;
      showAccepted(row, data);
      render(hit, data);
    } catch (error) {
      if (signal.aborted) return;
      status.classList.add("error");
      status.textContent = "Could not load the source excerpt. " + error.message;
    }
  }

  return { open, close };
}
