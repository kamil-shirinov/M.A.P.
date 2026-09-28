/* The front door: the mode controller, the strip, and the wiring that has to
   sit in a particular place for either to work.

   The browser-only behaviour — a view transition actually morphing, reduced
   motion actually applying — was verified in Chromium and cannot be observed
   from Node. What is tested here is what those checks depend on: the flip is
   synchronous without the API, focus moves inside the flip with it, the call
   sites are where the verification found they have to be, and the CSS still
   carries the rules the verification read. */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { HAVE_EXPORT, itNeedsExport } from "./needs-export.mjs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const EXPORT = new URL("../assets/export/", import.meta.url);
const HAVE = existsSync(new URL("manifest.json", EXPORT));

/** The body of a top-level function, by its declaration line. */
function bodyOf(source, declaration) {
  const start = source.indexOf(declaration);
  assert.notEqual(start, -1, `${declaration} not found`);
  const end = source.indexOf("\n}\n", start);
  return source.slice(start, end);
}

/** The declarations of every rule whose selector list includes `selector`. */
function rulesFor(css, selector) {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("}")
    .map((block) => block.split("{"))
    .filter(([sel]) => sel?.split(",").some((s) => s.trim() === selector))
    .map(([, decls]) => decls ?? "");
}

/* ---- a document just large enough for the controller ---- */
function stubDocument({ api }) {
  const doc = { body: { dataset: { mode: "door" } }, activeElement: null, pending: [], started: 0 };
  const input = (name) => ({
    name,
    value: "",
    caret: null,
    focus() { doc.activeElement = this; },
    setSelectionRange(a, b) { this.caret = [a, b]; },
  });
  doc.door = input("door");
  doc.page = input("page");
  if (api) {
    doc.startViewTransition = (update) => { doc.started++; doc.pending.push(update); return {}; };
  }
  globalThis.document = doc;
  return doc;
}

const { createModeController, mountDoor } = await import("../assets/js/ui/front-door.js");

describe("mode controller", () => {
  it("swaps instantly, and does not throw, where the View Transition API is missing", () => {
    const doc = stubDocument({ api: false });
    const mode = createModeController({ doorInput: doc.door, pageInput: doc.page });
    doc.door.focus();
    doc.door.value = "T";
    assert.equal(mode.sync("T"), "open");
    assert.equal(doc.body.dataset.mode, "open", "flipped synchronously");
    assert.equal(doc.activeElement, doc.page);
    assert.deepEqual(doc.page.caret, [1, 1]);
    assert.equal(mode.sync(""), "door");
    assert.equal(doc.body.dataset.mode, "door");
    assert.equal(doc.activeElement, doc.door);
  });

  it("moves focus inside the flip, carrying a keystroke that arrived after the last paint", () => {
    // Typed at 60 ms a key, "TSLA" arrived as "TSA" when focus waited for the
    // transition's `ready`: the L landed on <body> while the door box was hidden.
    const doc = stubDocument({ api: true });
    const mode = createModeController({ doorInput: doc.door, pageInput: doc.page });
    doc.door.focus();
    doc.door.value = "TS";
    mode.sync("TS");
    assert.equal(doc.body.dataset.mode, "door", "the flip waits for the transition's update callback");
    doc.door.value = "TSL"; // typed before the callback ran
    doc.pending.shift()();
    assert.equal(doc.body.dataset.mode, "open");
    assert.equal(doc.activeElement, doc.page);
    assert.equal(doc.page.value, "TSL");
    assert.deepEqual(doc.page.caret, [3, 3]);
  });

  it("starts no transition when the mode does not change", () => {
    const doc = stubDocument({ api: true });
    const mode = createModeController({ doorInput: doc.door, pageInput: doc.page });
    mode.sync("");
    mode.sync("   ");
    assert.equal(doc.started, 0);
  });

  it("focuses the box the current mode shows", () => {
    const doc = stubDocument({ api: true });
    const mode = createModeController({ doorInput: doc.door, pageInput: doc.page });
    mode.focus();
    assert.equal(doc.activeElement, doc.door, "the page's box is display:none at the door");
  });

  it("has no way home that bypasses the query handler", () => {
    const doc = stubDocument({ api: false });
    const mode = createModeController({ doorInput: doc.door, pageInput: doc.page });
    assert.equal(mode.toDoor, undefined);
  });
});

describe("the door's strip", () => {
  const exported = (name) => JSON.parse(readFileSync(new URL(name, EXPORT), "utf8"));

  /** Mount the door into a stub tree and return its strip's parts. */
  function strip(options) {
    class Node {
      constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this._text = ""; this.parentElement = null; }
      set textContent(v) { this._text = String(v); this.children = []; }
      get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
      setAttribute() {}
      addEventListener() {}
      append(...kids) { for (const k of kids) { k.parentElement = this; this.children.push(k); } }
    }
    const block = new Node("div");
    const host = new Node("section");
    host.querySelector = (sel) => (sel === ".door-block" ? block : null);
    globalThis.document = { createElement: (t) => new Node(t) };
    mountDoor(host, { onQuery: () => {}, ...options });
    const node = host.children.find((c) => c.className === "door-strip");
    return { node, block, parts: node.children.map((c) => c.textContent) };
  }

  itNeedsExport("counts runs from the manifest's four counts, summed on the page and marked derived", async () => {
    const source = await import("../assets/js/data/source.js");
    const manifest = exported("manifest.json");
    const companies = exported("universe.json").length;
    const runsBySource = source.runCountsBySource(manifest);
    const { node, block, parts } = strip({ companies, runsBySource, finding: source.devScoringRecordExported(manifest) });

    const rowsInFiles = source.SOURCES.reduce((n, s) => n + exported(`runs/by_source/${s}.json`).length, 0);
    /* Computed from the export rather than written down, because the strip gains
       a clause when any run is outside the corpus — and whether one is depends on
       whether `map serve` has been used. A hardcoded list would pass on a clean
       checkout and fail the first time someone ran a live analysis. */
    const outside = ["edgar", "news"].reduce((n, s) => n + exported(`runs/by_source/${s}.json`).length, 0);
    assert.deepEqual(parts, [
      String(companies), " companies", "·",
      // The run count is one part now: a link to the screen it names.
      `${rowsInFiles.toLocaleString("en-US")} runs recorded`,
      // Two parts: the figure is marked and the label is chrome, as everywhere else.
      ...(outside ? ["·", outside.toLocaleString("en-US"), " outside the corpus"] : []),
      "·",
      "does not beat a plain random walk or GARCH on the development companies",
    ]);
    const [companyFig, , , runLink] = node.children;
    assert.equal(companyFig.dataset.prov, "derived");
    assert.equal(runLink.href, "runs.html", "the count is the way in to the runs screen");
    const runFig = runLink.children[0];
    assert.equal(runFig.dataset.prov, "derived", "a sum of four read counts is computed here, not read");
    /* Every part carries its own account of itself: a figure with a provenance,
       chrome saying why it holds digits, a separator, or the link. Checked by
       KIND rather than by index, which was hardcoded to 0 and 3 and broke the
       moment the strip gained a fifth part. */
    for (const [i, child] of node.children.entries()) {
      assert.ok(
        child.dataset.prov !== undefined
          || child.dataset.chrome !== undefined
          || child.className === "door-dot"
          || child.className === "door-runs",
        `part ${i} is marked`,
      );
    }
    assert.ok(block.children.some((c) => c.className === "door-box"), "the box goes into the static block");
  });

  itNeedsExport("adds all four populations, not whichever one holds the runs today", async () => {
    // Every real run is `unknown`, so the export alone cannot tell a sum from a read.
    const { figure } = await import("../assets/js/lib/figure.js");
    const runsBySource = { corpus: 2, edgar: 1, news: 0, unknown: 4 };
    for (const k of Object.keys(runsBySource)) runsBySource[k] = figure(runsBySource[k], "measured", "int");
    const { parts } = strip({ companies: 120, runsBySource, finding: false });
    assert.equal(parts[3], "7 runs recorded");
  });

  itNeedsExport("states a missing run count instead of reading an old export as zero", async () => {
    const source = await import("../assets/js/data/source.js");
    const { runs, ...older } = exported("manifest.json");
    const { parts, node } = strip({ companies: 120, runsBySource: source.runCountsBySource(older), finding: false });
    assert.deepEqual(parts, ["120", " companies", "·", "runs not counted"]);
    assert.match(node.children[3].dataset.chrome, /predates runs\.rows/);
  });

  itNeedsExport("makes no claim about baselines when the export carries no development record", async () => {
    const source = await import("../assets/js/data/source.js");
    const manifest = { ...exported("manifest.json"), scores: { records: [], absent: [] } };
    assert.equal(source.devScoringRecordExported(manifest), false);
    const { parts } = strip({ companies: 120, runsBySource: source.runCountsBySource(manifest), finding: false });
    assert.ok(!parts.some((p) => /random walk|GARCH/.test(p)));
  });

  itNeedsExport("is still true of every development record the export carries", () => {
    // The finding is prose, so a re-export cannot update it. This is what fails
    // if a later development pass beats either baseline on either rule.
    const records = exported("manifest.json").scores.records.filter((r) => r.split === "dev");
    assert.ok(records.length > 0, "the finding needs a development record under it");
    for (const { file } of records) {
      const { summaries } = exported(file);
      for (const rule of ["crps", "log score"]) {
        for (const baseline of ["random_walk", "garch"]) {
          const line = summaries[rule].find((l) => l.startsWith(`M.A.P. vs ${baseline}:`));
          assert.ok(line, `${file}: no ${rule} comparison against ${baseline}`);
          assert.match(line, /: (worse by|indistinguishable at)/, `${file}: ${line}`);
        }
      }
    }
  });
});

describe("wiring in search-page.js", () => {
  const page = read("assets/js/search-page.js");

  it("flips the mode as the last thing a paint does", () => {
    const lines = bodyOf(page, "function paint()").split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("/*") && !l.startsWith("*") && !l.startsWith("//"));
    assert.equal(lines.at(-1), "mode.sync(state.query);");
    const body = bodyOf(page, "function paint()");
    assert.ok(body.indexOf("renderResults(") < body.indexOf("mode.sync("), "after the rows are in the DOM");
  });

  it("does not flip from the query handler, where an early return skips it", () => {
    assert.doesNotMatch(bodyOf(page, "async function onQuery("), /mode\.sync/);
  });

  it("does not make a keystroke wait for the index", () => {
    assert.doesNotMatch(bodyOf(page, "async function onQuery("), /searchSymbols/);
    assert.match(bodyOf(page, "function requestIndex()"), /onQuery\(state\.query\)/);
  });

  it("goes home through onQuery, so a query in flight cannot reopen the page", () => {
    const handler = page.slice(page.indexOf('querySelector(".masthead h1 a")'));
    assert.match(handler.slice(0, handler.indexOf("});")), /onQuery\(""\)/);
  });

  it("shows the no-export state instead of hiding it behind the door", () => {
    const branch = page.slice(page.indexOf("exportState.state === source.NO_EXPORT"), page.indexOf("state.corpus = companies.rows"));
    assert.match(branch, /document\.body\.dataset\.mode = "open"/);
  });

  it("focuses the door's box at boot, not the page's hidden one", () => {
    const boot = bodyOf(page, "async function boot()");
    assert.match(boot, /mode\.focus\(\)/);
    assert.doesNotMatch(boot, /box\.focus\(\)/);
  });

  it("keeps the query in the URL, and writes it from paint", () => {
    // The URL is part of the screen, so it is written where the screen is.
    const body = bodyOf(page, "function paint()");
    assert.match(body, /writeQueryToLocation\(state\.query\)/);
    assert.doesNotMatch(bodyOf(page, "async function onQuery("), /writeQueryToLocation/);
    // The URL is not rendered, so it is not in the transition's snapshot and the
    // flip stays last. Written after the rows, though: paint is one unit.
    assert.ok(body.indexOf("renderResults(") < body.indexOf("writeQueryToLocation("));
    assert.ok(body.indexOf("writeQueryToLocation(") < body.indexOf("mode.sync("));
  });

  it("replaces on a keystroke and pushes only for the crest", () => {
    // One entry per letter would bury the page you arrived from.
    const write = bodyOf(page, "function writeQueryToLocation(");
    assert.match(write, /if \(push\) window\.history\.pushState/);
    assert.match(write, /else window\.history\.replaceState/);
    assert.match(bodyOf(page, "function paint()"), /writeQueryToLocation\(state\.query\);/);
    const handler = page.slice(page.indexOf('querySelector(".masthead h1 a")'));
    const body = handler.slice(0, handler.indexOf("});"));
    assert.match(body, /pushQueryToLocation\(""\)/);
    // Pushed BEFORE the repaint, or Back returns to the empty box it replaced.
    assert.ok(body.indexOf("pushQueryToLocation") < body.indexOf('onQuery("")'));
  });

  it("does not push an identical URL", () => {
    assert.match(bodyOf(page, "function writeQueryToLocation("), /if \(next === window\.location/);
  });

  it("re-reads the URL on back and forward, through onQuery", () => {
    const boot = bodyOf(page, "async function boot()");
    assert.match(boot, /addEventListener\("popstate"/);
    const listener = boot.slice(boot.indexOf('addEventListener("popstate"'));
    assert.match(listener.slice(0, 200), /onQuery\(queryFromLocation\(\)\)/);
  });

  it("seeds an arriving ?q= through onQuery, so the index is still requested", () => {
    const boot = bodyOf(page, "async function boot()");
    assert.match(boot, /const seeded = queryFromLocation\(\)/);
    assert.match(boot, /await onQuery\(seeded\)/);
    // And the plain arrival still paints, or the door would never render.
    assert.match(boot, /\} else \{\s*paint\(\);\s*\}/);
  });

  it("survives an engine with no history or no parseable URL", () => {
    // These files open over file:// as well as over http, and the tests drive the
    // module with a stub document. Neither may have history.
    assert.match(bodyOf(page, "function writeQueryToLocation("), /if \(!window\.history\?\.replaceState\) return/);
    assert.match(bodyOf(page, "function queryFromLocation()"), /catch \{/);
  });
});

describe("masthead nav", () => {
  it("offers four sections and never a company", async () => {
    const doc = stubDocument({ api: false });
    const { mountMastheadNav } = await import("../assets/js/ui/front-door.js");
    const host = { children: [], append(...k) { this.children.push(...k); } };
    doc.createElement = (t) => {
      const n = { tagName: t, children: [], dataset: {}, _cls: new Set(), attrs: {},
        set className(v) { this._cls = new Set(String(v).split(/\s+/)); },
        get className() { return [...this._cls].join(" "); },
        set textContent(v) { this._text = String(v); },
        get textContent() { return (this._text ?? "") + this.children.map((c) => c.textContent ?? "").join(""); },
        setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {},
        append(...k) { this.children.push(...k); } };
      return n;
    };
    const nav = mountMastheadNav(host, { current: "search" });
    const labels = nav.children.map((c) => c.textContent);
    assert.deepEqual(labels, ["find a company", "runs", "results", "live analysis"]);
    assert.ok(!labels.some((l) => /company$/.test(l) && l !== "find a company"));
    // A detail page marks neither section rather than inventing a third.
    const none = mountMastheadNav(host, { current: null });
    assert.equal(none.children.filter((c) => c.attrs["aria-current"]).length, 0);
    for (const current of ["search", "runs", "results", "analyse"]) {
      assert.equal(mountMastheadNav(host, { current }).children.filter((c) => c.attrs["aria-current"]).length, 1, `${current} marks itself`);
    }
  });

  it("mounts on every screen that is a section, and not at the door", () => {
    for (const page of ["index.html", "company.html", "runs.html", "results.html"]) {
      assert.match(read(page), /<div id="masthead-nav"><\/div>/, `${page} has a nav host`);
    }
    // The door hides the masthead entirely, which is what keeps it nav-free.
    assert.match(read("assets/styles/front-door.css"), /body\[data-mode="door"\][^{]*\.masthead/);
  });
});

describe("front-door.css and the two documents", () => {
  const css = read("assets/styles/front-door.css");
  const index = read("index.html");
  const company = read("company.html");

  it("opts in to cross-document transitions on both pages", () => {
    assert.match(css, /@view-transition\s*\{\s*navigation:\s*auto;\s*\}/);
    for (const html of [index, company]) {
      assert.match(html, /<link rel="stylesheet" href="assets\/styles\/front-door\.css">/);
      assert.match(html, /<h1><a href="index\.html"[^>]*>M\.A\.P\.<\/a><\/h1>/);
    }
  });

  it("has the door's crest in the markup, where the first rendered frame can see it", () => {
    const door = index.slice(index.indexOf('<section class="door"'), index.indexOf("</section>"));
    assert.match(door, /<h1>M\.A\.P\.<\/h1>/);
    assert.match(css, /\.door-crest h1,\s*\n\.masthead h1 a \{ view-transition-name: map-crest; \}/);
  });

  it("turns off all three motions under reduced motion", () => {
    const block = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    assert.match(block, /\[data-band\] \{ animation: none;/);
    assert.match(block, /\.ground \{ transition: none; \}/);
    assert.match(block, /::view-transition-group\(\*\),\s*::view-transition-old\(\*\),\s*::view-transition-new\(\*\) \{ animation-duration: 1ms !important; \}/);
  });

  it("puts the ground behind the page rather than level with it", () => {
    assert.match(rulesFor(css, ".ground")[0], /z-index: -1;/);
  });

  it("sets the nav on tokens, and marks the current screen with a rule", () => {
    /* The nav moved to system.css as `.nav` when the four screens took the
       door's voice. Two of the old assertions survive the move and one does not:
       spacing is still tokens, and the shared voice is now deliberately tracked,
       because tracking is what makes a mono line at --step--1 read as
       navigation rather than as a stamp. */
    const system = read("assets/styles/system.css");
    assert.equal(rulesFor(css, ".masthead-nav").length, 0, "the old class is gone, not merely unused");

    for (const sel of [".nav", ".nav a"]) {
      for (const decls of rulesFor(system, sel)) {
        // Spacing only: a 1px hairline is the shipped border everywhere, and has no token.
        assert.doesNotMatch(decls, /(gap|padding|margin)[\w-]*:[^;]*\d+px/, `${sel} spaces in pixels`);
      }
    }
    assert.match(rulesFor(system, ".nav")[0], /gap: var\(--sp-6\);/);

    /* The invariant that matters: the current screen is marked by a RULE, so it
       is still marked in greyscale and in a screenshot with the colour stripped.
       Colour on top of it is reinforcement. */
    const current = rulesFor(system, '.nav a[aria-current="page"]::after')[0];
    assert.match(current, /transform: scaleX\(1\)/, "the indicator is drawn, not coloured in");
  });

  it("keeps the masthead crest on the left edge the sections start on", () => {
    for (const decls of rulesFor(css, ".masthead h1")) assert.doesNotMatch(decls, /text-indent/);
  });
});

describe("the ground drifts, on every screen", () => {
  const module = read("assets/js/ui/rosette.js");
  const doorCss = read("assets/styles/front-door.css");
  const systemCss = read("assets/styles/system.css");

  it("mounts a drifting figure, because every screen mounts through one helper", () => {
    /* The regression this exists for: `mountPageRosette` forced `drift: false`
       and all four pages go through it, so nothing in the app ever mounted a
       drifting rosette and front-door.css's keyframes were unreachable. The door
       looked still because it was. */
    const helper = bodyOf(module, "export function mountPageRosette(");
    assert.doesNotMatch(helper, /drift:\s*false/);
    assert.match(helper, /opacity: 0\.35/);
  });

  it("never leaves a band on a value no rule animates", () => {
    // A band built without drift is `data-band="static"`, and nothing styles it.
    const produced = [...module.matchAll(/"data-band":\s*([^)]+)\)/g)].join(" ");
    assert.match(produced, /o\.drift \? name : "static"/);
    for (const css of [doorCss, systemCss]) {
      assert.doesNotMatch(css, /\[data-band="static"\]/);
    }
    // So the app must not build one. Checked at the only call site of the option.
    for (const page of ["search-page.js", "company.js", "runs-page.js", "results-page.js"]) {
      assert.doesNotMatch(read(`assets/js/${page}`), /drift:\s*false/);
    }
  });

  it("drifts linearly, so the motion is visible rather than eased into nothing", () => {
    /* ease-in-out over 34s moves band a 0.02 of its 14 degrees in the first
       second. That is the defect, not the duration. */
    for (const band of ["a", "b", "c"]) {
      assert.match(doorCss, new RegExp(`\\[data-band="${band}"\\][^}]*animation: rosette-${band} \\d+s linear`));
      assert.match(systemCss, new RegExp(`\\[data-band="${band}"\\][^}]*animation: rosette-page-${band} \\d+s linear`));
    }
    assert.doesNotMatch(doorCss, /animation: rosette-[abc] \d+s ease/);
  });

  it("starts the three bands at different phases", () => {
    // All three at an endpoint together is the one moment the relative angle is
    // not changing, and it was the moment the page loaded.
    const delays = [...doorCss.matchAll(/animation: rosette-[abc] \d+s linear (-\d+)s/g)].map((m) => m[1]);
    assert.equal(delays.length, 3);
    assert.equal(new Set(delays).size, 3);
    const pageDelays = [...systemCss.matchAll(/animation: rosette-page-[abc] \d+s linear (-\d+)s/g)].map((m) => m[1]);
    assert.equal(new Set(pageDelays).size, 3);
  });

  it("swings less behind a page than behind the door", () => {
    const deg = (css, name) => {
      const block = css.slice(css.indexOf(`@keyframes ${name} `));
      return Math.abs(Number(block.match(/rotate\((-?[\d.]+)deg\)/)[1]));
    };
    for (const band of ["a", "b", "c"]) {
      assert.ok(deg(systemCss, `rosette-page-${band}`) < deg(doorCss, `rosette-${band}`),
        `page band ${band} should swing less than the door's`);
    }
  });

  it("stops entirely under reduced motion, rather than holding a rotated frame", () => {
    const reduce = systemCss.slice(systemCss.indexOf("@media (prefers-reduced-motion: reduce)"));
    assert.match(reduce, /\[data-band\] \{ animation: none !important;/);
    // And the layer hint goes with it: a figure that never moves should not hold
    // a compositor layer for the life of the page.
    assert.match(reduce, /\[data-band\][^}]*will-change: auto !important/);
  });
});

describe("motion is on one curve and never shifts the layout", () => {
  const SHEETS = ["tokens", "system", "base", "components", "front-door", "search", "results", "runs", "company"];
  /* Comments come out first. They quote declarations in prose — "`animation:
     ... both` applies its FROM state" — and a scan that reads them is testing the
     commentary rather than the stylesheet. */
  const bare = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
  const css = Object.fromEntries(SHEETS.map((n) => [n, bare(read(`assets/styles/${n}.css`))]));
  const all = Object.values(css).join("\n");

  it("names no easing curve but the token, except the drift", () => {
    /* Two transitions used a bare `ease` and a literal copy of the token. One
       curve is the rule; the drift's `linear` is the one stated exception, and
       tokens.css says so. */
    const eased = [...all.matchAll(/(transition|animation):[^;]+;/g)].map((m) => m[0]);
    for (const decl of eased) {
      if (/rosette/.test(decl)) {
        assert.match(decl, /\blinear\b/, `the drift is linear: ${decl}`);
        continue;
      }
      if (!/\b(ease|cubic-bezier|linear|steps)\b/.test(decl)) continue;
      assert.match(decl, /var\(--ease\)/, `should use var(--ease): ${decl}`);
      assert.doesNotMatch(decl, /cubic-bezier/, `should not restate the curve: ${decl}`);
    }
  });

  it("names no duration inline", () => {
    // Every duration is a token, so the set of them is readable in one place.
    const decls = [...all.matchAll(/(transition|animation):[^;]+;/g)].map((m) => m[0]);
    for (const decl of decls) {
      if (/rosette/.test(decl)) continue; // periods in the tens of seconds, per band
      const literal = decl.match(/\b\d+(\.\d+)?m?s\b/);
      assert.equal(literal, null, `duration should be a token: ${decl}`);
    }
    assert.match(css.tokens, /--dur-4:/);
  });

  it("animates nothing that reflows the page", () => {
    /* Every entrance moves opacity and transform only. A transition on width,
       height or a box offset would shift the rows beneath it while it ran. */
    const LAYOUT = /\b(width|height|margin|padding|top|left|right|bottom|font-size|inset)\b/;
    for (const decl of [...all.matchAll(/transition:[^;]+;/g)].map((m) => m[0])) {
      assert.doesNotMatch(decl, LAYOUT, `transitions a layout property: ${decl}`);
    }
    // One level of nesting, which is exactly what a keyframes block is:
    // `from { ... } to { ... }`. Several are written on a single line.
    const frames = [...all.matchAll(/@keyframes [\w-]+ \{(?:[^{}]|\{[^{}]*\})*\}/g)].map((m) => m[0]);
    assert.ok(frames.length >= 8, "found the keyframes");
    for (const frame of frames) {
      const inner = frame.slice(frame.indexOf("{") + 1);
      assert.doesNotMatch(inner, LAYOUT, `keyframe animates a layout property: ${frame.slice(0, 60)}`);
    }
  });

  it("scrolls smoothly only when movement was not declined", () => {
    const page = read("assets/js/runs-page.js");
    assert.match(page, /prefersReducedMotion\(\) \? "auto" : "smooth"/);
    // One scroll, not a smooth one followed by a jump to correct it.
    assert.doesNotMatch(page, /window\.scrollBy\(/);
    assert.match(page, /window\.scrollTo\(\{ top, behavior \}\)/);
  });
});
