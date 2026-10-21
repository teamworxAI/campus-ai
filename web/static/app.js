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
  : h("span", { class: "badge bc", text: "BC · " + (card.source || "Arca") });
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
      box("Europeana (EU)", true, null, true), box("Arca (BC) · coming soon", false, null, true)),
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
      h("div", { class: "badges" }, h("span", { class: "badge bc", text: "BC · Arca" })),
      h("h2", { text: "BC collections" }),
      h("p", { text: "Arca results will appear here, side by side with Europeana, once the pilot collection is agreed with BC ELN." }),
      h("p", { class: "muted", text: "Status: data agreement in progress" })),
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

// ---------- routing ----------

function route() {
  const hash = location.hash || "#/";
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
