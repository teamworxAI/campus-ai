// Collections search front end (R9). No framework, no build step; talks to /api.
// Record text is untrusted: it is only ever set with textContent, never as HTML.
"use strict";

const app = document.getElementById("app");
const state = { mode: "words", query: "", results: null, show: { pictures: true, texts: true }, licences: null };
const LICENCE_GROUPS = ["Public domain", "CC0", "CC BY", "CC BY-SA"];

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "text") el.textContent = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const itemHref = (id) => "#/item/" + encodeURIComponent(id);
const licenceGroup = (label) => LICENCE_GROUPS.slice().reverse().find((g) => label.startsWith(g)) || "Other";
const sourceBadge = (card) => card.source === "europeana" ? h("span", { class: "badge eu", text: "EU · Europeana" })
  : h("span", { class: "badge bc", text: "BC · " + (card.source || "ArcaBC") });
const who = (card) => card.creators.length ? card.creators.join("; ") : "Creator not recorded";
const credit = (card) => card.licence.startsWith("CC BY") ? `${card.licence} · credit ${card.creators[0] || card.holder}` : card.licence;

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : "request failed");
  }
  return response.json();
}

// ---------- search page ----------

function searchForm() {
  const pick = (mode) => () => { state.mode = mode; renderSearch(); };
  const toggle = h("div", { class: "seg", role: "group", "aria-label": "Search by" },
    h("button", { type: "button", "aria-pressed": String(state.mode === "words"), onclick: pick("words"), text: "Words" }),
    h("button", { type: "button", "aria-pressed": String(state.mode === "image"), onclick: pick("image"), text: "By image" }));

  if (state.mode === "words") {
    const input = h("input", { id: "q", class: "q", type: "search", name: "q", value: state.query, required: true,
      maxlength: "300", placeholder: "e.g. salmon fishing on rivers", autocomplete: "off" });
    return h("form", { class: "search", role: "search", onsubmit: (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (q) location.hash = "#/search?q=" + encodeURIComponent(q);
    } }, toggle, h("label", { for: "q", class: "sr", text: "Search collections" }), input,
      h("button", { type: "submit", class: "btn primary", text: "Search" }));
  }

  const file = h("input", { id: "upload", type: "file", accept: "image/jpeg,image/png,image/webp,image/gif", class: "sr",
    onchange: () => file.files[0] && searchByImage(file.files[0]) });
  const drop = h("label", { for: "upload", class: "drop" },
    h("span", { text: "Drop a picture here, or choose a file, to find similar ones" }), file);
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files[0]) searchByImage(e.dataTransfer.files[0]);
  });
  return h("div", { class: "search" }, toggle, drop);
}

function filters(results) {
  const all = [...results.pictures, ...results.texts].map((c) => licenceGroup(c.licence));
  const groups = LICENCE_GROUPS.filter((g) => all.includes(g)).concat(all.includes("Other") ? ["Other"] : []);
  if (!state.licences) state.licences = new Set(groups);
  const box = (label, checked, onchange, disabled) => h("label", { class: disabled ? "off" : null },
    h("input", { type: "checkbox", checked, disabled, onchange }), label);
  const flip = (key) => (e) => { state.show[key] = e.target.checked; renderResults(); };
  const lic = (g) => (e) => { e.target.checked ? state.licences.add(g) : state.licences.delete(g); renderResults(); };
  // Open on wide screens; on phones a "Filters" disclosure keeps results near the top.
  return h("details", { class: "filters", open: matchMedia("(min-width: 701px)").matches },
    h("summary", { text: "Filters" }),
    h("fieldset", {}, h("legend", { text: "Source" }),
      box("Europeana (EU)", true, null, true), box("ArcaBC (BC) · pending permission", false, null, true)),
    h("fieldset", {}, h("legend", { text: "Show" }),
      box("Pictures", state.show.pictures, flip("pictures")), box("Books, reports and film", state.show.texts, flip("texts"))),
    groups.length ? h("fieldset", {}, h("legend", { text: "Licence" }),
      groups.map((g) => box(g, state.licences.has(g), lic(g))),
      h("p", { class: "muted", text: "Only openly licensed items are indexed." })) : null);
}

function pictureCard(card) {
  return h("li", { class: "card" },
    h("img", { src: card.image, alt: "Picture: " + card.title, loading: "lazy" }),
    h("div", { class: "card-body" },
      h("div", { class: "badges" }, sourceBadge(card), h("span", { class: "badge", text: card.matched })),
      h("h3", {}, h("a", { href: itemHref(card.id), text: card.title })),
      h("p", { class: "meta" }, who(card), h("br"), card.holder),
      h("p", { class: "muted", text: credit(card) }),
      h("div", { class: "actions" },
        h("button", { type: "button", class: "btn", onclick: () => openCite(card.id), text: "Cite" }),
        h("a", { class: "btn", href: itemHref(card.id) + "?similar", text: "Similar pictures" }),
        card.url ? h("a", { class: "linkish", href: card.url, rel: "noopener", target: "_blank", text: "Source" }) : null)));
}

function textRow(card) {
  const kind = { TEXT: "TEXT", VIDEO: "FILM", SOUND: "SOUND" }[card.type] || "ITEM";
  return h("li", { class: "row-card" },
    h("span", { class: "kind", "aria-hidden": "true", text: kind }),
    h("div", { class: "row-main" },
      h("h3", {}, h("a", { href: itemHref(card.id), text: card.title + (card.year ? ` (${card.year})` : "") })),
      h("p", { class: "meta", text: `${who(card)} · ${card.holder} · ${credit(card)}` }),
      h("span", { class: "badges" }, h("span", { class: "badge", text: card.matched }))),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn", onclick: () => openCite(card.id), text: "Cite" }),
      card.url ? h("a", { class: "linkish", href: card.url, rel: "noopener", target: "_blank", text: "Source" }) : null));
}

function rail() {
  return h("aside", { class: "rail", "aria-label": "BC collections and SFU experts" },
    h("section", { class: "panel" },
      h("div", { class: "badges" }, h("span", { class: "badge bc", text: "BC · ArcaBC" })),
      h("h2", { text: "BC collections" }),
      h("p", { text: "ArcaBC results will appear here, side by side with Europeana, once BC ELN grants permission to include its collections." }),
      h("p", { class: "muted", text: "Status: permission in progress" })),
    h("section", { class: "panel" },
      h("h2", { text: "Who at SFU works on this today?" }),
      h("p", { text: "Matching researchers from SFU's Research Expertise Engine will be listed here, each with the publication behind the match." }),
      h("p", { class: "muted", text: "Status: waiting on the REE integration" })));
}

// The uploaded picture and an honest verdict: the list always holds the nearest pictures in
// the index, so say when none of them is actually close.
function imageVerdict(results) {
  const n = results.indexed_items;
  const verdicts = {
    same: ["This picture is in the collection", "It is the first result. The others are the most similar pictures."],
    close: ["Similar pictures found", `The closest of the ${n} indexed items, best first.`],
    none: ["No close match", `Nothing among the ${n} indexed items looks like this picture. ` +
      "The pictures below are only the nearest ones, and are probably unrelated."],
  };
  const [title, body] = verdicts[results.match] || verdicts.none;
  return h("section", { class: `panel verdict ${results.match}`, role: "status" },
    results.preview ? h("img", { src: results.preview, alt: "Your picture", class: "verdict-img" }) : null,
    h("div", {}, h("h2", { text: title }), h("p", { text: body }),
      results.match === "none" ? h("p", { class: "muted", text: "The index currently holds the Europeana salmon pilot collection only." }) : null));
}

function renderResults() {
  const area = document.getElementById("results");
  if (!area || !state.results) return;
  const keep = (c) => state.licences.has(licenceGroup(c.licence));
  const pictures = state.show.pictures ? state.results.pictures.filter(keep) : [];
  const texts = state.show.texts ? state.results.texts.filter(keep) : [];
  const label = !state.results.byImage ? "European collections"
    : state.results.match === "none" ? "Nearest pictures in the index" : `Pictures like “${state.results.query}”`;
  area.replaceChildren(...[
    state.results.byImage ? imageVerdict(state.results) : null,
    h("div", { class: "head-row" },
      h("h2", { id: "eu-heading" }, label, h("span", { class: "sub", text: " · Europeana" })),
      h("span", { class: "muted", text: "Best matches first" })),
    pictures.length ? h("ol", { class: "grid", "aria-label": "Pictures" }, pictures.map(pictureCard)) : null,
    texts.length ? h("h2", { text: "Books, reports and film" }) : null,
    texts.length ? h("ol", { class: "list" }, texts.map(textRow)) : null,
    !pictures.length && !texts.length ? h("div", { class: "state", text: "Nothing matches. Try other words, another language, or fewer filters." }) : null,
  ].filter(Boolean));
}

function renderSearch(status) {
  const layout = h("main", { id: "main", class: "wrap layout" });
  if (state.results) layout.append(filters(state.results));
  const results = h("section", { id: "results", class: "results", "aria-live": "polite", "aria-labelledby": "eu-heading" });
  if (status) results.append(h("div", { class: "state", role: status.error ? "alert" : "status", text: status.text }));
  layout.append(results, rail());
  app.replaceChildren(
    h("section", { class: "hero" }, h("div", { class: "wrap" },
      h("h1", { text: "Find sources across BC and European collections" }),
      searchForm(),
      h("p", { class: "muted", text: "Ask in any language. Results match on meaning, on exact words, and on what pictures show. Every result names its source and licence." }))),
    layout);
  if (!status) renderResults();
}

async function runSearch(query) {
  state.query = query; state.mode = "words";
  document.title = `${query} · Collections search`;
  if (state.results && state.results.query === query && !state.results.byImage) return renderSearch();
  state.results = null; state.licences = null;
  renderSearch({ text: "Searching…" });
  try {
    state.results = await api("/api/search?q=" + encodeURIComponent(query));
    renderSearch();
  } catch (error) {
    renderSearch({ text: "Search failed: " + error.message, error: true });
  }
}

async function searchByImage(file) {
  if (state.results && state.results.preview) URL.revokeObjectURL(state.results.preview);
  state.results = null; state.licences = null; state.mode = "image";
  renderSearch({ text: "Looking for similar pictures…" });
  const body = new FormData();
  body.append("file", file);
  try {
    const found = await api("/api/search/image", { method: "POST", body });
    state.results = { ...found, byImage: true, preview: URL.createObjectURL(file) };
    renderSearch();
  } catch (error) {
    renderSearch({ text: "Image search failed: " + error.message, error: true });
  }
}

// ---------- item page ----------

async function renderItem(id, focusSimilar) {
  app.replaceChildren(h("main", { id: "main", class: "wrap item" }, h("div", { class: "state", role: "status", text: "Loading…" })));
  let item;
  try { item = await api("/api/items/" + encodeURIComponent(id)); } catch (error) {
    app.replaceChildren(h("main", { id: "main", class: "wrap item" }, h("div", { class: "state", role: "alert", text: "Could not load this item: " + error.message })));
    return;
  }
  document.title = `${item.title} · Collections search`;
  const back = state.query ? `#/search?q=${encodeURIComponent(state.query)}` : "#/";
  const fact = (term, value) => value ? [h("dt", { text: term }), h("dd", {}, value)] : [];
  const similar = item.similar.length ? h("section", { id: "similar", "aria-labelledby": "sim-h", class: "results" },
    h("h2", { id: "sim-h", text: "Similar pictures" }),
    h("ul", { class: "thumbs" }, item.similar.map((c) => h("li", {}, h("a", { href: itemHref(c.id) },
      h("img", { src: c.image, alt: "Picture: " + c.title, loading: "lazy" }), `${c.title} · ${credit(c)}`))))) : null;

  app.replaceChildren(h("main", { id: "main", class: "wrap item" },
    h("a", { href: back, class: "linkish", text: state.query ? `← Back to results for “${state.query}”` : "← New search" }),
    h("div", { class: "split" },
      item.image ? h("figure", {}, h("img", { src: item.image, alt: "Picture: " + item.title }),
        h("figcaption", { text: `Preview image. ${who(item)}, ${item.title}. ${item.holder}, ${item.licence}.` })) : null,
      h("section", { class: "detail", "aria-labelledby": "item-title" },
        h("div", { class: "badges" }, sourceBadge(item), h("span", { class: "badge", text: item.type.toLowerCase() || "item" }),
          h("span", { class: "badge", text: item.licence })),
        h("div", {}, h("h1", { id: "item-title", text: item.title }), item.description ? h("p", { class: "alt", text: item.description }) : null),
        h("dl", { class: "facts" },
          fact("Creator", who(item)), fact("Year", item.year), fact("Held by", item.holder),
          fact("Collection", item.collection),
          fact("Licence", item.rights ? h("a", { href: item.rights, rel: "noopener", target: "_blank", text: item.licence }) : item.licence),
          fact("Record", item.url ? h("a", { href: item.url, rel: "noopener", target: "_blank", text: item.url.replace(/^https?:\/\//, "") }) : null)),
        citeBox(item.citations))),
    h("div", { class: "split" },
      h("section", { class: "panel wide", "aria-labelledby": "ev-h" },
        h("h2", { id: "ev-h", text: "Linked records" }),
        h("ul", { class: "links" },
          item.creators.map((c) => h("li", {}, h("span", { class: "rel", text: "CREATED BY" }), c)),
          item.collection ? h("li", {}, h("span", { class: "rel", text: "IN" }), item.collection) : null,
          item.holder ? h("li", {}, h("span", { class: "rel", text: "HELD BY" }), item.holder) : null)),
      h("section", { class: "panel narrow", "aria-labelledby": "sfu-h" },
        h("h2", { id: "sfu-h", text: "Related work at SFU" }),
        h("p", { text: "Researchers working on this topic today will be shown here once SFU's Research Expertise Engine is connected." }))),
    similar));
  if (focusSimilar && similar) similar.scrollIntoView();
  else window.scrollTo(0, 0);
}

// Fill a style switcher (APA / Chicago / BibTeX) that shows each citation in `text`.
function citationStyles(citations, seg, text) {
  const show = (key) => {
    text.textContent = citations[key];
    for (const b of seg.children) b.setAttribute("aria-pressed", String(b.dataset.key === key));
  };
  seg.replaceChildren(...Object.entries({ apa: "APA", chicago: "Chicago", bibtex: "BibTeX" }).map(([key, name]) => {
    const b = h("button", { type: "button", "aria-pressed": "false", onclick: () => show(key), text: name });
    b.dataset.key = key;
    return b;
  }));
  show("apa");
}

function citeBox(citations) {
  const text = h("pre", { class: "cite-text" });
  const status = h("span", { class: "muted", role: "status" });
  const seg = h("div", { class: "seg small", role: "group", "aria-label": "Citation style" });
  citationStyles(citations, seg, text);
  return h("section", { class: "panel", "aria-labelledby": "cite-h" },
    h("div", { class: "head-row" }, h("h2", { id: "cite-h", text: "Cite this item" }), seg),
    text,
    h("div", { class: "row" }, h("button", { type: "button", class: "btn primary", text: "Copy citation",
      onclick: () => copy(text.textContent, status) }), status));
}

async function copy(value, status) {
  try { await navigator.clipboard.writeText(value); status.textContent = "Copied"; }
  catch (_) { status.textContent = "Select the text and copy it"; }
}

async function openCite(id) {
  const dialog = document.getElementById("cite");
  const text = document.getElementById("cite-text");
  const seg = document.getElementById("cite-styles");
  const status = document.getElementById("cite-status");
  text.textContent = "Loading…"; status.textContent = ""; seg.replaceChildren();
  dialog.showModal();
  try {
    const { citations } = await api("/api/items/" + encodeURIComponent(id));
    citationStyles(citations, seg, text);
  } catch (error) { text.textContent = "Could not load the citation: " + error.message; }
}
document.getElementById("cite-copy").addEventListener("click", () =>
  copy(document.getElementById("cite-text").textContent, document.getElementById("cite-status")));

// ---------- research journeys (R4): experts, EU partners, Horizon calls ----------
// Every result lists the graph evidence behind it: the publications, projects or call records.

const JOURNEYS = {
  experts: { title: "Find an SFU expert or supervisor for a topic", placeholder: "e.g. wildfire smoke and public health",
    path: "/api/experts", key: "experts", source: "OpenAlex, public publication records",
    note: "Ranked by fit to the topic. Each researcher is listed with the topics and publications behind the match, never by anything else." },
  partners: { title: "Find EU partners for a call or project idea", placeholder: "paste the call topic, or describe the project",
    path: "/api/partners", key: "partners", source: "CORDIS, Horizon Europe projects",
    note: "Organisations are reached through the Horizon Europe projects that match, so each one comes with the projects that are the evidence." },
  calls: { title: "Which open Horizon Europe calls fit this work?", placeholder: "describe the research, or paste a lab's profile",
    path: "/api/calls", key: "calls", source: "Funding & Tenders portal, open and forthcoming topics",
    note: "Open and forthcoming topics only, with deadlines and the portal page. Closed topics are kept in the graph for the back-test." },
};

function expertRow(r) {
  const e = r.evidence;
  return h("li", { class: "row-card" },
    h("div", { class: "row-main" },
      h("h3", {}, r.url ? h("a", { href: r.url, rel: "noopener", target: "_blank", text: r.name }) : r.name),
      h("p", { class: "meta", text: [r.institution, e.works ? `${e.works} works since 2021` : null].filter(Boolean).join(" · ") }),
      e.topics.length ? h("p", { class: "muted", text: "Topics: " + e.topics.slice(0, 5).join("; ") }) : null,
      e.publications.length ? h("ul", { class: "evidence" }, e.publications.map((p) => h("li", {},
        p.url ? h("a", { href: p.url, rel: "noopener", target: "_blank", text: p.title }) : p.title, p.year ? ` (${p.year})` : ""))) : null),
    h("div", { class: "row" },
      h("a", { class: "btn", href: `#/calls?for=${encodeURIComponent(r.id)}`, text: "Calls for this researcher" })));
}

function partnerRow(o) {
  return h("li", { class: "row-card" },
    h("div", { class: "row-main" },
      h("h3", {}, o.url ? h("a", { href: o.url, rel: "noopener", target: "_blank", text: o.name }) : o.name),
      h("p", { class: "meta", text: [o.country, o.activity, o.city, `${o.projects_total} Horizon Europe projects`].filter(Boolean).join(" · ") }),
      o.fields.length ? h("p", { class: "muted", text: "Fields: " + o.fields.slice(0, 5).join("; ") }) : null,
      h("ul", { class: "evidence" }, o.evidence.projects.slice(0, 4).map((p) => h("li", {},
        p.url ? h("a", { href: p.url, rel: "noopener", target: "_blank", text: p.acronym || p.title }) : (p.acronym || p.title),
        `: ${p.title}${p.role ? " (" + p.role + ")" : ""}`)))));
}

function callRow(c) {
  const when = [c.opening ? "opens " + c.opening : null, c.deadlines && c.deadlines.length ? "deadline " + c.deadlines.join(", ") : null].filter(Boolean).join(" · ");
  return h("li", { class: "row-card" },
    h("div", { class: "row-main" },
      h("h3", {}, h("a", { href: c.url, rel: "noopener", target: "_blank", text: `${c.identifier}: ${c.title}` })),
      h("p", { class: "meta", text: [c.call_title || c.call, c.status, when].filter(Boolean).join(" · ") }),
      (c.clusters || []).length || (c.actions || []).length ? h("p", { class: "muted", text: [...(c.clusters || []), ...(c.actions || [])].join(" · ") }) : null),
    h("div", { class: "row" },
      h("span", { class: "badge eu", text: c.status }),
      h("a", { class: "btn", href: `#/analysis?call=${encodeURIComponent(c.id)}`, text: "Analyse this call" }),
      h("a", { class: "btn", href: `#/brief?call=${encodeURIComponent(c.id)}`, text: "Draft a consortium" })));
}

// The call analyst (R4): facts from the funding records, then topics, outcomes and partner profile
// from the local model, each with the passage of the topic text it quotes (unquotable items are dropped).
function quotedList(title, items) {
  return h("section", { class: "panel" }, h("h2", { text: title }),
    items.length ? h("ul", { class: "evidence" }, items.map((item) => h("li", {}, h("strong", { text: item.text }),
      h("br"), h("span", { class: "muted", text: `“${item.span}”` }))))
      : h("p", { class: "muted", text: "Nothing the model said here could be found in the topic text." }));
}

async function renderAnalysis(params) {
  const callId = params.get("call");
  document.title = "Call analysis · Research Assistant";
  const results = h("section", { id: "results", class: "results", "aria-live": "polite" });
  app.replaceChildren(
    h("section", { class: "hero" }, h("div", { class: "wrap" }, h("h1", { text: "What does this call ask for?" }),
      h("p", { class: "muted", text: "Action type, consortium rule, deadlines and budget come from the funding records. Topics, expected outcomes and the partner profile are a reading by the local model; each quotes the topic text, and anything it cannot quote is dropped." }))),
    h("main", { id: "main", class: "wrap layout" }, results));
  if (!callId) { results.append(h("div", { class: "state", text: "Pick a call on the Horizon calls page." })); return; }
  results.append(h("div", { class: "state", role: "status", text: "Reading the call (the local model can take a few minutes)…" }));
  try {
    const a = await api(`/api/calls/${encodeURIComponent(callId)}/analysis`);
    const when = [a.opening ? "opens " + a.opening : null, a.deadlines.length ? "deadline " + a.deadlines.join(", ") : null].filter(Boolean).join(" · ");
    const money = a.budget ? `EUR ${(a.budget / 1e6).toLocaleString("en", { maximumFractionDigits: 1 })} million` + (a.expected_grants ? ` for about ${a.expected_grants} grant(s)` : "") : null;
    results.replaceChildren(
      h("div", { class: "head-row" }, h("h2", {}, h("a", { href: a.url, rel: "noopener", target: "_blank", text: `${a.identifier}: ${a.title}` }))),
      h("section", { class: "panel" }, h("h2", { text: "From the funding records" }),
        h("p", { text: [a.call, a.status, when].filter(Boolean).join(" · ") }),
        h("p", { text: `${a.action_type || "Action type not given"}: ${a.consortium_rule} (${a.rule_source}).` }),
        h("p", { text: "Canada: " + a.canada + "." }),
        money ? h("p", { text: "Budget: " + money + "." }) : null,
        a.clusters.length ? h("p", { text: "Programme: " + a.clusters.join(" · ") }) : null,
        a.keywords.length ? h("p", { class: "muted", text: "Keywords: " + a.keywords.join("; ") }) : null,
        a.conditions ? h("p", { class: "muted", text: "Conditions: " + a.conditions }) : null,
        a.described ? null : h("p", { class: "muted", text: "The topic page has not been fetched, so the reading below rests on the title and keywords only." })),
      a.model_error ? h("div", { class: "state", role: "alert", text: "The model's reading is missing: " + a.model_error }) : null,
      quotedList("Topics", a.topics),
      quotedList("Expected outcomes", a.expected_outcomes),
      quotedList("Partner profile", a.partner_profile),
      h("p", { class: "muted", text: [a.analysed_by ? `Read by ${a.analysed_by}${a.seconds ? ` in ${a.seconds} s` : ""}` : null,
        a.dropped ? `${a.dropped} item(s) dropped: their quote is not in the topic text` : null,
        "Evidence: " + a.evidence.id].filter(Boolean).join(". ") + "." }),
      h("div", { class: "row" },
        h("a", { class: "btn primary", href: "#/partners?q=" + encodeURIComponent(a.partner_query) + "&call=" + encodeURIComponent(a.id), text: "Find partners for this call" }),
        h("a", { class: "btn", href: `#/brief?call=${encodeURIComponent(a.id)}`, text: "Draft a consortium" })));
  } catch (error) {
    results.replaceChildren(h("div", { class: "state", role: "alert", text: "Failed: " + error.message }));
  }
}

// Journey 3: the partner shortlist for a call, the eligibility check and a citation-checked brief for review.
async function renderBrief(params) {
  const callId = params.get("call"), q = params.get("q") || "";
  document.title = "Consortium brief · Research Assistant";
  const input = h("input", { id: "q", class: "q", type: "search", name: "q", value: q, maxlength: "2000",
    placeholder: "or describe the project idea", autocomplete: "off" });
  const form = h("form", { class: "search", role: "search", onsubmit: (e) => {
    e.preventDefault();
    if (input.value.trim()) location.hash = "#/brief?q=" + encodeURIComponent(input.value.trim());
  } }, h("label", { for: "q", class: "sr", text: "Project idea" }), input, h("button", { type: "submit", class: "btn primary", text: "Draft" }));
  const results = h("section", { id: "results", class: "results", "aria-live": "polite" });
  app.replaceChildren(
    h("section", { class: "hero" }, h("div", { class: "wrap" }, h("h1", { text: "Draft a consortium for a call" }), form,
      h("p", { class: "muted", text: "The shortlist and the eligibility check are rules over public records. The brief is a draft from the local model; every sentence that cites an id outside the evidence is dropped, and the research office approves before any outreach." }))),
    h("main", { id: "main", class: "wrap layout" }, results));
  if (!callId && !q) { results.append(h("div", { class: "state", text: "Pick a call on the Horizon calls page, or describe the idea." })); return; }
  results.append(h("div", { class: "state", role: "status", text: "Finding partners, checking the rules and drafting the brief (the local model can take a few minutes)…" }));
  try {
    const data = await api("/api/brief", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(callId ? { call_id: callId } : { query: q }) });
    const el = data.eligibility;
    results.replaceChildren(
      data.call ? h("div", { class: "head-row" }, h("h2", {}, h("a", { href: data.call.url, rel: "noopener", target: "_blank", text: `${data.call.identifier}: ${data.call.title}` }))) : h("h2", { text: data.query }),
      h("section", { class: "panel" }, h("h2", { text: el.ok ? "Consortium rule: met" : "Consortium rule: not met yet" }),
        h("p", { text: `${el.action || "no action type given"}: ${el.rule}.` }),
        h("p", { text: "Countries: " + el.countries.map(([c, kind]) => `${c} (${kind})`).join(", ") }),
        ...el.problems.map((p) => h("p", { class: "muted", text: p }))),
      h("h2", { text: "Shortlist" }),
      h("ol", { class: "list" }, data.partners.map(partnerRow)),
      h("section", { class: "panel" }, h("h2", { text: "Brief for review" }),
        data.brief.error ? h("p", { class: "muted", text: "The model did not answer: " + data.brief.error }) : h("pre", { class: "cite-text", text: data.brief.brief }),
        data.brief.dropped && data.brief.dropped.length ? h("p", { class: "muted", text: `${data.brief.dropped.length} sentence(s) dropped for citing ids outside the evidence.` }) : null,
        data.brief.uncited && data.brief.uncited.length ? h("p", { class: "muted", text: `${data.brief.uncited.length} sentence(s) cite nothing; check them.` }) : null,
        h("p", { class: "muted", text: data.brief.model ? `Model: ${data.brief.model}. Nothing is sent: this is a draft for the research office.` : "Nothing is sent: this is a draft for the research office." })));
  } catch (error) {
    results.replaceChildren(h("div", { class: "state", role: "alert", text: "Failed: " + error.message }));
  }
}

async function renderJourney(kind, params) {
  const j = JOURNEYS[kind];
  const q = params.get("q") || "";
  const forId = kind === "calls" ? params.get("for") : null;
  document.title = `${j.title} · Research Assistant`;
  const input = h("input", { id: "q", class: "q", type: "search", name: "q", value: q, required: true, maxlength: "2000",
    placeholder: j.placeholder, autocomplete: "off" });
  const form = h("form", { class: "search", role: "search", onsubmit: (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (text) location.hash = `#/${kind}?q=` + encodeURIComponent(text);
  } }, h("label", { for: "q", class: "sr", text: j.title }), input, h("button", { type: "submit", class: "btn primary", text: "Search" }));
  const results = h("section", { id: "results", class: "results", "aria-live": "polite" });
  app.replaceChildren(
    h("section", { class: "hero" }, h("div", { class: "wrap" }, h("h1", { text: j.title }), form, h("p", { class: "muted", text: j.note }),
      kind === "experts" ? h("p", {}, h("a", { href: "#/ask", text: "Not sure which page fits? Ask in plain words" })) : null)),
    h("main", { id: "main", class: "wrap layout" }, results));
  if (!q && !forId) {
    results.append(h("div", { class: "state", text: `Source: ${j.source}.` }));
    return;
  }
  results.append(h("div", { class: "state", role: "status", text: "Searching…" }));
  try {
    const data = forId ? await api(`/api/calls/for/${encodeURIComponent(forId)}`) : await api(`${j.path}?q=${encodeURIComponent(q)}`);
    const rows = data[j.key];
    const heading = forId && data.researcher ? `Calls for ${data.researcher.name}` : `Results · ${j.source}`;
    results.replaceChildren(
      h("div", { class: "head-row" }, h("h2", { text: heading }), h("span", { class: "muted", text: "Best matches first" })),
      rows.length ? h("ol", { class: "list" }, rows.map(kind === "experts" ? expertRow : kind === "partners" ? partnerRow : callRow))
        : h("div", { class: "state", text: "Nothing matches. Try other words, or check that the graph is indexed." }));
    if (kind === "partners" && params.get("call") && rows.length) {
      const wait = h("div", { class: "state", role: "status", text: "Working out what each partner adds…" });
      results.prepend(wait);
      wait.replaceWith(await whatEachAdds(params.get("call"), q));
    }
  } catch (error) {
    results.replaceChildren(h("div", { class: "state", role: "alert", text: "Search failed: " + error.message }));
  }
}

// What each partner adds to a call (R4 complementarity scorer): facts only, every line citing the ids it rests on.
async function whatEachAdds(callId, q) {
  const box = h("section", { class: "panel" }, h("h2", { text: "What each adds" }));
  try {
    const c = await api(`/api/partners/complement?call=${encodeURIComponent(callId)}&q=${encodeURIComponent(q)}&n=3`);
    const s = c.set, el = c.complementary.eligibility;
    box.append(
      h("h3", { text: "Complementary set of 3" }),
      h("ol", { class: "evidence" }, c.complementary.picked.map((p) => h("li", { text: p.adds }))),
      h("p", { text: `${el.ok ? "Consortium rule met" : "Consortium rule not met yet"} with the home institution: ${el.rule}.` }),
      c.complementary.set.uncovered.length ? h("p", { class: "muted", text: "Not covered by the set: " + c.complementary.set.uncovered.join("; ") }) : null,
      c.complementary.set.roles_unfilled.length ? h("p", { class: "muted", text: "Roles still open: " + c.complementary.set.roles_unfilled.join("; ") }) : null,
      h("h3", { text: "Every partner on the shortlist" }),
      h("ul", { class: "evidence" }, c.partners.map((p) => h("li", { text: p.adds }))),
      h("p", { class: "muted", text: [
        "Countries: " + Object.keys(s.countries).join(", "),
        s.uncovered.length ? "covered by nobody: " + s.uncovered.join("; ") : "every need is covered by someone",
        s.roles_unfilled.length ? "roles unfilled: " + s.roles_unfilled.join("; ") : null].filter(Boolean).join(" · ") + "." }),
      c.model_error ? h("p", { class: "muted", text: "The call analysis is missing its model reading: " + c.model_error }) : null);
  } catch (error) {
    box.append(h("p", { class: "muted", text: "Could not score the shortlist: " + error.message }));
  }
  return box;
}

// One Ask box for every journey: the router picks it (rules first, the local model when no rule fires).
const ASK_ROWS = { partners: partnerRow, calls: callRow, experts: expertRow };

async function renderAsk(params) {
  const q = params.get("q") || "";
  document.title = "Ask · Research Assistant";
  const input = h("input", { id: "ask", class: "q", type: "search", name: "q", value: q, required: true, maxlength: "2000",
    placeholder: "e.g. who works on wildfire smoke? partners for HORIZON-MISS-2027-03-OCEAN-01?", autocomplete: "off" });
  const form = h("form", { class: "search", role: "search", onsubmit: (e) => {
    e.preventDefault();
    if (input.value.trim()) location.hash = "#/ask?q=" + encodeURIComponent(input.value.trim());
  } }, h("label", { for: "ask", class: "sr", text: "Ask" }), input, h("button", { type: "submit", class: "btn primary", text: "Ask" }));
  const results = h("section", { id: "results", class: "results", "aria-live": "polite" });
  app.replaceChildren(
    h("section", { class: "hero" }, h("div", { class: "wrap" }, h("h1", { text: "Ask the Research Assistant" }), form,
      h("p", { class: "muted", text: "Partners for a call, calls for your work, a consortium, an SFU expert or sources in the collections: the question picks the page." }))),
    h("main", { id: "main", class: "wrap layout" }, results));
  if (!q) return;
  results.append(h("div", { class: "state", role: "status", text: "Working out what you need…" }));
  try {
    const d = await api("/api/ask?q=" + encodeURIComponent(q));
    const key = ["partners", "calls", "experts"].find((k) => d[k]);
    const rows = key ? d[key] : [];
    const next = d.journey === 3 ? h("a", { class: "btn", href: d.call ? `#/brief?call=${encodeURIComponent(d.call.id)}` : "#/brief?q=" + encodeURIComponent(d.search), text: "Draft a consortium" })
      : d.journey === 1 && d.call ? h("a", { class: "btn", href: "#/analysis?call=" + encodeURIComponent(d.call.id), text: "Analyse this call, then see what each partner adds" })
      : d.journey === 5 ? h("a", { class: "btn primary", href: "#/search?q=" + encodeURIComponent(d.search), text: "Open in Collections" }) : null;
    results.replaceChildren(
      h("p", { class: "muted", text: `Routed to: journey ${d.journey}, ${d.name} (${d.why}). Searched for: ${d.search}` }),
      d.call ? h("div", { class: "head-row" }, h("h2", {}, h("a", { href: d.call.url, rel: "noopener", target: "_blank", text: `${d.call.identifier}: ${d.call.title}` }))) : null,
      next ? h("div", { class: "row" }, next) : null,
      d.journey === 5 ? h("p", { text: `${(d.pictures || []).length} pictures and ${(d.texts || []).length} texts found.` })
        : rows.length ? h("ol", { class: "list" }, rows.map(ASK_ROWS[key]))
          : h("div", { class: "state", text: "Nothing matches. Try other words." }));
  } catch (error) {
    results.replaceChildren(h("div", { class: "state", role: "alert", text: "Failed: " + error.message }));
  }
}

function setNav(kind) {
  for (const key of ["ask", "experts", "partners", "calls", "collections"]) {
    const link = document.getElementById("nav-" + key);
    if (link) link.toggleAttribute("aria-current", key === kind) && link.setAttribute("aria-current", "page");
    if (link && key !== kind) link.removeAttribute("aria-current");
  }
}

// ---------- routing ----------

function route() {
  const hash = location.hash || "#/";
  const journey = hash.match(/^#\/(experts|partners|calls|brief|analysis|ask)(\?.*)?$/);
  if (journey) {
    setNav(journey[1] === "brief" || journey[1] === "analysis" ? "calls" : journey[1]);
    const params = new URLSearchParams((journey[2] || "").slice(1));
    if (journey[1] === "analysis") return renderAnalysis(params);
    if (journey[1] === "ask") return renderAsk(params);
    return journey[1] === "brief" ? renderBrief(params) : renderJourney(journey[1], params);
  }
  setNav("collections");
  if (hash.startsWith("#/item/")) {
    const [rest, flag] = hash.slice(7).split("?");
    return renderItem(decodeURIComponent(rest), flag === "similar");
  }
  const q = new URLSearchParams(hash.split("?")[1] || "").get("q");
  if (q) return runSearch(q);
  state.results = null;
  document.title = "Collections search · Research Assistant";
  renderSearch();
}
window.addEventListener("hashchange", route);
route();
