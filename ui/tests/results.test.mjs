/* The results screen, rendered against the REAL export.

   Every figure in CD's build spec was recomputed from the record files before
   this screen was built, and these tests are what keeps them true after the next
   re-export. Where the spec and the files disagreed, the files win and the test
   states the file's number.

   The tail counts get their own block. Two definitions of `z` are defensible and
   they give different answers on the same items (11 against 13 over 2.5), so the
   test pins BOTH and asserts which one the page shows. */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { before, describe, it } from "node:test";
import { HAVE_EXPORT, itNeedsExport } from "./needs-export.mjs";

const ROOT = new URL("../", import.meta.url);
const EXPORT = new URL("assets/export/", ROOT);
const HAVE = existsSync(new URL("manifest.json", EXPORT));
const read = (name) => JSON.parse(readFileSync(new URL(name, EXPORT), "utf8"));
const file = (p) => readFileSync(new URL(p, ROOT), "utf8");

/* ---- a DOM wide enough for this page's renderers ---- */
class Node {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.children = []; this.dataset = {}; this.style = {}; this.attrs = {};
    this._cls = new Set(); this._text = ""; this.parentElement = null;
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
  addEventListener(name, fn) { (this._on ??= {})[name] = fn; }
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

const load = (m) => import(new URL(`assets/js/${m}?${Math.random()}`, ROOT));

/* ---- the numbers, recomputed here from the files, independently of the page --- */
const CLEAN = "scores/clean.dev.2026-09-05.1997f7352e47.json";
const AMBIG = "scores/ambiguous.dev.2026-09-05.e66b2fab1cfb.json";
const DIRTY = "scores/clean.dev.2026-09-05.dirty.json";

const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
const rms = (xs) => Math.sqrt(mean(xs.map((x) => x * x)));

let ctx = null;

async function build({ band = "clean" } = {}) {
  installDom();
  const source = await load("data/source.js");
  const records = await source.listScoringRecords();
  const loaded = new Map();
  for (const [name, meta] of records.preferred) {
    const record = await source.getScoringRecord(meta.file);
    loaded.set(name, { record, stats: source.scoreStatistics(record.items) });
  }
  const holdout = await source.readHoldoutSpend();

  const { renderIdentity } = await load("ui/results-identity.js");
  const { renderPit } = await load("ui/results-pit.js");
  const baselines = await load("ui/results-baselines.js");
  const leakage = await load("ui/results-leakage.js");
  const direction = await load("ui/results-direction.js");
  const holdoutUi = await load("ui/results-holdout.js");
  const { whyGroups } = await load("ui/results-disclosure.js");
  const { renderPageWhy } = await load("ui/page-why.js");

  const here = loaded.get(band);
  const both = [...loaded.values()].map((e) => ({ stats: e.stats, summaries: e.record.summaries }));
  const domains = {
    crps: baselines.domainFor(both, { key: "crps", field: "crps" }),
    "log score": baselines.domainFor(both, { key: "log score", field: "log_score" }),
  };

  const roots = {
    identity: new Node("section"), pit: new Node("section"), baselines: new Node("section"),
    leakage: new Node("section"), direction: new Node("section"), holdout: new Node("section"),
    disclosure: new Node("section"),
  };
  renderIdentity(roots.identity, {
    meta: records.preferred.get(band), record: here.record, stats: here.stats,
    records, band, onBand: () => {},
  });
  renderPit(roots.pit, { stats: here.stats, pending: "…" });
  baselines.renderBaselines(roots.baselines, {
    stats: here.stats, summaries: here.record.summaries, domains, pending: "…",
  });
  leakage.renderLeakage(roots.leakage, {
    clean: loaded.get("clean").stats, ambiguous: loaded.get("ambiguous").stats, pending: "…",
  });
  direction.renderDirection(roots.direction, { stats: here.stats, items: here.record.items, pending: "…" });
  holdoutUi.renderHoldout(roots.holdout, { holdout, pending: "…" });
  renderPageWhy(roots.disclosure, {
    groups: whyGroups({ holdoutReason: records.holdout?.why ?? null, stats: here.stats, band }),
  });

  return { roots, source, records, loaded, holdout, domains, band, mods: { baselines, leakage, direction, holdoutUi } };
}

describe("the results screen, against the real export", () => {
  // A hook is not a test and cannot be skipped, so it declines on its own.
  before(async () => { if (HAVE_EXPORT) ctx = await build(); });

  itNeedsExport("reads the manifest, both identifiable records and the spend — and never the dirty one", () => {
    assert.ok(fetched.includes("manifest.json"));
    assert.ok(fetched.includes(CLEAN), "the clean record with a digest");
    assert.ok(fetched.includes(AMBIG), "the ambiguous record");
    assert.ok(fetched.includes("scores/holdout_spend.json"), "the holdout's terms");
    assert.ok(!fetched.includes(DIRTY), "the record with a null digest is named, never fetched");
    for (const never of ["runs/by_source/unknown.json", "universe.json", "symbols.json", "filers.json", "corpus.json"]) {
      assert.ok(!fetched.includes(never), `${never} is not this screen's file`);
    }
  });

  itNeedsExport("marks every number on screen", () => {
    for (const [name, root] of Object.entries(ctx.roots)) {
      assert.deepEqual(unmarked(root), [], `${name} has unmarked numbers`);
    }
  });

  itNeedsExport("prefers the record with a forecast digest and names the other without averaging", () => {
    const clean = ctx.records.preferred.get("clean");
    assert.equal(clean.file, CLEAN);
    assert.ok(clean.forecast_digest, "the shown record names its code");
    assert.equal(ctx.records.twins.get("clean").forecast_digest, null);
    const twin = byClass(ctx.roots.identity, "res-twin")[0].textContent;
    assert.match(twin, /not shown, not averaged/);
    // Nothing on the page is a mean of the two: both carry the same statistics,
    // so an average would be invisible. The guard is that it is never fetched.
    assert.ok(!fetched.includes(DIRTY));
  });
});

describe("the first paint, before any record has landed", () => {
  itNeedsExport("marks the reading lines, which carry a file size", async () => {
    installDom();
    const { renderPit } = await load("ui/results-pit.js");
    const baselines = await load("ui/results-baselines.js");
    const leakage = await load("ui/results-leakage.js");
    const direction = await load("ui/results-direction.js");
    const holdout = await load("ui/results-holdout.js");
    const say = "Reading the clean record — 133.5 KB…";

    const roots = {};
    roots.pit = new Node("section"); renderPit(roots.pit, { stats: null, pending: say });
    roots.baselines = new Node("section");
    baselines.renderBaselines(roots.baselines, { stats: null, summaries: null, domains: { crps: 1, "log score": 1 }, pending: say });
    roots.leakage = new Node("section");
    leakage.renderLeakage(roots.leakage, { clean: null, ambiguous: null, pending: say });
    roots.direction = new Node("section");
    direction.renderDirection(roots.direction, { stats: null, items: [], pending: say });
    roots.holdout = new Node("section");
    holdout.renderHoldout(roots.holdout, { holdout: null, pending: say });

    for (const [name, root] of Object.entries(roots)) {
      assert.deepEqual(unmarked(root), [], `${name} has an unmarked number before its record lands`);
      assert.match(root.textContent, /133\.5 KB/, `${name} says what it is reading`);
    }
  });

  itNeedsExport("renders the identity block from the manifest alone", async () => {
    installDom();
    const source = await load("data/source.js");
    const records = await source.listScoringRecords();
    const { renderIdentity } = await load("ui/results-identity.js");
    const root = new Node("section");
    renderIdentity(root, { meta: records.preferred.get("clean"), record: null, stats: null, records, band: "clean", onBand: () => {} });
    assert.deepEqual(unmarked(root), []);
    // n, the digest, the vintage and the freeze are in the 2.2 KB manifest.
    assert.match(root.textContent, /175/);
    assert.match(root.textContent, /1997f735/);
    assert.match(root.textContent, /freeze 2\.6\.0/);
    // The commit and the item counts are not, and are not invented.
    assert.match(root.textContent, /commit …/);
    assert.match(root.textContent, /… tickers/);
  });
});

describe("the figures, recomputed from the record files", () => {
  const record = () => read(CLEAN);

  itNeedsExport("reproduces the PIT histogram, the ratio and the PIT mean", async () => {
    installDom();
    const source = await load("data/source.js");
    const stats = source.scoreStatistics(record().items);
    assert.deepEqual(stats.histogram, [27, 16, 15, 13, 17, 13, 17, 24, 13, 20]);
    assert.equal(stats.histogram.reduce((a, b) => a + b, 0), 175);
    assert.equal(stats.calibrationRatio.toFixed(3), "0.733");
    assert.equal(stats.pitMean.toFixed(3), "0.489");
    assert.equal(stats.tickers, 59);
    assert.equal(stats.dates, 66);
    assert.deepEqual(stats.horizons, [5]);
  });

  itNeedsExport("puts a PIT of exactly 1 in the last bin rather than off the end", async () => {
    installDom();
    const source = await load("data/source.js");
    const items = record().items.slice(0, 3).map((i, k) => ({ ...i, map_pit: [0, 0.5, 1][k] }));
    const stats = source.scoreStatistics(items);
    assert.deepEqual(stats.histogram, [1, 0, 0, 0, 0, 1, 0, 0, 0, 1]);
  });

  itNeedsExport("reproduces both rules' means and deltas on the clean band", async () => {
    installDom();
    const source = await load("data/source.js");
    const items = record().items;
    const stats = source.scoreStatistics(items);
    assert.equal(stats.map.crps.toFixed(5), "0.03179");
    assert.equal(stats.map.log_score.toFixed(4), "-1.3786");
    // The three deltas, at the places the screen prints them. random_walk and
    // garch are positive: M.A.P. is WORSE on both rules against both.
    const delta = (field, b) => stats.map[field] - stats.baselines[b][field];
    assert.equal(delta("crps", "random_walk").toFixed(5), "0.00163");
    assert.equal(delta("crps", "garch").toFixed(5), "0.00075");
    assert.equal(delta("crps", "earnings_scaled_random_walk").toFixed(5), "-0.00100");
    assert.equal(delta("log_score", "random_walk").toFixed(4), "0.2040");
    assert.equal(delta("log_score", "garch").toFixed(4), "0.1873");
    assert.equal(delta("log_score", "earnings_scaled_random_walk").toFixed(4), "-0.0272");
  });

  itNeedsExport("counts the direction and the P(up) span", async () => {
    installDom();
    const source = await load("data/source.js");
    const stats = source.scoreStatistics(record().items);
    assert.equal(stats.directionRight, 87);
    assert.equal(stats.n, 175);
    assert.equal(stats.probabilityUp.min.toFixed(3), "0.369");
    assert.equal(stats.probabilityUp.max.toFixed(3), "0.631");
    const ambiguous = source.scoreStatistics(read(AMBIG).items);
    assert.equal(ambiguous.directionRight, 88);
    assert.equal(ambiguous.n, 174);
    assert.equal(ambiguous.calibrationRatio.toFixed(3), "0.679");
    assert.equal(ambiguous.pitMean.toFixed(3), "0.475");
  });

  itNeedsExport("checks the Brier claim against every item instead of asserting it", async () => {
    installDom();
    const source = await load("data/source.js");
    const stats = source.scoreStatistics(record().items);
    assert.equal(stats.baselineBrierIsOneComparison, true);
    assert.equal(stats.map.brier.toFixed(5), "0.25193");
    // One item moved off 0.25 and the claim must fail, so the page cannot be
    // printing a constant it never looked at.
    const tampered = record().items.map((i, k) =>
      k ? i : { ...i, baseline_brier: { ...i.baseline_brier, garch: 0.26 } });
    assert.equal(source.scoreStatistics(tampered).baselineBrierIsOneComparison, false);
  });
});

describe("the tail counts, and which z they use", () => {
  itNeedsExport("counts |z| with z = inverse-normal(PIT), which is the published definition", async () => {
    installDom();
    const source = await load("data/source.js");
    const { inverseNormalCdf } = await load("lib/gaussian.js");
    const items = read(CLEAN).items;
    const stats = source.scoreStatistics(items);

    // The definition the page uses: the standardised distance from the
    // forecast's own CENTRE. Pre-registered on ad71b13 as "z = Phi^-1(PIT)",
    // and the counts it gives here are the ones the record was published with.
    const byPit = items.map((i) => inverseNormalCdf(i.map_pit));
    assert.equal(byPit.filter((z) => Math.abs(z) > 2.5).length, 11);
    assert.equal(byPit.filter((z) => Math.abs(z) > 3).length, 7);
    assert.equal(stats.tails[2.5], 11);
    assert.equal(stats.tails[3], 7);
    // The blocks those exceedances fall in — 7 and 5, as the record reports.
    assert.equal(stats.tailBlocks[2.5], 7);
    assert.equal(stats.tailBlocks[3], 5);

    // The OTHER definition, which ignores the forecast's centre. It is a
    // different statistic, not a different route to this one, and it gives a
    // different answer. Pinned so that a future change from one to the other
    // cannot happen quietly.
    const byRatio = items.map((i) => i.realised_return / i.map_sigma);
    assert.equal(byRatio.filter((z) => Math.abs(z) > 2.5).length, 13);
    assert.equal(byRatio.filter((z) => Math.abs(z) > 3).length, 7);
    assert.notEqual(stats.tails[2.5], byRatio.filter((z) => Math.abs(z) > 2.5).length);
  });

  itNeedsExport("names the sample beside every tail count", async () => {
    const shown = byClass(ctx.roots.pit, "res-tail").map((n) => n.textContent);
    assert.equal(shown.length, 2);
    for (const line of shown) assert.match(line, /of 175/, "a bare count reads as a contradiction");
    /* The definition is stated ONCE, under both rows, rather than repeated under
       each — where it read as two different z's that happened to share a name.
       It is still on the page: that is the assertion, not where it sits. */
    assert.match(ctx.roots.pit.textContent, /z = Φ⁻¹\(PIT\)/, "the definition is on the page");
    const repeats = ctx.roots.pit.textContent.match(/z = Φ⁻¹\(PIT\)/g) ?? [];
    assert.equal(repeats.length, 1, "and said once");
  });

  itNeedsExport("refuses a PIT outside the open interval rather than inventing a z", async () => {
    const { inverseNormalCdf } = await load("lib/gaussian.js");
    for (const p of [0, 1, -0.1, 1.5, NaN]) assert.throws(() => inverseNormalCdf(p), RangeError);
    // Accurate enough for the thresholds it is compared against.
    assert.ok(Math.abs(inverseNormalCdf(0.975) - 1.959963985) < 1e-7);
    assert.ok(Math.abs(inverseNormalCdf(0.5)) < 1e-12);
  });
});

describe("intervals and verdicts are quoted, never computed", () => {
  itNeedsExport("parses every interval out of the record's own sentence", async () => {
    const { parseSummary, summaryFor, BASELINES } = await load("ui/results-baselines.js");
    for (const f of [CLEAN, AMBIG]) {
      const record = read(f);
      for (const rule of ["crps", "log score"]) {
        for (const b of BASELINES) {
          const parsed = summaryFor(record.summaries[rule], b);
          assert.ok(parsed, `${f} ${rule} has a line for ${b}`);
          assert.ok(parsed.interval, "every line on this export carries an interval");
          assert.ok(parsed.interval.lo < parsed.interval.hi);
          assert.ok(parsed.line.includes(`vs ${b}:`), "the line matched its own baseline");
        }
      }
    }
    assert.equal(parseSummary("M.A.P. vs garch: worse by 12.0% [+0.06284, +0.36219], n=175").verdict, "worse");
    assert.equal(parseSummary("M.A.P. vs x: indistinguishable at n=175, interval [-0.1, +0.2] spans zero").verdict, "neither");
    assert.equal(parseSummary("M.A.P. vs x: better by 3.0% [-0.2, -0.1]").verdict, "better");
    assert.equal(parseSummary("no interval here").interval, null);
  });

  itNeedsExport("takes the verdict from the sentence and not from the sign of the point", async () => {
    const { summaryFor } = await load("ui/results-baselines.js");
    const record = read(CLEAN);
    installDom();
    const source = await load("data/source.js");
    const stats = source.scoreStatistics(record.items);
    // CRPS against garch: the point is POSITIVE (+0.00075, M.A.P. worse) and the
    // interval spans zero, so the record says indistinguishable. A page reading
    // the sign would colour this as a loss.
    const parsed = summaryFor(record.summaries.crps, "garch");
    assert.ok(stats.map.crps - stats.baselines.garch.crps > 0);
    assert.equal(parsed.verdict, "neither");
    const row = byClass(ctx.roots.baselines, "res-row").find((r) => r.dataset.baseline === "garch");
    assert.equal(row.dataset.verdict, "neither");
  });

  itNeedsExport("prints each sentence verbatim", () => {
    const record = read(CLEAN);
    const said = byClass(ctx.roots.baselines, "res-row-said").map((n) => n.textContent);
    for (const line of [...record.summaries.crps, ...record.summaries["log score"]]) {
      assert.ok(said.includes(line), `the record's line is shown as written: ${line.slice(0, 40)}`);
    }
  });

  itNeedsExport("fixes one axis per rule across both bands", async () => {
    const { domainFor } = await load("ui/results-baselines.js");
    installDom();
    const source = await load("data/source.js");
    const both = [CLEAN, AMBIG].map((f) => {
      const record = read(f);
      return { stats: source.scoreStatistics(record.items), summaries: record.summaries };
    });
    assert.equal(domainFor(both, { key: "crps", field: "crps" }), 0.004);
    assert.equal(domainFor(both, { key: "log score", field: "log_score" }), 0.7);
    // One band alone must give the same axis, or switching would rescale.
    assert.equal(domainFor(both, { key: "crps", field: "crps" }), ctx.domains.crps);
  });
});

describe("the leakage control", () => {
  itNeedsExport("reproduces the published difference from the two records", async () => {
    installDom();
    const source = await load("data/source.js");
    const clean = source.scoreStatistics(read(CLEAN).items);
    const ambiguous = source.scoreStatistics(read(AMBIG).items);
    const { fmt } = await load("lib/format.js");
    const { PUBLISHED } = await load("ui/results-leakage.js");
    assert.equal(fmt.signed5(clean.map.crps - ambiguous.map.crps), PUBLISHED.difference);
    assert.equal(PUBLISHED.difference, "−0.00169");
    const check = byClass(ctx.roots.leakage, "res-leak-check")[0];
    assert.equal(check.dataset.agrees, "true");
    assert.match(check.textContent, /agrees with the published figure/);
  });

  itNeedsExport("shows its arithmetic and quotes the interval it cannot derive", () => {
    const working = byClass(ctx.roots.leakage, "res-leak-working")[0].textContent;
    assert.match(working, /0\.03179/);
    assert.match(working, /0\.03348/);
    const quoted = byClass(ctx.roots.leakage, "res-leak-quoted")[0].textContent;
    assert.match(quoted, /−0\.0093/, "the interval is in neither record and is quoted");
    // Neither record states this interval: it belongs to the comparison BETWEEN
    // the two files, not to anything inside either.
    for (const f of [CLEAN, AMBIG]) {
      const summaries = JSON.stringify(read(f).summaries);
      assert.ok(!/\[-?0\.0093/.test(summaries), `${f}'s summaries do not carry it`);
      assert.ok(!summaries.includes("0.0060]"), `${f}'s summaries do not carry it`);
    }
  });

  itNeedsExport("shows both bands whatever the switch says", async () => {
    const ambiguousView = await build({ band: "ambiguous" });
    for (const view of [ctx, ambiguousView]) {
      const text = view.roots.leakage.textContent;
      assert.match(text, /clean/);
      assert.match(text, /ambiguous/);
      assert.match(text, /0\.03179/);
      assert.match(text, /0\.03348/);
    }
  });
});

describe("the holdout panel", () => {
  itNeedsExport("renders the terms out of the spend record and nothing else", () => {
    const spend = read("scores/holdout_spend.json").at(-1);
    const text = ctx.roots.holdout.textContent;
    assert.match(text, /173/);
    assert.match(text, new RegExp(spend.calibration.fitted_on.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.match(text, /−0\.0757/, "a, with a real minus");
    assert.match(text, /1\.3305/);
    assert.match(text, /ADR 0032, amended by note record 3, amended by note record 7/);
    assert.match(text, /git note record 14 on ad71b13/);
  });

  itNeedsExport("states that no holdout score exists, and prints none", () => {
    const text = ctx.roots.holdout.textContent;
    assert.match(text, /none exist — never persisted, unrecoverable by design/);
    // Every number on the panel comes out of the spend record. Nothing from the
    // development records leaks in under a holdout heading.
    const spend = read("scores/holdout_spend.json").at(-1);
    const allowed = new Set([
      ...JSON.stringify(spend).match(/\d+(\.\d+)?/g),
      "710879a", "8", "2026",
    ]);
    for (const n of text.match(/\d+\.\d+/g) ?? []) {
      assert.ok(allowed.has(n) || allowed.has(n.replace(/^0/, "")), `${n} is not in the spend record`);
    }
    /* 175 DOES appear, inside `fitted_on`: the correction was fitted on the
       development half and the record says so. What must not appear is a
       development MEASUREMENT under a holdout heading. */
    assert.match(text, /clean\/dev, 175 items, log-score objective/);
    for (const forbidden of ["0.03179", "1.3786", "0.25193", "0.7331", "0.4891"]) {
      assert.ok(!text.includes(forbidden), `${forbidden} is a development figure and not the holdout's`);
    }
  });

  itNeedsExport("shows the rewritten commit as two rows, the record's and the published one", async () => {
    const { REWRITTEN } = await load("ui/results-holdout.js");
    const spend = read("scores/holdout_spend.json").at(-1);
    const recorded = spend.commit.slice(0, 7);
    assert.equal(recorded, "9cb1b84");
    assert.equal(REWRITTEN[recorded], "710879a");
    const text = ctx.roots.holdout.textContent;
    assert.match(text, /710879a in published history/);
    assert.match(text, /9cb1b84, replaced by the 8 September rebase/);
    // The record is not edited: the original is still shown as what was stored.
    assert.equal(spend.commit, "9cb1b84f21726a82d211b9c7b62b2ada2abd1e41");
  });

  itNeedsExport("falls back to the recorded commit alone when the table does not know it", async () => {
    installDom();
    const { renderHoldout } = await load("ui/results-holdout.js");
    const spend = read("scores/holdout_spend.json").at(-1);
    const root = new Node("section");
    renderHoldout(root, { holdout: { spend: { ...spend, commit: "deadbee" + "f".repeat(33) }, spends: 1 }, pending: "…" });
    assert.match(root.textContent, /deadbee/);
    assert.ok(!root.textContent.includes("published history"), "no successor is invented");
  });
});

/* NO EXPORT NEEDED. `ui/assets/export/` is generated and gitignored, so a fresh
   clone has none — and since the front end merged into M.A.P., a fresh clone is
   expected to pass both suites. These assertions read the checked-in files only. */
describe("the page, its nav and its files", () => {
  it("adds results to the nav on every screen", async () => {
    installDom();
    const { mountMastheadNav } = await load("ui/front-door.js");
    const host = new Node("div");
    const nav = mountMastheadNav(host, { current: "results" });
    assert.deepEqual(
      nav.children.map((c) => c.textContent),
      ["find a company", "runs", "results", "live analysis"],
    );
    assert.equal(nav.children.filter((c) => c.attrs["aria-current"]).length, 1);
    // Results is third now that live analysis sits last: it is the only screen
    // that makes something rather than reading it, so it goes at the end.
    assert.equal(nav.children[2].attrs["aria-current"], "page");
    for (const page of ["index.html", "company.html", "runs.html", "results.html", "analyse.html"]) {
      assert.match(file(page), /<div id="masthead-nav"><\/div>/, `${page} has a nav host`);
    }
  });

  it("gives every section the page mounts a host", () => {
    const html = file("results.html");
    /* `res-identity`, not `identity`: company.css caps that id at the prose
       measure and this page loads it, which held the head 236px short of the
       chart grid. The runs screen hit the same collision and was renamed for the
       same reason. */
    for (const id of ["res-identity", "pit", "baselines", "leakage", "direction", "holdout", "status", "disclosure", "legend", "footer", "masthead-nav"]) {
      assert.match(html, new RegExp(`id="${id}"`), `results.html has #${id}`);
    }
    assert.match(html, /assets\/js\/results-page\.js/);
    assert.match(html, /assets\/styles\/results\.css/);
  });

  it("formats signed decimals with a real minus sign", async () => {
    const { fmt } = await load("lib/format.js");
    assert.equal(fmt.signed5(0.0016308), "+0.00163");
    assert.equal(fmt.signed5(-0.0010039), "−0.00100");
    assert.equal(fmt.dec4(-1.378592), "−1.3786");
    assert.equal(fmt.dec5(0.031793), "0.03179");
    // A hyphen is not a minus, and the column these sit in is read by sign.
    assert.ok(!fmt.signed5(-0.001).includes("-"));
    // A difference that rounds away is not a direction.
    assert.equal(fmt.signed4(-1e-9), "0.0000");
  });

  it("keeps the log score's orientation guard, and keeps it out of amber", () => {
    /* The guard is the SENTENCE "stored lower-is-better", not a colour. It used
       to be amber, which put a fourth meaning on a token that should carry one;
       amber now means "not a settled measurement" everywhere and an instruction
       about reading an axis is not that. The tag is still boxed and still the
       brightest ink on the block, so it is still the thing the eye lands on. */
    const guard = file("assets/styles/results.css").match(/\.res-rule-tag--guard \{[^}]*\}/)[0];
    assert.doesNotMatch(guard, /--uncal/, "the orientation guard is not an alarm state");
    assert.match(guard, /--ink-num/, "it is still the brightest thing in the block");
    assert.match(guard, /border/, "and still boxed, so it reads as a tag");
  });

  it("jitters deterministically", async () => {
    const { jitter } = await load("ui/results-direction.js");
    assert.equal(jitter(7), jitter(7));
    // 101 residues, rounded into the 75 integer rows the strip is tall.
    assert.equal(new Set(Array.from({ length: 101 }, (_, i) => (i * 7919) % 101)).size, 101);
    const spread = new Set(Array.from({ length: 101 }, (_, i) => Math.round(jitter(i))));
    assert.ok(spread.size > 60, "a prime step through a prime modulus spreads");
    for (let i = 0; i < 200; i += 1) assert.ok(jitter(i) >= 4 && jitter(i) <= 78);
  });
});

describe("the rendered page", () => {
  itNeedsExport("states the log score's orientation where it can be misread", () => {
    const text = ctx.roots.baselines.textContent;
    assert.match(text, /stored lower-is-better/);
    assert.match(text, /M\.A\.P\. worse →/);
  });

  itNeedsExport("never uses 779 or 709 as a denominator, and names 779 only to refuse it", () => {
    for (const [name, root] of Object.entries(ctx.roots)) {
      if (name === "disclosure") continue;
      for (const wrong of ["779", "709"]) {
        assert.ok(!root.textContent.includes(wrong), `${name} prints ${wrong}, which is not a denominator here`);
      }
    }
    // The one place it appears is the block that exists to say it is not one.
    const why = ctx.roots.disclosure.textContent;
    assert.match(why, /779 runs[^.]*not the denominator/);
    assert.ok(!why.includes("709"), "items_settled belongs to the runs screen");
  });

  itNeedsExport("writes the two band-specific disclosure blocks from the record on screen", async () => {
    const ambiguous = await build({ band: "ambiguous" });
    const cleanText = ctx.roots.disclosure.textContent;
    const ambigText = ambiguous.roots.disclosure.textContent;

    // The clean band's two z definitions disagree at 2.5; the ambiguous band's
    // agree there and disagree at 3. One fixed sentence cannot state both.
    assert.match(cleanText, /On the clean band it gives 11 over 2\.5 and 7 over 3/);
    assert.match(cleanText, /ignores the centre and gives 13 and 7 on the same items/);
    assert.match(ambigText, /On the ambiguous band it gives 11 over 2\.5 and 8 over 3/);
    assert.match(ambigText, /ignores the centre and gives 11 and 6 on the same items/);

    assert.match(cleanText, /−1\.3786 against the random walk's −1\.5826/);
    assert.match(ambigText, /−1\.2332 against the random walk's −1\.5214/);
    assert.ok(!ambigText.includes("−1.3786"), "the clean band's mean is not quoted under the ambiguous one");
  });

});
