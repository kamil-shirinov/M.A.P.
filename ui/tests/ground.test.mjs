/* The ground: a guilloche that shifts, drawn on a canvas behind every page.

   What is asserted is the contract, not the look: the figure's shape changes with
   time (it morphs, not merely turns); it asks for frames only when motion is
   welcome; it takes no layout; and every page mounts it. The look is checked in a
   browser, where frames and layout shift can be measured. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { Node, installDom } from "./dom.mjs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const load = (path) => import(`../assets/js/${path}?${Math.random()}`);

/** A 2D context that records what was drawn, enough to tell two frames apart. */
function recordingCanvas() {
  const calls = [];
  const ctx = new Proxy({}, {
    get: (_t, key) => (key in ctx_fields ? ctx_fields[key] : (...args) => calls.push([key, ...args])),
    set: (_t, key, value) => { ctx_fields[key] = value; return true; },
  });
  const ctx_fields = {};
  return { calls, ctx };
}

function withCanvas(recording) {
  const doc = installDom();
  const make = doc.createElement;
  doc.createElement = (tag) => {
    const node = make(tag);
    if (tag === "canvas") node.getContext = () => recording.ctx;
    return node;
  };
  return doc;
}

describe("the figure morphs, and does not merely turn", () => {
  it("changes each ring's shape over time, and each ring at its own rate", async () => {
    const { modulation } = await load("ui/ground.js");
    const at = (i, t) => Array.from({ length: 12 }, (_, k) => modulation(i, (k / 12) * Math.PI * 2, t));
    assert.notDeepEqual(at(0, 0), at(0, 5), "a ring's outline is different five seconds later");
    // A rotation would move every ring by the same angle; a morph does not.
    const shift = (i) => at(i, 5).map((v, k) => v - at(i, 0)[k]);
    assert.notDeepEqual(shift(0), shift(14), "the inner and outer rings drift differently");
  });

  it("stays a gentle modulation of a circle", async () => {
    const { modulation } = await load("ui/ground.js");
    for (let t = 0; t < 600; t += 37) {
      for (let i = 0; i < 15; i += 7) {
        for (let k = 0; k < 24; k++) {
          const m = modulation(i, (k / 24) * Math.PI * 2, t);
          assert.ok(m > 0.8 && m < 1.2, `ring ${i} at ${t}s: ${m}`);
        }
      }
    }
  });
});

describe("mounting it", () => {
  it("draws one frame at once, and asks for more only when motion is welcome", async () => {
    const recording = recordingCanvas();
    withCanvas(recording);
    const frames = [];
    globalThis.requestAnimationFrame = (fn) => frames.push(fn);
    globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
    const { mountGround } = await load("ui/ground.js");
    const host = new Node("div");
    const ground = mountGround(host);
    assert.ok(ground.canvas, "a canvas, not the SVG fallback");
    assert.equal(host.children[0], ground.canvas);
    const strokes = () => recording.calls.filter(([k]) => k === "stroke").length;
    assert.equal(strokes(), 15, "the first frame, fifteen rings");
    assert.equal(frames.length, 1, "and one frame requested");

    const firstMove = recording.calls.find(([k]) => k === "moveTo");
    recording.calls.length = 0;
    frames.shift()(1000);
    frames.shift()(4000);
    const later = recording.calls.filter(([k]) => k === "moveTo");
    assert.equal(strokes(), 30);
    // Ring 0's first point: the same as at mount on the loop's first frame (no
    // time has passed), and somewhere else three seconds on.
    assert.deepEqual(later[0], firstMove, "the loop resumes where the mount drew");
    assert.notDeepEqual(later[15], firstMove, "a later frame draws a different figure");
    ground.stop();
    delete globalThis.requestAnimationFrame;
    delete globalThis.matchMedia;
  });

  it("draws one still frame and asks for none under reduced motion", async () => {
    const recording = recordingCanvas();
    withCanvas(recording);
    const frames = [];
    globalThis.requestAnimationFrame = (fn) => frames.push(fn);
    globalThis.matchMedia = () => ({ matches: true, addEventListener() {} });
    const { mountGround } = await load("ui/ground.js");
    mountGround(new Node("div"));
    assert.equal(recording.calls.filter(([k]) => k === "stroke").length, 15, "still drawn");
    assert.equal(frames.length, 0, "never animated");
    delete globalThis.requestAnimationFrame;
    delete globalThis.matchMedia;
  });

  it("redraws a resize as the figure stood, not from its first frame", async () => {
    /* A door that lifts into the page resizes the ground. Redrawing its rest
       frame there read as the drift restarting. */
    const recording = recordingCanvas();
    withCanvas(recording);
    const frames = [];
    let resized = null;
    let seen = null;
    globalThis.requestAnimationFrame = (fn) => frames.push(fn);
    globalThis.cancelAnimationFrame = () => { frames.length = 0; };
    globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
    globalThis.ResizeObserver = class { constructor(fn) { resized = fn; } observe() {} };
    globalThis.IntersectionObserver = class { constructor(fn) { seen = fn; } observe() {} };
    const { mountGround } = await load("ui/ground.js");
    const ground = mountGround(new Node("div"));
    frames.shift()(1000);
    frames.shift()(9000);
    const moves = () => recording.calls.filter(([k]) => k === "moveTo");
    const at9 = moves().at(-15);
    seen([{ isIntersecting: false }]);   // scrolled away: the loop stops
    recording.calls.length = 0;
    resized();                           // and the box changes size meanwhile
    assert.deepEqual(moves()[0], at9, "the same figure, redrawn at its size");
    ground.stop();
    for (const name of ["requestAnimationFrame", "cancelAnimationFrame", "matchMedia", "ResizeObserver", "IntersectionObserver"]) {
      delete globalThis[name];
    }
  });

  it("falls back to the SVG figure where there is no canvas", async () => {
    installDom();
    const { mountGround } = await load("ui/ground.js");
    const host = new Node("div");
    const ground = mountGround(host);
    assert.equal(ground.canvas, null);
    assert.equal(ground.svg.tagName, "SVG");
  });
});

describe("it takes no layout, on every page", () => {
  it("fills a box that is already out of flow, and fades at the rim in CSS", () => {
    const system = read("assets/styles/system.css");
    const canvas = system.match(/\.ground-canvas \{[^}]*\}/)[0];
    assert.match(canvas, /width: 100%; height: 100%/);
    assert.match(canvas, /mask-image: radial-gradient/);
    const page = system.slice(system.indexOf('body[data-mode="open"] .ground,'));
    assert.match(page.slice(0, 900), /position: absolute/);
    assert.match(read("assets/styles/front-door.css"), /\.ground \{\s*position: fixed/);
  });

  it("sits behind the title and fades out below it", () => {
    const system = read("assets/styles/system.css");
    const rule = system.slice(system.indexOf('body[data-mode="open"] .ground,'), system.indexOf(".ground-canvas {"));
    assert.match(rule, /top: var\(--rosette-top, 6\.5rem\)/);
    assert.match(rule, /mask-image: linear-gradient\(to bottom, #000 0 50%/);
  });

  it("is mounted by every page", () => {
    for (const page of ["company.js", "runs-page.js", "search-page.js", "results-page.js"]) {
      const code = read(`assets/js/${page}`);
      assert.match(code, /import \{ mountGround \} from "\.\/ui\/ground\.js"/, page);
      assert.match(code, /mountGround\(\$\("ground"\)\)/, page);
    }
    for (const html of ["index.html", "company.html", "runs.html", "results.html"]) {
      assert.match(read(html), /<div class="ground" id="ground"/, html);
    }
  });

  it("does not paint its fade on the canvas every frame", () => {
    const code = read("assets/js/ui/ground.js").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.doesNotMatch(code, /createRadialGradient|globalCompositeOperation/);
    assert.doesNotMatch(code, /getComputedStyle[\s\S]{0,200}draw = /, "style is read on resize, not per frame");
  });
});
