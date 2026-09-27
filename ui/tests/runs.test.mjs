/* The runs screen, rendered against the REAL export.

   The same discipline as the company tests: a DOM stub rather than jsdom, and
   every assertion made against the files the page actually reads. The counts in
   CD's spec were checked against the export before this screen was built; these
   tests are what keeps them true after the next one. */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { before, describe, it } from "node:test";
import { HAVE_EXPORT, itNeedsExport } from "./needs-export.mjs";

const EXPORT = new URL("../assets/export/", import.meta.url);
const HAVE = existsSync(new URL("manifest.json", EXPORT));
const read = (name) => JSON.parse(readFileSync(new URL(name, EXPORT), "utf8"));

/* ---- a DOM wide enough for this page's renderers ---- */
class Node {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.children = []; this.dataset = {}; this.style = {}; this.attrs = {};
    this._cls = new Set(); this._text = ""; this.parentElement = null; this.disabled = false;
    this.classList = { add: (c) => this._cls.add(c), remove: (c) => this._cls.delete(c), contains: (c) => this._cls.has(c) };
  }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._cls].join(" "); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this._text + this.children.map((c) => (c.nodeType === 3 ? c.data : c.textContent)).join("");
  }
  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children.at(-1); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener() {}
  append(...kids) {
    for (const k of kids) {
      const node = typeof k === "string" ? { nodeType: 3, data: k, parentElement: this } : k;
      node.parentElement = this;
      this.children.push(node);
    }
  }
  querySelector() { return null; }
  closest(sel) {
    const keys = sel.match(/data-[a-z-]+/g)?.map((d) => d.replace("data-", "").replace(/-(.)/g, (_, c) => c.toUpperCase())) ?? [];
    for (let n = this; n; n = n.parentElement) if (n.dataset && keys.some((k) => n.dataset[k] !== undefined)) return n;
    return null;
  }
}

const fetched = [];
function installDom() {
  globalThis.document = {
    createElement: (t) => new Node(t),
    createElementNS: (_ns, t) => new Node(t),
    createTextNode: (t) => ({ nodeType: 3, data: String(t), parentElement: null }),
    getElementById: () => new Node("div"),
    querySelector: () => null,
    querySelectorAll: () => [],
    body: new Node("body"),
  };
  globalThis.location = { search: "" };
  fetched.length = 0;
  globalThis.fetch = async (path) => {
    const name = String(path).replace(/^assets\/export\//, "");
    fetched.push(name);
    if (!existsSync(new URL(name, EXPORT))) return { status: 404, ok: false };
    return { status: 200, ok: true, json: async () => read(name) };
  };
}

/** Every node in a rendered tree, in order. */
function* walk(node) {
  yield node;
  for (const child of node.children ?? []) if (child.nodeType !== 3) yield* walk(child);
}
const byClass = (root, cls) => [...walk(root)].filter((n) => n._cls?.has(cls));
const unmarked = (root) => {
  const bad = [];
  const visit = (node) => {
    if (node.nodeType === 3) {
      if (/\d/.test(node.data) && !node.parentElement?.closest("[data-prov], [data-chrome], [data-audit-exempt]")) bad.push(node.data.trim());
      return;
    }
    if (node._text && /\d/.test(node._text) && !node.closest("[data-prov], [data-chrome], [data-audit-exempt]")) bad.push(node._text.trim());
    node.children?.forEach(visit);
  };
  visit(root);
  return bad;
};

const load = (m) => import(`../assets/js/${m}?${Math.random()}`);
const SOURCES = ["corpus", "edgar", "news", "unknown"];

let ctx = null;

async function build({ filters = { ticker: null, relation: "all", outcome: "all", freeze: "all" }, openRows = new Set() } = {}) {
  installDom();
  const source = await load("data/source.js");
  const [state, companies, unrun, journal] = await Promise.all([
    source.getExportState(), source.listCorpusCompanies(), source.listUnrunFilings(), source.listJournal(),
  ]);
  const rows = [];
  for (const name of SOURCES) rows.push(...journal.bySource[name]);
  const universe = new Map(companies.rows.map((r) => [r.ticker, r]));
  const { matches, renderFilters, quarterLabel } = await load("ui/runs-filters.js");
  const { renderJournal } = await load("ui/runs-journal.js");
  const { renderIdentity, renderPopulations, renderUnrun, renderDrift } = await load("ui/runs-header.js");
  const counts = Object.fromEntries(SOURCES.map((s) => [s, state.manifest.runs.rows[s]]));
  const filtered = rows.filter((r) => matches(r, filters));

  const groups = [...new Set(filtered.map((r) => quarterLabel(r.anchor_date)))].sort().reverse().map((label) => {
    const inGroup = filtered.filter((r) => quarterLabel(r.anchor_date) === label);
    return {
      label, rows: inGroup, total: rows.filter((r) => quarterLabel(r.anchor_date) === label).length,
      months: [], dates: new Set(inGroup.map((r) => r.anchor_date)).size,
      open: inGroup.filter((r) => source.isAbsent(r.outcome)).length,
      drift: inGroup.filter((r) => !source.isAbsent(r.anchor_drift)).length,
    };
  });

  const roots = { identity: new Node("section"), populations: new Node("section"), unrun: new Node("section"), drift: new Node("section"), journal: new Node("section") };
  renderIdentity(roots.identity, { rows, counts, universe });
  renderPopulations(roots.populations, { manifest: state.manifest, journal, counts });
  renderUnrun(roots.unrun, { filings: unrun });
  renderDrift(roots.drift, { rows, total: rows.length, selected: filters.ticker, onSelect: () => {} });
  const hosts = renderJournal(roots.journal, {
    state: "ready", rows, filtered, groups, allOpen: false,
    span: { min: 83, max: 191 }, monthSpan: { min: 3, max: 97 }, describe: [],
    // Every group open: the audit and the column assertions have to see all of it.
    openGroups: new Set(groups.map((g) => g.label)), openRows, universe,
    onToggleGroup: () => {}, onToggleRow: () => {},
  });
  renderFilters(hosts.filters, { rows, filtered, filters, query: "", universe, on: {} });
  return { roots, rows, filtered, unrun, source, universe, counts, manifest: state.manifest };
}

describe("the runs screen, against the real export", () => {
  // A hook is not a test and cannot be skipped, so it declines on its own.
  before(async () => { if (HAVE_EXPORT) ctx = await build(); });

  itNeedsExport("totals the four files and reads each of them separately", () => {
    const rows = ctx.manifest.runs.rows;
    const total = SOURCES.reduce((n, s) => n + rows[s], 0);
    const shown = byClass(ctx.roots.identity, "runs-total")[0].textContent;
    assert.match(shown, new RegExp(`^${total.toLocaleString("en-US")}`));
    assert.equal(total, ctx.rows.length, "the page's own rows agree with the manifest");
    for (const s of SOURCES) assert.ok(fetched.includes(`runs/by_source/${s}.json`), `${s}.json was read`);
    assert.ok(!fetched.some((f) => /runs\.json|all\.json/.test(f)), "there is no combined file to read");
  });

  itNeedsExport("never prints the ledger's item count anywhere", () => {
    for (const [name, root] of Object.entries(ctx.roots)) {
      assert.ok(!root.textContent.includes("709"), `${name} prints 709, which counts corpus items and not runs`);
    }
  });

  itNeedsExport("marks every number on screen, with the journal fully expanded", () => {
    for (const [name, root] of Object.entries(ctx.roots)) {
      assert.deepEqual(unmarked(root), [], `${name} has unmarked numbers`);
    }
  });

  itNeedsExport("labels nothing a score except the two statements that say there is none", () => {
    const hits = [...walk(ctx.roots.journal)].filter((n) => /score/i.test(n._text ?? ""));
    for (const node of hits) {
      const text = node._text;
      assert.ok(
        /no score column/i.test(text) || /^Score$/.test(text) || /Cannot be computed for a run/.test(text) ||
          /scores are per band and split/.test(text) || /^results →$/.test(text) ||
          /Scoring records key|Scoring is shown whole|Scoring keys on ticker/.test(text),
        `an element mentions a score: ${text.slice(0, 60)}`,
      );
    }
  });

  itNeedsExport("shows the ratio and no realised figure on every re-based row", () => {
    const drifted = ctx.rows.filter((r) => !ctx.source.isAbsent(r.anchor_drift));
    assert.equal(drifted.length, 9);
    const rendered = byClass(ctx.roots.journal, "runs-row").filter((r) => r.dataset.drift === "true");
    assert.equal(rendered.length, drifted.length);
    for (const row of rendered) {
      const real = byClass(row, "runs-c-real")[0];
      assert.match(real.textContent, /^×\d\.\d{6}$/, "the ratio, at six places");
      const figs = byClass(real, "fig");
      assert.equal(figs.length, 1, "the ratio is the only figure in the cell — no realised return");
      // Read from the row, not computed here: the ratio is measured.
      assert.equal(figs[0].dataset.prov, "measured");
      assert.ok(!/%/.test(real.textContent), "a re-based row shows no percentage");
    }
  });

  itNeedsExport("carries the filing date from the ledger on every panel row", () => {
    const panel = ctx.rows.filter((r) => r.corpus_relation === "ledger_item");
    assert.equal(panel.length, 701);
    const sameAsAnchor = panel.filter((r) => r.ledger_item.filing_date === r.anchor_date);
    assert.equal(sameAsAnchor.length, 66, "the cases a +1 derivation would get wrong");
    const rendered = byClass(ctx.roots.journal, "runs-row");
    let checked = 0;
    for (const [i, run] of ctx.filtered.entries()) {
      if (run.corpus_relation !== "ledger_item") continue;
      const cell = byClass(rendered[i], "runs-c-rel")[0];
      assert.ok(cell.textContent.includes(run.ledger_item.filing_date), `row ${i} shows the ledger's filing date`);
      checked += 1;
    }
    assert.equal(checked, 701);
  });

  itNeedsExport("lists the filings that never ran, each linking to its company page", () => {
    assert.equal(ctx.unrun.length, 8);
    const cells = byClass(ctx.roots.unrun, "runs-cell");
    assert.equal(cells.length, 8);
    for (const cell of cells) assert.match(cell.href, /^company\.html\?ticker=[A-Z.]+$/);
  });

  itNeedsExport("counts facet options by what choosing them would show", async () => {
    const { matches } = await load("ui/runs-filters.js");
    const filters = { ticker: null, relation: "repeat_of_exhibit", outcome: "all", freeze: "all" };
    const one = await build({ filters });
    const options = byClass(one.roots.journal, "runs-opt").length ? one.roots.journal : null;
    const opts = byClass(options ?? one.roots.journal, "runs-opt");
    const closed = opts.find((o) => o.textContent.startsWith("closed"));
    const expected = one.rows.filter((r) => matches(r, { ...filters, outcome: "closed" })).length;
    assert.match(closed.textContent, new RegExp(`${expected}$`), "the count is cross-filtered, not the raw total");
  });

  itNeedsExport("renders a zero-count option disabled rather than hiding it", async () => {
    const one = await build({ filters: { ticker: null, relation: "repeat_of_exhibit", outcome: "all", freeze: "all" } });
    const opts = byClass(one.roots.journal, "runs-opt");
    const open = opts.find((o) => o.textContent.startsWith("window open"));
    assert.ok(open, "the option is present");
    assert.equal(open.disabled, true);
    assert.equal(open.title, "No run in this export has this value");
  });

  itNeedsExport("keeps an open row open across a filter change, by run id", async () => {
    const target = ctx.rows.find((r) => r.corpus_relation === "repeat_of_exhibit");
    const before = await build({ openRows: new Set([target.run_id]) });
    assert.equal(byClass(before.roots.journal, "runs-detail").length, 1);
    const after = await build({
      filters: { ticker: null, relation: "repeat_of_exhibit", outcome: "all", freeze: "all" },
      openRows: new Set([target.run_id]),
    });
    const stillOpen = byClass(after.roots.journal, "runs-row").filter((r) => r.dataset.open === "true");
    assert.equal(stillOpen.length, 1, "the same run is still open after filtering");
    assert.equal(byClass(after.roots.journal, "runs-detail").length, 1);
  });

  itNeedsExport("states the convention of the realised number it actually shows", () => {
    const text = ctx.roots.journal.textContent;
    assert.match(text, /a log return, shown as the simple return it equals/);
  });
});

describe("the runs screen's own boundary", () => {
  itNeedsExport("returns four keys and no combined array", async () => {
    installDom();
    const source = await load("data/source.js");
    const journal = await source.listJournal();
    assert.deepEqual(Object.keys(journal.bySource), SOURCES);
    assert.ok(!("rows" in journal), "no flattened array at the boundary");
    assert.equal(journal.bySource.unknown.length, read("manifest.json").runs.rows.unknown);
  });

  itNeedsExport("states an unrecorded freeze version as absent, not as a blank", async () => {
    installDom();
    const source = await load("data/source.js");
    const journal = await source.listJournal();
    const unrecorded = journal.bySource.unknown.filter((r) => source.isAbsent(r.freeze_version));
    assert.equal(unrecorded.length, 68);
    assert.match(unrecorded[0].freeze_version.why, /predates the field/);
  });

  itNeedsExport("names the provider and the adjustment basis in the outcome sentence", async () => {
    installDom();
    const source = await load("data/source.js");
    const journal = await source.listJournal();
    const closed = journal.bySource.unknown.find((r) => r.outcome_status === "closed");
    const said = source.describeOutcome(closed).map((p) => p.text ?? "").join("");
    assert.match(said, /yfinance/);
    assert.match(said, /split-adjusted/);
    // The date is read from the row, never written into the copy.
    const retrieved = source.describeOutcome(closed).find((p) => p.why?.includes("the day the close was read"));
    assert.equal(retrieved.text, closed.outcome.retrieved_on);
  });
});
