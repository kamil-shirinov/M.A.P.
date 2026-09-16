/* The company page, rendered against the REAL export.

   A DOM stub rather than jsdom: the repository has no build step and no
   dependencies, and the sections use a narrow slice of the DOM. The stub is
   enough to run them and to walk the result, which is what the provenance audit
   needs — the audit is the point of these tests, since it is the rule the page
   most easily breaks. */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { before, describe, it } from "node:test";

const EXPORT = new URL("../assets/export/", import.meta.url);
const HAVE = existsSync(new URL("manifest.json", EXPORT));

/* ---- a DOM small enough to read and large enough to render into ---- */
class Node {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.children = []; this.attrs = {}; this.dataset = {};
    this.classList = { add: (c) => this._cls.add(c), remove: (c) => this._cls.delete(c) };
    this._cls = new Set(); this._text = ""; this.parentElement = null;
  }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._cls].join(" "); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this._text + this.children.map((c) => (c.nodeType === 3 ? c.data : c.textContent)).join("");
  }
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
  querySelectorAll() { return []; }
  closest(sel) {
    // Only the audit's selector is needed: [data-prov], [data-chrome], [data-audit-exempt].
    const keys = sel.match(/data-[a-z-]+/g).map((d) => d.replace("data-", "").replace(/-(.)/g, (_, c) => c.toUpperCase()));
    for (let n = this; n; n = n.parentElement) {
      if (n.dataset && keys.some((k) => n.dataset[k] !== undefined)) return n;
    }
    return null;
  }
}

function installDom() {
  const doc = {
    createElement: (t) => new Node(t),
    createElementNS: (_ns, t) => new Node(t),
    createTextNode: (t) => ({ nodeType: 3, data: String(t), parentElement: null }),
    getElementById: () => new Node("div"),
    querySelector: () => null,
    querySelectorAll: () => [],
    body: new Node("body"),
  };
  globalThis.document = doc;
  globalThis.location = { search: "" };
  return doc;
}

function stubFetch() {
  globalThis.fetch = async (path) => {
    const name = String(path).replace(/^assets\/export\//, "");
    if (!existsSync(new URL(name, EXPORT))) return { status: 404, ok: false };
    return { status: 200, ok: true, json: async () => JSON.parse(readFileSync(new URL(name, EXPORT), "utf8")) };
  };
}

/** Every text node with a digit must sit inside a marked ancestor. This is the
    page's own rule, reimplemented over the stub tree. */
function unmarkedNumbers(root) {
  const bad = [];
  const walk = (node) => {
    if (node.nodeType === 3) {
      if (/\d/.test(node.data) && !node.parentElement?.closest("[data-prov], [data-chrome], [data-audit-exempt]")) {
        bad.push(node.data.trim());
      }
      return;
    }
    if (node._text && /\d/.test(node._text) && !node.closest("[data-prov], [data-chrome], [data-audit-exempt]")) {
      bad.push(node._text.trim());
    }
    node.children?.forEach(walk);
  };
  walk(root);
  return bad;
}

const load = (m) => import(`../assets/js/${m}?${Math.random()}`);

async function renderCompany(ticker) {
  installDom();
  stubFetch();
  const source = await load("data/source.js");
  const [company, runs, series, scoring, state] = await Promise.all([
    source.getCompany(ticker), source.listRuns(ticker), source.getPriceSeries(ticker),
    source.listScoringRecords(), source.getExportState(),
  ]);
  const roots = {};
  const mk = () => new Node("section");
  const { renderIdentity } = await load("ui/company-identity.js");
  const { renderSeries } = await load("ui/company-series.js");
  const { renderFilings } = await load("ui/company-filings.js");
  const { renderRuns } = await load("ui/company-runs.js");
  const { renderScoring } = await load("ui/company-scoring.js");
  const { renderFooter } = await load("ui/company-footer.js");

  renderIdentity((roots.identity = mk()), { company, runs });
  renderSeries((roots.series = mk()), { series, runs });
  renderFilings((roots.filings = mk()), { company, runs });
  renderRuns((roots.runs = mk()), { runs, company, open: new Set(), onToggle: () => {} });
  renderScoring((roots.scoring = mk()), { scoring, company });
  renderFooter((roots.footer = mk()), state.manifest);
  return { roots, company, runs, source };
}

describe("company page, against the real export", { skip: !HAVE }, () => {
  for (const ticker of ["ACHC", "ATI", "AAPL"]) {
    it(`${ticker}: every number on screen is marked`, async () => {
      const { roots } = await renderCompany(ticker);
      for (const [name, root] of Object.entries(roots)) {
        assert.deepEqual(unmarkedNumbers(root), [], `${ticker}/${name} has unmarked numbers`);
      }
    });
  }

  it("ACHC is the plain page: no drift, no repeat, no open window", async () => {
    const { runs, source } = await renderCompany("ACHC");
    const rows = Object.values(runs.bySource).flat();
    assert.equal(rows.length, 6);
    assert.ok(rows.every((r) => r.corpus_relation === "ledger_item"));
    assert.ok(rows.every((r) => r.outcome_status === "closed"));
    assert.ok(rows.every((r) => source.isAbsent(r.anchor_drift)));
  });

  it("ATI shows a repeat whose panel run does not exist", async () => {
    const { roots, company } = await renderCompany("ATI");
    const text = roots.runs.textContent;
    assert.match(text, /whose panel run does not exist/);
    assert.match(text, /not because a run exists and is shown elsewhere/);
    // And the filings table mirrors it without linking back.
    assert.match(roots.filings.textContent, /held, not run/);
    assert.equal(company.filings.filter((f) => !f.ran).length, 2);
  });

  it("AAPL shows drift and an open window, and keeps the outcome", async () => {
    const { roots } = await renderCompany("AAPL");
    const text = roots.runs.textContent;
    assert.match(text, /re-based since this run/);
    assert.match(text, /0\.988142|1\.007509/, "the ratio is shown at six places");
    assert.match(text, /horizon has not elapsed yet/);
    // A drifted run keeps its outcome; the marker is what stops the two from
    // looking identical.
    assert.match(text, /Closed at/);
    assert.match(text, /Not part of any published score/);
  });

  it("no run is both drifted and open, so that drift tail never renders", async () => {
    // The spec gives the drift block two tails, one for a closed outcome and one
    // for an open window. All 9 drifted runs are closed and both open runs are
    // undrifted, so the open-window tail is unreachable against this export. The
    // branch stays -- a later export can reach it -- and this pins the fact.
    const { runs, source } = await renderCompany("AAPL");
    const rows = Object.values(runs.bySource).flat();
    const drifted = rows.filter((r) => !source.isAbsent(r.anchor_drift));
    assert.ok(drifted.length > 0);
    assert.ok(drifted.every((r) => r.outcome_status === "closed"));
    assert.ok(rows.filter((r) => r.outcome_status === "window_open")
      .every((r) => source.isAbsent(r.anchor_drift)));
  });

  it("refuses the two renderings, on the page not silently", async () => {
    const { roots } = await renderCompany("ACHC");
    const text = roots.scoring.textContent;
    assert.match(text, /Not scored/);
    assert.match(text, /would claim that scored-eligible runs went unscored/);
    assert.match(text, /map_sigma but no p10, p50 or p90/);
    assert.match(text, /modelling presented as reading/);
  });

  it("never prints a per-run score", async () => {
    const { roots } = await renderCompany("ACHC");
    for (const word of ["CRPS", "crps", "PIT", "Brier", "log score"]) {
      assert.doesNotMatch(roots.runs.textContent, new RegExp(word), `${word} appeared on a run card`);
    }
  });

  it("states exchange as not loaded rather than fetching symbols.json", async () => {
    const { roots } = await renderCompany("ACHC");
    assert.match(roots.identity.textContent, /not loaded/);
    assert.match(roots.identity.textContent, /does not fetch a megabyte to fill one field/);
  });

  it("names the page a record rather than a projection", async () => {
    const { roots } = await renderCompany("ACHC");
    assert.match(roots.identity.textContent, /record of forecasts already made/);
    assert.match(roots.identity.textContent, /not a current projection/);
  });

  it("draws no y-axis ticks", async () => {
    const { roots } = await renderCompany("ACHC");
    const numbers = roots.series.textContent.match(/\d+\.\d\d/g) ?? [];
    // Only the last close is a number in this section; the axis carries dates.
    assert.ok(numbers.length <= 1, `unexpected numeric ticks: ${numbers}`);
  });

  it("carries filing_date from the ledger, not derived from the anchor", async () => {
    const { runs } = await renderCompany("ACHC");
    const rows = Object.values(runs.bySource).flat();
    const withItem = rows.filter((r) => r.ledger_item && !r.ledger_item.absent);
    assert.ok(withItem.length > 0);
    assert.ok(withItem.some((r) => r.ledger_item.filing_date !== r.anchor_date));
  });

  it("keeps the four run files apart", async () => {
    const { runs } = await renderCompany("AAPL");
    assert.deepEqual(Object.keys(runs.bySource).sort(), ["corpus", "edgar", "news", "unknown"]);
  });
});

describe("colour discipline", { skip: !HAVE }, () => {
  const css = readFileSync(new URL("../assets/styles/company.css", import.meta.url), "utf8");

  it("reserves amber for something that did not complete", () => {
    // The missing panel run is a terminal failure: attempted, settled, no
    // forecast. So is a filing held but never run. Both earn amber.
    const amberRules = css
      .split("}")
      .filter((block) => /var\(--uncal/.test(block))
      .map((block) => block.split("{")[0].trim());
    for (const selector of amberRules) {
      assert.match(
        selector,
        /cmp-panel-missing|cmp-unrun/,
        `amber on ${selector} -- it is reserved for work that did not complete`,
      );
    }
  });

  it("does not colour an open window as an attention state", () => {
    // A fact about the calendar: nothing is wrong, nothing refused, and it
    // resolves by itself. Distinguished by the dash, not by colour.
    const openRules = css.split("}").filter((b) => /cmp-anchor--open|window_open/.test(b.split("{")[0] ?? ""));
    assert.ok(openRules.length >= 3);
    for (const rule of openRules) {
      assert.doesNotMatch(rule, /var\(--uncal|var\(--down/, `open-window rule uses an alarm colour: ${rule}`);
    }
    assert.match(css, /cmp-anchor--open \{[^}]*stroke-dasharray/);
  });
});

describe("run identity on every card", { skip: !HAVE }, () => {
  it("shows an abbreviated run_id on all of them, not just collisions", async () => {
    const { roots, runs } = await renderCompany("AAPL");
    const rows = Object.values(runs.bySource).flat();
    const text = roots.runs.textContent;
    for (const run of rows) {
      assert.ok(text.includes(run.run_id.slice(0, 8)), `no id shown for ${run.run_id}`);
    }
  });

  it("distinguishes same-anchor runs, which are common rather than rare", async () => {
    // 62 (ticker, anchor, horizon) groups corpus-wide hold more than one run.
    // AAPL has three such pairs; without an id the cards are indistinguishable.
    const { runs } = await renderCompany("AAPL");
    const rows = Object.values(runs.bySource).flat();
    const seen = new Map();
    for (const r of rows) {
      const key = `${r.anchor_date}|${r.horizon_days}`;
      seen.set(key, (seen.get(key) ?? 0) + 1);
    }
    const collisions = [...seen.values()].filter((n) => n > 1).length;
    assert.equal(collisions, 3);
    assert.equal(new Set(rows.map((r) => r.run_id)).size, rows.length);
  });
});

describe("layout invariants", { skip: !HAVE }, () => {
  const css = readFileSync(new URL("../assets/styles/company.css", import.meta.url), "utf8");

  it("gives the masthead, content and footer one measure", () => {
    // They sat at different left edges: the masthead outside any container and
    // the content capped, so the difference read as dead space.
    assert.match(css, /\.masthead,\s*\n\s*\.company,\s*\n\s*\.cmp-footer \{[^}]*--measure/);
  });

  it("anchors the vintage stamps right without relying on a spacer element", () => {
    // base.css does this with a .spacer that this page's markup does not have.
    assert.match(css, /\.masthead-vintage \{ margin-left: auto/);
  });

  it("gives section headers more presence than body text", () => {
    const header = css.match(/\.cmp-h \{[^}]*\}/)[0];
    assert.match(header, /font-size: var\(--step-2\)/);
    assert.doesNotMatch(header, /--step--1/, "a section header must not be caption-sized");
    assert.match(header, /border-top/);
  });
});

describe("the pre-screen is a search question", { skip: !HAVE }, () => {
  it("does not appear on a company page", async () => {
    const { roots } = await renderCompany("ACHC");
    for (const root of Object.values(roots)) {
      assert.doesNotMatch(root.textContent, /recent EDGAR block/);
      assert.doesNotMatch(root.textContent, /Item 2\.02 8-Ks/);
    }
  });

  it("is still reachable from the boundary, for the screen that needs it", async () => {
    installDom();
    stubFetch();
    const source = await load("data/source.js");
    const screen = await source.getFilerScreen("AAPL");
    assert.equal(typeof screen.item_202_in_recent, "boolean");
  });
});

describe("URL forms", { skip: !HAVE }, () => {
  const js = readFileSync(new URL("../assets/js/company.js", import.meta.url), "utf8");

  it("accepts ?ticker= as the linked form and keeps ?example= for review", () => {
    assert.match(js, /params\.get\("ticker"\)/);
    assert.match(js, /params\.get\("example"\)/);
  });

  it("marks a ticker link as linked, never as an example name", () => {
    // Styling keyed on an example must not silently apply to an arbitrary
    // company reached from search.
    assert.match(js, /mode: "linked"/);
    assert.match(js, /dataset\.example = mode/);
  });

  it("renders a stated absence for a ticker the corpus does not hold", () => {
    // CD's patch header said the identity section already handled this. It did
    // not: renderIdentity prints undefined and renderFilings throws on
    // company.filings. The guard is in the composition root instead.
    assert.match(js, /source\.isAbsent\(company\)/);
    assert.match(js, /function renderUnknownCompany/);
    assert.doesNotMatch(
      js.slice(js.indexOf("onToggle:"), js.indexOf("renderScoring")),
      /function renderUnknownCompany/,
      "the handler must be at module level, not inside a callback",
    );
  });
});

describe("the four screen defects", { skip: !HAVE }, () => {
  const css = readFileSync(new URL("../assets/styles/company.css", import.meta.url), "utf8");

  it("resolves a repeat's panel run by anchor, not by filing arithmetic", async () => {
    // TSLA's 2026-01-02 filing is one of the 66 whose anchor IS the filing date.
    // A `filing + 1` rule found nothing there and printed ATI's copy about a
    // panel run that does not exist, while a9b0c9d8 sat in the filings table on
    // the same page.
    const { roots } = await renderCompany("TSLA");
    const text = roots.runs.textContent;
    assert.doesNotMatch(text, /filing not identified/);
    assert.doesNotMatch(text, /whose panel run does not exist/);
    assert.match(text, /the panel's run is a9b0c9d8, anchored 2026-01-02/);
  });

  it("still reports the one repeat whose panel run really is absent", async () => {
    const { roots } = await renderCompany("ATI");
    assert.match(roots.runs.textContent, /filed 2026-02-03, whose panel run does not exist/);
  });

  it("names the two different run counts rather than showing one", async () => {
    // Search counts panel runs from corpus.json; this page counts every run for
    // the ticker. TSLA is 12 and 16. Unlabelled they read as a contradiction.
    const { roots, runs, company } = await renderCompany("TSLA");
    const panel = company.filings.reduce((n, f) => n + f.run_ids.length, 0);
    const all = Object.values(runs.bySource).flat().length;
    assert.equal(panel, 12);
    assert.equal(all, 16);
    assert.match(roots.identity.textContent, /Panel runs/);
    assert.match(roots.identity.textContent, /Runs on this page/);
  });

  it("colours neither half of the split", () => {
    // Accent means panel membership, and dev and holdout are both the panel.
    // Same overloading that took clean/ambiguous neutral.
    assert.doesNotMatch(css, /\.cmp-badge--holdout \{/);
    assert.doesNotMatch(css, /\.cmp-badge--dev \{/);
    const base = css.match(/\.cmp-badge \{[^}]*\}/)[0];
    assert.doesNotMatch(base, /var\(--accent/);
  });

  it("gives the badge an outline that survives the row it sits on", () => {
    // The dev text measured 6.62:1 and was never the problem: the border was
    // --rule-2, about 1.3:1 on a sunken row, so the badge had no shape.
    const base = css.match(/\.cmp-badge \{[^}]*\}/)[0];
    assert.match(base, /border: 1px solid var\(--ink-3\)/);
    assert.doesNotMatch(base, /border: 1px solid var\(--rule-2\)/);
  });

  it("centres the unknown-company state instead of pinning it to the top", () => {
    const empty = css.match(/\.cmp-empty \{[^}]*\}/)[0];
    assert.match(empty, /min-height/);
    assert.match(empty, /justify-content: center/);
  });
});
