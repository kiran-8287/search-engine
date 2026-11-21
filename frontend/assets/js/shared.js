export const $ = (selector, root = document) => root.querySelector(selector);

export function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

export const sourceName = (source) => source === "mdn" ? "MDN" : "Stack Overflow";
export const titleCase = (value) => value.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");

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
    // Source metadata without a usable URL remains text.
  }
  return node;
}

export async function api(path, { body, signal } = {}) {
  const response = await fetch("/api/v1" + path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  if (response.status === 204) return undefined;
  const value = await response.json();
  if (!response.ok) {
    throw new Error(typeof value.detail === "string" ? value.detail :
      Array.isArray(value.detail) ? value.detail.map((item) => item.msg).join("; ") : "Request failed.");
  }
  return value;
}

export function addOptions(select, values, blank) {
  if (blank) select.append(new Option(blank, ""));
  values.forEach(([value, label]) => select.append(new Option(label, value)));
  return select;
}

export function showJson(label, value) {
  const result = el("details");
  result.append(el("summary", label), el("pre", JSON.stringify(value, null, 2)));
  return result;
}

function attribution(item) {
  const node = el("p", null, "meta");
  if (item.author) node.append(item.author_url ? link(item.author, item.author_url) : el("span", item.author));
  if (item.content_license || item.license) node.append(el("span", item.content_license || item.license));
  return node;
}

const viewer = $("#viewer");
let viewWork;
viewer.addEventListener("close", () => viewWork?.abort());

export async function openDocument(id, evidence, release) {
  viewWork?.abort();
  viewWork = new AbortController();
  const { signal } = viewWork;
  const title = $("#viewer-title");
  const body = $("#viewer-body");
  title.textContent = "Document";
  body.replaceChildren(el("p", "Loading document…"));
  if (!viewer.open) viewer.showModal();
  try {
    const data = await api("/documents/" + encodeURIComponent(id) + (release ? "?release=" + encodeURIComponent(release) : ""), { signal });
    if (signal.aborted) return;
    title.textContent = data.title;
    body.replaceChildren(link("Open original source", evidence?.url || data.url), attribution(data.metadata));
    for (const flag of ["deprecated", "experimental"]) {
      if (data.metadata[flag]) body.append(el("p", titleCase(flag), "badge"));
    }
    const sections = new Map([[null, el("section")]]);
    body.append(sections.get(null));
    for (const answer of data.answers) {
      const section = el("section");
      section.append(el("h3", answer.is_accepted ? "Accepted answer" : "Answer"), link("Open original answer", answer.url), attribution(answer));
      sections.set(answer.answer_id, section);
      body.append(section);
    }
    let focused;
    for (const segment of data.segments) {
      const node = el(segment.field === "code" ? "pre" : segment.field === "heading" ? "h4" : "p", segment.text);
      (sections.get(segment.answer_id) || sections.get(null)).append(node);
      if (evidence?.ordinal === segment.ordinal) focused = node;
    }
    if (focused) focused.scrollIntoView({ block: "nearest" });
    if (data.metadata.browser_compat) body.append(showJson("Browser compatibility", data.metadata.browser_compat));
  } catch (error) {
    if (!signal.aborted) body.replaceChildren(el("p", error.message));
  }
}

export function resultItem(hit, { lab = false, judge } = {}) {
  const li = el("li", null, "result");
  const meta = el("div", null, "meta");
  meta.append(el("span", sourceName(hit.source), "badge" + (hit.source === "mdn" ? "" : " so")),
              el("span", titleCase(hit.topic)));
  if (lab) meta.append(el("span", "#" + hit.rank + " · " + hit.score.toFixed(5)));
  const heading = el("h3");
  heading.append(link(hit.title, hit.url));
  const snippet = el("p", null, "snippet");
  for (const piece of hit.snippet) snippet.append(piece.match ? el("mark", piece.text) : document.createTextNode(piece.text));
  const controls = el("div", null, "controls");
  const view = el("button", "View evidence", "secondary");
  view.type = "button";
  view.addEventListener("click", () => openDocument(hit.id, hit.evidence, hit.release_id));
  controls.append(view);
  if (judge) {
    for (const [value, label] of [[1, "Relevant"], [-1, "Not relevant"]]) {
      const button = el("button", label, "secondary");
      button.type = "button";
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", async () => {
        const saved = await judge(hit.id, value);
        if (saved) for (const peer of controls.querySelectorAll("[aria-pressed]")) {
          peer.setAttribute("aria-pressed", String(peer === button));
        }
      });
      controls.append(button);
    }
  }
  li.append(meta, heading, snippet, attribution(hit), controls);
  if (lab) li.append(showJson("Score explanation", { contributions: hit.explanation, evidence: hit.evidence }));
  return li;
}
