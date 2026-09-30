/* The loading rings: one per agent, calibrating while it works, glowing when done.

   What is asserted is the contract, not the look: the cycle's four phases, the
   circles of a working ring turning against each other, a ring changing only on
   a recorded event, a finished ring settling into ONE flat circle that glows and
   stays, the loop stopping when nothing moves, and reduced motion keeping the
   glow and dropping the turning. The look is checked in a browser. */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Node, installDom } from "./dom.mjs";

const load = (m) => import(`../assets/js/${m}?${Math.random()}`);
const STAGES = ["intake", "analyst", "structuralist"];

const find = (node, test, out = []) => {
  if (test(node)) out.push(node);
  for (const c of node.children ?? []) find(c, test, out);
  return out;
};
const ringsOf = (svg) => find(svg, (n) => n.attrs?.class === "anl-ring");
const linesOf = (ring) => find(ring, (n) => n.attrs?.class === "anl-ring-line");
const turn = (line) => {
  const m = /^rotate\((-?[\d.]+) 500 500\)$/.exec(line.getAttribute("transform") ?? "");
  return m ? Number(m[1]) : null;
};

/** Frames on demand, and a visitor who has or has not asked for less motion. */
function stage({ reduced }) {
  installDom();
  const frames = [];
  globalThis.requestAnimationFrame = (fn) => frames.push(fn);
  globalThis.matchMedia = () => ({ matches: reduced, addEventListener() {} });
  const run = (t) => {
    const pending = frames.splice(0);
    for (const fn of pending) fn(t);
  };
  const done = () => {
    delete globalThis.requestAnimationFrame;
    delete globalThis.matchMedia;
  };
  return { frames, run, done };
}

describe("the cycle", () => {
  it("turns for three seconds, holds three, turns back three, holds three, and repeats", async () => {
    const { swing, SWING_DEGREES } = await load("ui/calibration-rings.js");
    assert.equal(swing(0), 0);
    assert.ok(Math.abs(swing(1.5) - SWING_DEGREES / 2) < 1e-9);
    assert.equal(swing(3), SWING_DEGREES);
    assert.equal(swing(4.5), SWING_DEGREES, "held");
    assert.equal(swing(6), SWING_DEGREES);
    assert.ok(Math.abs(swing(7.5) - SWING_DEGREES / 2) < 1e-9, "turning back, every direction reversed");
    assert.equal(swing(9), 0);
    assert.equal(swing(10.5), 0, "held");
    for (const t of [0, 1.1, 3.7, 7.2, 10]) assert.equal(swing(t + 12), swing(t), "and again");
    for (let t = 0.1; t < 3; t += 0.1) assert.ok(swing(t) > swing(t - 0.1), `out at ${t}`);
    for (let t = 6.1; t < 9; t += 0.1) assert.ok(swing(t) < swing(t - 0.1), `back at ${t}`);
  });

  it("goes at one speed however long the agent takes: nothing in it fills", async () => {
    const { swing } = await load("ui/calibration-rings.js");
    const early = [0.5, 1, 2, 4, 7, 8, 10].map(swing);
    const late = [0.5, 1, 2, 4, 7, 8, 10].map((t) => swing(t + 12 * 40));
    assert.deepEqual(late, early);
  });
});

describe("a ring per agent, changed only by the run's events", () => {
  it("puts intake inside, analyst in the middle and structuralist outside, three wavy circles each", async () => {
    const s = stage({ reduced: false });
    const { createRings } = await load("ui/calibration-rings.js");
    const { svg } = createRings(STAGES);
    const rings = ringsOf(svg);
    assert.deepEqual(rings.map((r) => r.dataset.stage), STAGES);
    for (const ring of rings) {
      const lines = linesOf(ring);
      assert.equal(lines.length, 3);
      assert.equal(new Set(lines.map((l) => l.getAttribute("d"))).size, 3, "three distinct wavy circles");
    }
    const radius = (ring) => Number(/^M([\d.]+)/.exec(linesOf(ring)[1].getAttribute("d"))[1]) - 500;
    assert.ok(radius(rings[0]) < radius(rings[1]) && radius(rings[1]) < radius(rings[2]));
    s.done();
  });

  it("turns a working ring's circles against each other, and leaves the waiting ones still", async () => {
    const s = stage({ reduced: false });
    const { createRings, SWING_DEGREES } = await load("ui/calibration-rings.js");
    const rings = createRings(STAGES);
    rings.set("intake", "running");
    s.run(1000);
    s.run(2500);
    const [intake, analyst] = ringsOf(rings.svg);
    const turns = linesOf(intake).map(turn);
    assert.ok(Math.abs(turns[0] - SWING_DEGREES / 2) < 0.01, `half way out at 1.5s: ${turns[0]}`);
    assert.deepEqual(turns.map(Math.sign), [1, -1, 1], "neighbours turn opposite ways");
    assert.deepEqual(linesOf(analyst).map(turn), [null, null, null], "a waiting ring does not turn");
    s.done();
  });

  it("settles a finished ring into one flat glowing circle, and keeps it", async () => {
    const s = stage({ reduced: false });
    const { createRings, SETTLE_MS } = await load("ui/calibration-rings.js");
    const rings = createRings(STAGES);
    rings.set("intake", "running");
    s.run(0);
    s.run(2000);
    rings.set("intake", "done");
    rings.set("analyst", "running");
    const [intake] = ringsOf(rings.svg);
    assert.equal(intake.dataset.state, "done");
    assert.match(intake.getAttribute("filter"), /^url\(#anl-glow-\d+\)$/);
    s.run(3000);
    s.run(3000 + SETTLE_MS / 2);
    const mid = linesOf(intake).map((l) => l.getAttribute("d"));
    assert.equal(new Set(mid).size, 3, "still easing half way");
    s.run(3000 + SETTLE_MS);
    const flat = linesOf(intake);
    assert.equal(new Set(flat.map((l) => l.getAttribute("d"))).size, 1, "one circle");
    assert.deepEqual(flat.map(turn), [0, 0, 0]);
    s.run(9000);
    assert.equal(new Set(linesOf(intake).map((l) => l.getAttribute("d"))).size, 1, "and it stays one");
    s.done();
  });

  it("stops asking for frames once nothing turns or settles", async () => {
    const s = stage({ reduced: false });
    const { createRings, SETTLE_MS } = await load("ui/calibration-rings.js");
    const rings = createRings(STAGES);
    rings.set("intake", "running");
    s.run(0);
    for (const stageName of STAGES) rings.set(stageName, "done");
    s.run(100);
    s.run(100 + SETTLE_MS);
    assert.equal(s.frames.length, 0, "three glowing circles, and the loop is over");
    s.done();
  });

  it("holds a failed run's ring where it stood", async () => {
    const s = stage({ reduced: false });
    const { createRings } = await load("ui/calibration-rings.js");
    const rings = createRings(STAGES);
    rings.set("intake", "running");
    s.run(0);
    s.run(1000);
    rings.set("intake", "stopped");
    s.run(2000);
    assert.equal(s.frames.length, 0);
    assert.equal(ringsOf(rings.svg)[0].dataset.state, "stopped");
    s.done();
  });
});

describe("reduced motion", () => {
  it("turns nothing, and still makes each finished ring its glowing circle at once", async () => {
    const s = stage({ reduced: true });
    const { createRings } = await load("ui/calibration-rings.js");
    const rings = createRings(STAGES);
    rings.set("intake", "running");
    assert.equal(s.frames.length, 0, "no frame asked for");
    rings.set("intake", "done");
    const [intake] = ringsOf(rings.svg);
    assert.equal(new Set(linesOf(intake).map((l) => l.getAttribute("d"))).size, 1);
    assert.match(intake.getAttribute("filter"), /anl-glow/);
    assert.equal(s.frames.length, 0);
    s.done();
  });

  it("drops the easing in CSS as well, so the glow is simply there", async () => {
    const { readFileSync } = await import("node:fs");
    const sheet = readFileSync(new URL("../assets/styles/analyse.css", import.meta.url), "utf8");
    const reduced = sheet.slice(sheet.indexOf("@media (prefers-reduced-motion: reduce) {\n  /* Still alive"));
    assert.match(reduced, /\.anl-ring-line \{ transition: none; \}/);
    assert.match(sheet, /\.anl-ring\[data-state="done"\] \.anl-ring-line \{[^}]*stroke: var\(--ring-glow\)/);
    const tokens = readFileSync(new URL("../assets/styles/tokens.css", import.meta.url), "utf8");
    assert.equal((tokens.match(/--ring-glow:/g) ?? []).length, 3, "dark, and both ways of being light");
  });
});

describe("the progress panel", () => {
  it("builds its rings from the run's own stage list when the run starts", async () => {
    const s = stage({ reduced: true });
    const { createProgress } = await load("ui/live-progress.js");
    const host = new Node("div");
    const display = createProgress(host, { ticker: "KO" });
    display.update({ event: "started", ticker: "KO", horizon_days: 5, typical_seconds: 400, stages: STAGES });
    display.update({ event: "progress", stage: "intake", detail: "" });
    const rings = find(host, (n) => n.attrs?.class === "anl-ring");
    assert.deepEqual(rings.map((r) => r.dataset.state), ["done", "running", "waiting"]);
    display.finish();
    s.done();
  });
});
