// Course Access review queue (P3). No framework, no build step; talks to /api/course-access.
// Proposal text comes from documents and a local model: it is only ever set with textContent, never as HTML.
"use strict";

const API = "/api/course-access";
const app = document.getElementById("app");
const state = { jobs: [], job: null, busy: "", error: "" };
const WORKERS = { "structure worker": "Structure", "table worker": "Tables", "text worker": "Text" };

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

async function api(path, options) {
  const response = await fetch(API + path, options);
  if (response.status === 204) return null;
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : "request failed");
  }
  return response.json();
}

const json = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function run(label, fn) {
  state.busy = label; state.error = ""; render();
  try { await fn(); } catch (error) { state.error = error.message; }
  state.busy = ""; render();
}

// ---------- queue ----------

function uploadForm() {
  const file = h("input", { id: "file", type: "file", accept: ".pdf,.pptx,.docx", required: true });
  const alt = h("input", { id: "alt", type: "checkbox" });
  const cls = h("select", { id: "cls", "aria-label": "Data class" },
    h("option", { value: "I", text: "I: institutional (course materials)" }),
    h("option", { value: "P", text: "P: public" }),
    h("option", { value: "S", text: "S: sensitive" }));
  return h("form", { class: "upload", onsubmit: (e) => {
    e.preventDefault();
    if (!file.files.length) return;
    const body = new FormData();
    body.append("file", file.files[0]);
    run("Reading the document and proposing fixes (the alt-text model takes about 20 s per image)", async () => {
      const job = await api(`/jobs?alt_text=${alt.checked ? 1 : 0}&data_class=${cls.value}`, { method: "POST", body });
      location.hash = "#/job/" + job.id;
    });
  } },
    h("label", { class: "file", for: "file", text: "Course document (PDF, PPTX, DOCX)" }), file,
    h("label", { class: "check" }, alt, "Also propose alt text (vision model)"),
    cls,
    h("button", { type: "submit", class: "btn primary", text: "Audit and propose" }));
}

function queueTable() {
  if (!state.jobs.length) return h("p", { class: "muted", text: "No documents yet. Upload one to start." });
  return h("table", { class: "queue" },
    h("thead", null, h("tr", null, ...["Document", "Issues", "Proposals", "To review", "Decided", "Rebuilt", ""].map((t) => h("th", { text: t })))),
    h("tbody", null, ...state.jobs.map((j) => h("tr", null,
      h("td", null, h("a", { href: "#/job/" + j.id, text: j.name }), h("div", { class: "muted", text: `${j.format.toUpperCase()} · class ${j.data_class} · ${j.created.slice(0, 16).replace("T", " ")} UTC` })),
      h("td", { text: j.issues }), h("td", { text: j.proposals }), h("td", { text: j.to_review }), h("td", { text: j.decided }),
      h("td", { text: j.rebuilt ? "yes" : "no" }),
      h("td", null, h("button", { class: "btn", type: "button", text: "Delete", onclick: () => run("Deleting", async () => {
        await api("/jobs/" + j.id, { method: "DELETE" }); state.jobs = await api("/jobs"); }) }))))));
}

function renderQueue() {
  app.replaceChildren(
    h("section", { class: "hero" }, h("div", { class: "wrap" },
      h("h1", { text: "Review queue" }),
      h("p", { class: "muted", text: "Upload a course document. The audit finds the accessibility problems, the workers propose fixes, and you approve, edit or reject each one before the accessible version is built. Documents stay on this machine." }),
      uploadForm())),
    h("main", { id: "main", class: "wrap main" }, status(), queueTable()));
}

// ---------- job ----------

const where = (p) => p.page ? `page ${p.page}` : (p.block === null || p.block === undefined ? "document" : `block ${p.block}`);
const decisionOf = (kind, p) => (state.job.decisions[kind] || {})[String(p.id)] || null;

function valueText(value) {
  if (value === null || value === undefined) return "(a person must supply the value)";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value && typeof value === "object" && "text" in value) return value.text + (value.ordered ? " (numbered)" : " (bulleted)");
  return JSON.stringify(value);
}

function fixCard(p) {
  const d = decisionOf("fixes", p);
  const editable = typeof p.value === "string" || p.value === null;
  const input = editable ? h("input", { type: "text", value: (d && d.value !== undefined ? d.value : p.value) || "", "aria-label": "Proposed value" }) : null;
  const decide = (decision) => run("Saving", async () => {
    const body = { decision };
    if (decision === "approve" && input) body.value = input.value.trim() || null;
    await api(`/jobs/${state.job.id}/decisions`, json({ fixes: { [p.id]: decision ? body : { decision: null } } }));
    state.job = await api("/jobs/" + state.job.id);
  });
  return h("article", { class: "proposal" + (d ? " decided-" + d.decision : "") },
    h("div", null,
      h("div", { class: "where" }, h("span", { class: "flag" + (p.needs_review ? " review" : ""), text: p.needs_review ? "needs review" : "rule, confidence " + p.confidence.toFixed(2) }),
        `${where(p)} · ${p.rule} · ${p.action}`),
      editable ? input : h("div", { class: "value", text: valueText(p.value) }),
      h("div", { class: "evidence", text: (p.needs_review ? p.review_reason + ". " : "") + "Evidence: " + p.evidence + (p.model ? " (" + p.model + ")" : "") })),
    h("div", { class: "actions" },
      h("button", { type: "button", class: "btn primary", text: d && d.decision === "approve" ? "Approved" : "Approve", onclick: () => decide("approve") }),
      h("button", { type: "button", class: "btn", text: d && d.decision === "reject" ? "Rejected" : "Reject", onclick: () => decide("reject") }),
      d ? h("button", { type: "button", class: "btn linkish", text: "Undo", onclick: () => decide(null) }) : null));
}

function altCard(p) {
  const d = decisionOf("alt_texts", p);
  const alt = h("textarea", { rows: "2", "aria-label": "Alt text" });
  alt.value = d && d.alt !== undefined ? d.alt : p.alt;
  const decorative = h("input", { type: "checkbox" });
  decorative.checked = d && d.decorative !== undefined ? d.decorative : p.decorative;
  const decide = (decision) => run("Saving", async () => {
    const body = decision ? { decision, alt: alt.value.trim(), decorative: decorative.checked } : { decision: null };
    await api(`/jobs/${state.job.id}/decisions`, json({ alt_texts: { [p.id]: body } }));
    state.job = await api("/jobs/" + state.job.id);
  });
  return h("article", { class: "proposal" + (d ? " decided-" + d.decision : "") },
    h("div", null,
      h("div", { class: "where" }, h("span", { class: "flag" + (p.needs_review ? " review" : ""), text: p.needs_review ? "needs review" : "confidence " + p.confidence.toFixed(2) }),
        `${where(p)} · ${p.kind}`),
      h("img", { src: `${API}/jobs/${state.job.id}/images/${p.block}`, alt: "The image this proposal describes" }),
      alt,
      h("label", { class: "check" }, decorative, " Decorative (no alt text; hidden from screen readers)"),
      p.long_description ? h("div", { class: "evidence", text: "Long description: " + p.long_description }) : null,
      h("div", { class: "evidence", text: (p.needs_review ? p.review_reason + ". " : "") + "Model: " + p.model })),
    h("div", { class: "actions" },
      h("button", { type: "button", class: "btn primary", text: d && d.decision === "approve" ? "Approved" : "Approve", onclick: () => decide("approve") }),
      h("button", { type: "button", class: "btn", text: d && d.decision === "reject" ? "Rejected" : "Reject", onclick: () => decide("reject") }),
      d ? h("button", { type: "button", class: "btn linkish", text: "Undo", onclick: () => decide(null) }) : null));
}

function resultBox() {
  const job = state.job;
  const files = job.outputs.map((name) => h("a", { class: "btn", href: `${API}/jobs/${job.id}/files/${encodeURIComponent(name)}`, text: name }));
  const r = job.result;
  return h("section", { class: "group" },
    h("h2", { text: "Accessible version" }),
    h("div", { class: "row" }, h("button", { type: "button", class: "btn primary", text: r ? "Rebuild with current decisions" : "Build the accessible version",
      onclick: () => run("Rebuilding and auditing the result", async () => {
        await api(`/jobs/${job.id}/rebuild`, { method: "POST" }); state.job = await api("/jobs/" + job.id); }) })),
    r ? h("div", { class: "numbers" },
      h("div", null, h("b", { text: r.before }), h("span", { text: "issues before" })),
      h("div", null, h("b", { text: r.after }), h("span", { text: "issues after" })),
      h("div", null, h("b", { text: r.applied }), h("span", { text: "proposals applied" })),
      h("div", null, h("b", { text: r.waiting }), h("span", { text: "still waiting for review" })),
      h("div", null, h("b", { text: Object.values(r.new).reduce((a, b) => a + b, 0) }), h("span", { text: "newly visible issues" })))
      : h("p", { class: "muted", text: "Approved proposals and rule-based ones that need no review will be applied; rejected and waiting ones will not." }),
    r && r.notes.length ? h("ul", null, ...r.notes.map((n) => h("li", { text: n }))) : null,
    h("div", { class: "downloads" }, ...files));
}

function renderJob() {
  const job = state.job;
  const groups = Object.entries(WORKERS).map(([key, label]) => {
    const own = job.fixes.filter((p) => p.worker === key);
    return own.length ? h("section", { class: "group" }, h("h2", { text: `${label} (${own.length})` }), ...own.map(fixCard)) : null;
  });
  const alts = job.alt_texts.length ? h("section", { class: "group" }, h("h2", { text: `Alt text (${job.alt_texts.length})` }), ...job.alt_texts.map(altCard)) : null;
  const s = job.summary;
  app.replaceChildren(
    h("section", { class: "hero" }, h("div", { class: "wrap" },
      h("p", null, h("a", { href: "#/", text: "← Queue" })),
      h("h1", { text: job.name }),
      h("div", { class: "numbers" },
        h("div", null, h("b", { text: s.issues }), h("span", { text: "issues found" })),
        h("div", null, h("b", { text: s.proposals }), h("span", { text: "proposals" })),
        h("div", null, h("b", { text: s.to_review }), h("span", { text: "need a person" })),
        h("div", null, h("b", { text: s.decided }), h("span", { text: "decided" }))))),
    h("main", { id: "main", class: "wrap main" }, status(), resultBox(), ...groups, alts,
      h("section", { class: "group" }, h("h2", { text: "Not checked automatically" }),
        h("ul", null, ...job.issues.not_checked.map((t) => h("li", { text: t }))))));
}

function status() {
  if (state.error) return h("div", { class: "error", role: "alert", text: state.error });
  if (state.busy) return h("div", { class: "notice", role: "status", text: state.busy + "…" });
  return null;
}

// ---------- routing ----------

function render() {
  if (state.job) renderJob(); else renderQueue();
}

async function route() {
  const match = location.hash.match(/^#\/job\/([a-z0-9]+)$/);
  state.error = "";
  if (match) {
    await run("Loading", async () => { state.job = await api("/jobs/" + match[1]); });
  } else {
    state.job = null;
    await run("Loading", async () => { state.jobs = await api("/jobs"); });
  }
}

window.addEventListener("hashchange", route);
route();
