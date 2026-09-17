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

describe("the door's strip", { skip: !HAVE }, () => {
  it("says only what universe.json can count, with the count marked", () => {
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

    const companies = JSON.parse(readFileSync(new URL("universe.json", EXPORT), "utf8")).length;
    mountDoor(host, { onQuery: () => {}, companies });

    const strip = host.children.find((c) => c.className === "door-strip");
    assert.equal(strip.textContent, `${companies} companies`);
    const figure = strip.children[0];
    assert.equal(figure.dataset.prov, "derived");
    assert.ok(strip.children.slice(1).every((c) => c.dataset.chrome !== undefined));
    assert.ok(block.children.some((c) => c.className === "door-box"), "the box goes into the static block");
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
    assert.match(block, /\[data-band\] \{ animation: none; \}/);
    assert.match(block, /\.ground \{ transition: none; \}/);
    assert.match(block, /::view-transition-group\(\*\),\s*::view-transition-old\(\*\),\s*::view-transition-new\(\*\) \{ animation-duration: 1ms !important; \}/);
  });

  it("puts the ground behind the page rather than level with it", () => {
    assert.match(rulesFor(css, ".ground")[0], /z-index: -1;/);
  });

  it("sets the masthead nav on tokens, untracked, like the vintages beside it", () => {
    for (const sel of [".masthead-nav", ".masthead-nav-here", ".masthead-nav-soon", ".masthead-nav a"]) {
      for (const decls of rulesFor(css, sel)) {
        // Spacing only: a 1px hairline is the shipped border everywhere, and has no token.
        assert.doesNotMatch(decls, /(gap|padding|margin)[\w-]*:[^;]*\d+px/, `${sel} spaces in pixels`);
        assert.doesNotMatch(decls, /letter-spacing/, `${sel} is tracked`);
      }
    }
    assert.match(rulesFor(css, ".masthead-nav")[0], /gap: var\(--sp-4\);/);
  });

  it("keeps the masthead crest on the left edge the sections start on", () => {
    for (const decls of rulesFor(css, ".masthead h1")) assert.doesNotMatch(decls, /text-indent/);
  });
});
