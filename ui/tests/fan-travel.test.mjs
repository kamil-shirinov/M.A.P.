/* The projection chart: smoother curves that stay on their data, and the dots
   that travel it on load.

   What is asserted: every close and every quantile is ON its curve and nothing
   between two of them overshoots both; the scenario curves are their closed
   form, densely; on load a dot runs the closes to the anchor and then three run
   the scenarios side by side, each in its colour, the reveals keeping pace; and
   with reduced motion the chart is simply finished, the three dots at their
   ends. NO EXPORT NEEDED. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { Node, installDom } from "./dom.mjs";

const load = (m) => import(`../assets/js/${m}?${Math.random()}`);
const css = readFileSync(new URL("../assets/styles/analyse.css", import.meta.url), "utf8");
const descendants = (root) => {
  const out = [];
  const walk = (n) => { out.push(n); (n.children ?? []).forEach(walk); };
  (root.children ?? []).forEach(walk);
  return out;
};
const coords = (d) => [...d.matchAll(/[ML]([-\d.]+) ([-\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);

const LEVELS = Array.from({ length: 19 }, (_, k) => Math.round((k + 1) * 5) / 100);
const SCENARIOS = [
  { name: "bullish", weight: 0.25, price_return: 0.06, annualised_vol: 0.34 },
  { name: "base_case", weight: 0.5, price_return: 0.01, annualised_vol: 0.28 },
  { name: "bearish", weight: 0.25, price_return: -0.05, annualised_vol: 0.41 },
];
const result = () => ({
  event: "result", run_id: "r-1", ticker: "AAPL", anchor: "2026-09-22", spot: 200, horizon_days: 5,
  scenarios: SCENARIOS, marking: "uncalibrated", corrected: false, reasons: [],
  band: [],
  fan: {
    levels: LEVELS,
    sessions: [0, 1, 2, 3, 4, 5].map((t) => ({
      session: t, prices: LEVELS.map((q) => 200 * (1 + (q - 0.5) * 0.04 * Math.sqrt(t))),
    })),
  },
  scenario_paths: SCENARIOS.map((s) => ({
    name: s.name, weight: s.weight,
    prices: [0, 1, 2, 3, 4, 5].map((t) => 200 * (1 + s.price_return) ** (t / 5)),
  })),
  history: [["2026-07-01", 190], ["2026-07-15", 197], ["2026-08-03", 193], ["2026-09-01", 201], ["2026-09-22", 200]],
});

describe("the curves", () => {
  it("pass through every point they were given, exactly", async () => {
    const { smooth } = await load("ui/analyse-fan.js");
    const knots = [[0, 10], [1, 14], [2, 11], [3, 11], [4, 20]];
    const dense = smooth(knots, 16);
    assert.equal(dense.length, 4 * 16 + 1, "denser: sixteen samples an interval");
    for (const [x, y] of knots) {
      assert.ok(dense.some(([dx, dy]) => dx === x && Math.abs(dy - y) < 1e-12), `(${x}, ${y}) is on the curve`);
    }
  });

  it("never rise above or dip below both ends of an interval", async () => {
    const { smooth } = await load("ui/analyse-fan.js");
    const knots = [[0, 10], [1, 14], [2, 11], [3, 11], [4, 20], [5, 20.5]];
    const dense = smooth(knots, 32);
    for (let i = 0; i < knots.length - 1; i++) {
      const [xa, ya] = knots[i];
      const [xb, yb] = knots[i + 1];
      const inside = dense.filter(([x]) => x >= xa && x <= xb).map(([, y]) => y);
      assert.ok(Math.max(...inside) <= Math.max(ya, yb) + 1e-9, `no invented high in [${xa}, ${xb}]`);
      assert.ok(Math.min(...inside) >= Math.min(ya, yb) - 1e-9, `no invented low in [${xa}, ${xb}]`);
    }
  });

  it("draw each scenario densely from its closed form, through every session's price", async () => {
    installDom();
    const { renderFan, yAt } = await load("ui/analyse-fan.js");
    const svg = renderFan(new Node("div"), result(), { opening: false });
    const nodes = descendants(svg);
    const axis = nodes.filter((n) => n._cls?.has("anl-ytick")).map((t) => [Number(t.textContent), Number(t.attrs.y) - 4]);
    const [[p0, y0], [p1, y1]] = [axis[0], axis.at(-1)];
    const yOf = (price) => y0 + ((price - p0) * (y1 - y0)) / (p1 - p0);
    for (const s of SCENARIOS) {
      const line = nodes.find((n) => n._cls?.has("anl-path") && n.attrs["data-scenario"] === s.name);
      const points = coords(line.attrs.d);
      assert.ok(points.length >= 5 * 16 + 1, `${s.name}: ${points.length} points`);
      const [xs, xe] = [points[0][0], points.at(-1)[0]];
      for (let t = 0; t <= 5; t++) {
        const x = xs + ((xe - xs) * t) / 5;
        const want = yOf(200 * (1 + s.price_return) ** (t / 5));
        assert.ok(Math.abs(yAt(points, x) - want) < 0.05, `${s.name} at session ${t}`);
      }
    }
    const history = nodes.find((n) => n._cls?.has("anl-history"));
    assert.ok(coords(history.attrs.d).length >= 4 * 16 + 1, "the closes are drawn as a dense curve");
  });
});

describe("the journey on load", () => {
  const stage = (reduced) => {
    installDom();
    const frames = [];
    globalThis.requestAnimationFrame = (fn) => frames.push(fn);
    globalThis.matchMedia = () => ({ matches: reduced, addEventListener() {} });
    return {
      frames,
      at: (ms, start) => { const pending = frames.splice(0); for (const fn of pending) fn(start + ms); },
      done: () => { delete globalThis.requestAnimationFrame; delete globalThis.matchMedia; },
    };
  };
  const parts = (svg) => {
    const nodes = descendants(svg);
    const dots = nodes.filter((n) => n._cls?.has("anl-dot"));
    return {
      lead: dots.find((d) => d.attrs["data-scenario"] === "history"),
      heads: dots.filter((d) => d.attrs["data-scenario"] !== "history"),
      pastReveal: nodes.find((n) => n._cls?.has("anl-reveal--history")),
      fanReveal: nodes.find((n) => n._cls?.has("anl-reveal--fan")),
      anchor: Number(nodes.find((n) => n._cls?.has("anl-anchor")).attrs.x1),
      labels: nodes.find((n) => n._cls?.has("anl-plabels")),
    };
  };

  it("runs one dot along the closes to the anchor, drawing them behind it", async () => {
    const s = stage(false);
    const { renderFan } = await load("ui/analyse-fan.js");
    const start = performance.now();
    const p = parts(renderFan(new Node("div"), result()));
    assert.equal(p.lead.attrs.visibility, "visible");
    assert.ok(p.heads.every((h) => h.attrs.visibility === "hidden"), "the three wait for the split");
    assert.equal(p.fanReveal.attrs.width, "0", "the fan is shut until the dot reaches the anchor");
    s.at(700, start);
    const x = Number(p.lead.attrs.cx);
    assert.ok(x > 64 && x < p.anchor, "part way along the closes");
    assert.ok(Math.abs(Number(p.pastReveal.attrs.width) - (x + 1)) < 0.01, "the line is drawn up to the dot");
    s.done();
  });

  it("splits into three that run the scenarios side by side, the fan opening with them", async () => {
    const s = stage(false);
    const { renderFan } = await load("ui/analyse-fan.js");
    const start = performance.now();
    const p = parts(renderFan(new Node("div"), result()));
    s.at(1400 + 700, start);
    assert.equal(p.lead.attrs.visibility, "hidden", "the one became three at the anchor");
    const xs = p.heads.map((h) => h.attrs.cx);
    assert.equal(new Set(xs).size, 1, "side by side");
    assert.ok(Number(xs[0]) > p.anchor);
    assert.ok(Math.abs(Number(p.fanReveal.attrs.width) - (Number(xs[0]) - p.anchor + 1)) < 0.01, "the fan keeps pace");
    const ys = Object.fromEntries(p.heads.map((h) => [h.attrs["data-scenario"], Number(h.attrs.cy)]));
    assert.ok(ys.bullish < ys.base_case && ys.base_case < ys.bearish, "each on its own path");
    s.at(1400 + 1400 + 50, start);
    assert.equal(s.frames.length, 0, "and it ends");
    assert.equal(p.labels.style.opacity, "1");
    s.done();
  });

  it("rests the three dots on the endpoints, and draws that finished chart at once under reduced motion", async () => {
    const s = stage(true);
    const { renderFan } = await load("ui/analyse-fan.js");
    const svg = renderFan(new Node("div"), result());
    const p = parts(svg);
    assert.equal(s.frames.length, 0, "nothing moves");
    assert.equal(p.lead.attrs.visibility, "hidden");
    assert.notEqual(p.fanReveal.attrs.width, "0");
    for (const head of p.heads) {
      const line = descendants(svg).find((n) => n._cls?.has("anl-path") && n.attrs["data-scenario"] === head.attrs["data-scenario"]);
      const [ex, ey] = coords(line.attrs.d).at(-1);
      assert.ok(Math.abs(Number(head.attrs.cx) - ex) < 0.01 && Math.abs(Number(head.attrs.cy) - ey) < 0.01);
      assert.notEqual(head.attrs.visibility, "hidden");
    }
    s.done();
  });
});

describe("the colours", () => {
  it("are green, white and red for the three scenarios, and never amber", () => {
    const rule = (sel) => css.match(new RegExp(`${sel.replace(/[[\]().]/g, "\\$&")} \\{[^}]*\\}`))?.[0] ?? "";
    for (const kind of ["anl-path", "anl-dot", "anl-plabel"]) {
      assert.match(rule(`.${kind}[data-scenario="bullish"]`), /var\(--up\)/, kind);
      assert.match(rule(`.${kind}[data-scenario="base_case"]`), /var\(--ink-num\)/, kind);
      assert.match(rule(`.${kind}[data-scenario="bearish"]`), /var\(--down\)/, kind);
    }
    const scenarioRules = css.match(/\.anl-(path|dot|plabel)\[data-scenario="[a-z_]+"\] \{[^}]*\}/g);
    assert.ok(scenarioRules.length >= 9);
    assert.ok(!scenarioRules.some((r) => /--uncal/.test(r)), "amber is the marking's alone");
  });

  it("says the middle band is the strongest, which is how it reads on a dark page", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, result(), { opening: false });
    assert.match(host.textContent, /the middle 10% of the forecast, strongest, out to the middle 90%/);
    assert.doesNotMatch(host.textContent, /darkest/);
  });
});
