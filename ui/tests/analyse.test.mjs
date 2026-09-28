/* The live-analysis screen — ADR 0036 §1 and §4.

   The load-bearing property is that a fan cannot reach the screen without its
   marking. That is asserted as a refusal rather than as a rendering detail: if a
   later change drops the marking, `renderFan` throws instead of drawing a fan
   that looks settled. */

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { describe, it } from "node:test";

/* A local DOM stub, as company, runs, results and front-door each keep one.
   Four copies is a smell, but a fifth convention would be worse than a fifth
   copy: these tests are the thing that has to stay readable. */
class Node {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.children = []; this.dataset = {}; this.style = {}; this.attrs = {};
    this._cls = new Set(); this._text = ""; this.parentElement = null;
    this.classList = { add: (c) => this._cls.add(c), remove: (c) => this._cls.delete(c) };
  }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._cls].join(" "); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this._text + this.children.map((c) => (c.nodeType === 3 ? c.data : c.textContent)).join("");
  }
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
  closest() { return null; }
}

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
}

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const load = (path) => import(`../assets/js/${path}?${Math.random()}`);

const RESULT = {
  event: "result",
  run_id: "r-1",
  ticker: "AAPL",
  anchor: "2026-09-22",
  spot: 200,
  horizon_days: 5,
  filed: "2026-09-21",
  accession: "0000320193-26-000077",
  scenarios: [
    { name: "bullish", weight: 0.25, price_return: 0.06, annualised_vol: 0.34 },
    { name: "base_case", weight: 0.5, price_return: 0.01, annualised_vol: 0.28 },
    { name: "bearish", weight: 0.25, price_return: -0.05, annualised_vol: 0.41 },
  ],
  marking: "settled",
  corrected: true,
  reasons: [],
  correction: { a: -0.0757, b: 1.3305, form: "z -> (z - a) / b" },
};

const amber = () => ({
  ...RESULT,
  marking: "uncalibrated",
  corrected: false,
  reasons: ["horizon is 21 sessions; the correction was fitted at 5 and at no other"],
});

describe("a fan cannot be drawn without its marking", () => {
  it("refuses a result that carries none", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    const { marking, ...unmarked } = RESULT;
    assert.throws(() => renderFan(host, unmarked), /without its marking/);
    assert.throws(() => renderFan(host, null), /without its marking/);
    assert.equal(host.children.length, 0, "nothing was drawn");
  });

  it("puts the marking on the figure itself, so a screenshot carries it", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const settled = renderFan(new Node("div"), RESULT);
    assert.equal(settled.dataset.calibration, "settled");
    const raw = renderFan(new Node("div"), amber());
    assert.equal(raw.dataset.calibration, "uncalibrated");
  });
});

describe("the scenarios are read the way the export states them", () => {
  it("treats price_return as a SIMPLE return, not a log one", async () => {
    /* `format.js` keeps two helpers apart for this: `spot * exp(r)` is invisible
       below about 4% and then diverges one-directionally, which looks like a
       plausible price at every magnitude. At +6% on a spot of 200 the two give
       212.00 and 212.37. */
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, RESULT);
    const text = host.textContent;
    assert.match(text, /212\.00/, "simple return: 200 * (1 + 0.06)");
    assert.doesNotMatch(text, /212\.37/, "log return would give this");
  });

  it("reports every scenario with its weight", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, RESULT);
    for (const label of ["Bullish", "Base case", "Bearish"]) {
      assert.ok(host.textContent.includes(label), label);
    }
    assert.match(host.textContent, /50%/, "the base case's weight");
  });
});

describe("the marking says which state it is and why", () => {
  it("names the three conditions when the correction was applied", async () => {
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderMarking(host, RESULT);
    assert.match(host.textContent, /Corrected fan/);
    assert.match(host.textContent, /five sessions/);
    assert.match(host.textContent, /within one trading day/);
  });

  it("still refuses the word calibrated on a corrected fan", async () => {
    /* ADR 0036's consequence: the company is outside the frozen corpus, so the
       three conditions make applying the correction defensible, not verified. */
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderMarking(host, RESULT);
    assert.match(host.textContent, /not a calibrated fan/i);
    assert.match(host.textContent, /defensible, not verified/);
  });

  it("prints every failing reason rather than summarising them", async () => {
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    const result = amber();
    result.reasons = ["horizon is 21 sessions", "the corpus filters would reject this company: illiquid"];
    renderMarking(host, result);
    for (const reason of result.reasons) assert.ok(host.textContent.includes(reason), reason);
  });

  it("says a raw fan is the one measured too narrow", async () => {
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderMarking(host, amber());
    assert.match(host.textContent, /measured too narrow/);
  });
});

describe("the page, its markup and its rules", () => {
  it("marks the uncalibrated horizons on the control, before anything runs", () => {
    /* A reader choosing 21 sessions should know it is uncalibrated while
       choosing it, not discover it from a result seven minutes later. In the
       shared module, so every screen that offers a run marks them identically. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /days: 10, label: "10 sessions", note: "uncalibrated"/);
    assert.match(offer, /days: 21, label: "21 sessions", note: "uncalibrated"/);
    assert.match(offer, /days: 5, label: "5 sessions", note: "the fitted horizon"/);
    assert.match(offer, /note\.dataset\.calibration = "uncalibrated"/);
  });

  it("states one absence rather than disabling a control per row", () => {
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /No analysis server/);
    assert.match(offer, /nothing is pending/);
    // Nowhere, on any screen that can offer a run.
    for (const file of ["analyse-page.js", "search-page.js", "ui/analyse-offer.js", "ui/search-box.js"]) {
      assert.doesNotMatch(read(`assets/js/${file}`), /\.disabled = true/, file);
    }
  });

  it("gives every screen the same absence, in the same words", () => {
    /* One module, so the three screens that can offer a run cannot drift into
       three different explanations of the same missing thing. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.equal((offer.match(/No analysis server/g) ?? []).length, 1);
    for (const file of ["analyse-page.js", "search-page.js"]) {
      assert.match(read(`assets/js/${file}`), /renderNoServer\(/, file);
      assert.doesNotMatch(read(`assets/js/${file}`), /No analysis server/, file);
    }
  });

  it("asks whether a server is there without being able to start a run", () => {
    // `health` with GET. A speculative POST would cost seven minutes to find out.
    const offer = read("assets/js/ui/analyse-offer.js");
    const body = offer.slice(offer.indexOf("export function serverPresent()"));
    assert.match(body.slice(0, 300), /fetch\("health", \{ method: "GET" \}\)/);
  });

  it("probes once per page, not once per row", () => {
    /* A screen with forty readable rows must ask once. A row is never the thing
       that decides whether the feature exists. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /probe \?\?= fetch/);
    assert.match(read("assets/js/search-page.js"), /state\.canAnalyse = await serverPresent\(\)/);
    assert.doesNotMatch(read("assets/js/ui/search-box.js"), /serverPresent/);
  });

  it("hands a ticker over as a link rather than posting from the row", () => {
    /* The run belongs to the screen built to show one. Starting seven minutes of
       work from a search row would leave the reader with nowhere to put it. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /link\.href = `analyse\.html\?ticker=/);
    assert.doesNotMatch(offer, /method: "POST"/);
  });

  it("seeds an arriving ticker without starting a run", () => {
    const page = read("assets/js/analyse-page.js");
    const boot = page.slice(page.indexOf("async function boot()"));
    assert.match(boot, /params\.get\("ticker"\)/);
    assert.match(boot, /\.anl-input"\)\.value = seeded/);
    // The seeded value fills the box; nothing calls analyse() from boot.
    assert.doesNotMatch(boot, /analyse\(seeded/);
  });

  it("reads the stream as it arrives rather than buffering it", () => {
    /* Buffering would turn a six-minute progress display into a six-minute
       blank, which is the whole reason the response is newline-delimited. */
    const page = read("assets/js/analyse-page.js");
    assert.match(page, /getReader\(\)/);
    assert.match(page, /TextDecoder/);
    assert.doesNotMatch(page, /await response\.text\(\)/);
  });

  it("has a host for every section the module fills", () => {
    const html = read("analyse.html");
    for (const id of ["ground", "masthead-nav", "masthead-vintage", "ask", "progress", "result", "why", "footer"]) {
      assert.match(html, new RegExp(`id="${id}"`), id);
    }
    assert.match(html, /analyse\.css/);
  });

  it("keeps amber to the one meaning, in this stylesheet too", () => {
    // The same discipline the company screen pins, applied to the new sheet.
    const sheet = read("assets/styles/analyse.css").replace(/\/\*[\s\S]*?\*\//g, "");
    const amberRules = sheet
      .split("}")
      .filter((block) => /var\(--uncal/.test(block))
      .map((block) => block.split("{")[0].trim());
    assert.ok(amberRules.length >= 3, "the sheet does use amber");
    for (const selector of amberRules) {
      assert.match(selector, /data-calibration="uncalibrated"/, selector);
    }
  });

  it("is listed in the nav on every screen", () => {
    for (const page of readdirSync(new URL("../", import.meta.url)).filter((f) => f.endsWith(".html"))) {
      assert.match(read(page), /<div id="masthead-nav"><\/div>/, page);
    }
  });
});
