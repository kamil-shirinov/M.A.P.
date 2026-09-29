/* The DOM these tests render into, and the fetch that feeds it.

   There were five copies of this — company, runs, results, front-door and
   analyse — which is how the `setAttribute("class", …)` fix came to exist in one
   of them and nowhere else. Every SVG element in this app is built through
   `createElementNS`, which takes its attributes that way, so in four of the five
   stubs a class set on an `<svg>` child was invisible to any assertion looking
   for it. A test that cannot see a class does not fail; it passes for the wrong
   reason.

   So: one stub, carrying the union of what the five needed. It is deliberately
   small and deliberately not a DOM implementation. It renders, it accumulates
   text, and it answers the two queries the provenance audit makes. Anything a
   page needs beyond that belongs in a browser check, which is what
   `styles.probe.mjs` is for. */

import { existsSync, readFileSync } from "node:fs";

const EXPORT = new URL("../assets/export/", import.meta.url);

export class Node {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase();
    this.children = []; this.attrs = {}; this.dataset = {}; this.style = {};
    this.classList = { add: (c) => this._cls.add(c), remove: (c) => this._cls.delete(c), contains: (c) => this._cls.has(c) };
    this._cls = new Set(); this._text = ""; this.parentElement = null;
  }

  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._cls].join(" "); }

  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    return this._text + this.children.map((c) => (c.nodeType === 3 ? c.data : c.textContent)).join("");
  }

  /* `class` set via setAttribute is the same thing as className — which is how
     every SVG element in this app is built, since createElementNS takes its
     attributes that way. Four of the five copies kept the two apart, so a class
     set on an <svg> child was invisible to any assertion that looked for it. */
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "class") this.className = String(v);
  }
  getAttribute(k) { return this.attrs[k]; }

  addEventListener(name, fn) { (this._on ??= {})[name] = fn; }

  append(...kids) {
    for (const k of kids) {
      const node = typeof k === "string" ? { nodeType: 3, data: k, parentElement: this } : k;
      node.parentElement = this;
      this.children.push(node);
    }
  }

  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children.at(-1); }

  querySelector() { return null; }
  querySelectorAll() { return []; }

  /** Only the provenance audit's selector is supported:
      `[data-prov], [data-chrome], [data-audit-exempt]`. */
  closest(sel) {
    const keys = (sel.match(/data-[a-z-]+/g) ?? [])
      .map((d) => d.replace("data-", "").replace(/-(.)/g, (_, c) => c.toUpperCase()));
    for (let n = this; n; n = n.parentElement) {
      if (n.dataset && keys.some((k) => n.dataset[k] !== undefined)) return n;
    }
    return null;
  }
}

/** Paths the stubbed `fetch` was asked for, in order. Cleared by `installDom`.

    Several tests assert on WHICH files a screen opened and when — the whole
    lazy-loading design of the search screen is a claim about that — so the list
    is part of the stub rather than something each file keeps for itself. */
export const fetched = [];

/** Install a document, a location and a fetch that reads the real export.

    Returns the document, which some callers replace `createElement` on to build
    a narrower node than this one. `withFetch: false` leaves `globalThis.fetch`
    alone for a test that wants to supply its own. */
export function installDom({ withFetch = true } = {}) {
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
  fetched.length = 0;
  if (withFetch) {
    globalThis.fetch = async (path) => {
      const name = String(path).replace(/^assets\/export\//, "");
      fetched.push(name);
      if (!existsSync(new URL(name, EXPORT))) return { status: 404, ok: false };
      return { status: 200, ok: true, json: async () => JSON.parse(readFileSync(new URL(name, EXPORT), "utf8")) };
    };
  }
  return doc;
}
