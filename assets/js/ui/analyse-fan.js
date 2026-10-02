/* The fan, and the marking that is part of drawing it.

   THE MARKING IS NOT A DECORATION ADDED AFTER. `renderFan` refuses a result that
   carries no `marking`, so there is no code path in which a fan reaches the
   screen without saying what it is. ADR 0036 §1 is the rule; this is the place it
   cannot be forgotten.

   A BANK OF ENGLAND FAN. The last three months of closes run into the anchor, and
   the forecast opens out from it in nine graded bands — the middle 10% of the
   distribution strongest, out to the middle 90% — widening session by session.
   Every band edge is a quantile the server or the exporter took from
   `simulate_paths`, whose last session is the scorer's own sample; nothing here
   samples, smooths a distribution or invents a level. The page draws each edge,
   and the history, as a monotone curve THROUGH those points: every quantile and
   every close is on its line, and nothing between two of them rises above or
   dips below both, which a Catmull–Rom curve could.

   The scenarios are thin curves over the fan in their own colours — bullish
   green, base case white, bearish red — each ending on the price it states, with
   its name and weight at the end. They are the shape of the reasoning; the bands
   are the claim. Their curves are their closed form, computed densely, so they
   are exact rather than drawn.

   ON LOAD, A DOT TRAVELS the closes to the anchor, drawing the history behind it,
   then splits into three that travel the scenario paths side by side to the
   horizon while the fan opens with them, and rest on the three endpoints. With
   reduced motion the chart is simply drawn finished, the three dots at their ends.

   Amber keeps the one meaning it was narrowed to: a number that is not a settled
   measurement. An uncorrected fan is one — the raw fan is the version measured too
   narrow — so its bands are amber. A corrected fan is neutral, and its marking
   still says it is not calibrated.

   TWO SCALES, SAID ALOUD. Five sessions ahead beside sixty-three behind would make
   the fan a sliver at the right edge, so the forecast side is drawn wider than the
   history side, with a rule at the anchor between them. The legend says so,
   because a chart that changes scale without saying is misleading however well
   meant. */

import { DERIVED, MEASURED, chrome, chromeText, derive, figure, renderFigure } from "../lib/figure.js";
import { prefersReducedMotion } from "../lib/motion.js";

const SVG = "http://www.w3.org/2000/svg";
const W = 1080;
const H = 420;
// The top holds the two scale captions, one either side of the anchor.
const PAD = { top: 40, right: 150, bottom: 40, left: 64 };
// Of the plot's width, the share the history side gets when there is history.
const HISTORY_SHARE = 0.55;
// The dot's two legs: along the closes, then out along the three scenarios.
const HISTORY_MS = 1400;
const FORECAST_MS = 1400;
// Curve samples between two points: enough that no corner shows at any width.
const PER_INTERVAL = 16;
const DOT_R = 4.5;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const svgNode = (tag, attrs) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs ?? {})) node.setAttribute(k, String(v));
  return node;
};

/** Nice axis levels, the same 1/2/2.5/5 ladder the company chart uses. */
function ticks(lo, hi, target = 6) {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

const LABELS = { bullish: "Bullish", base_case: "Base case", bearish: "Bearish" };

/** The three scenario endpoints, as prices, from the spot and each return.

    `price_return` is a SIMPLE return, not a log one — `format.js` keeps two
    helpers apart for this exact reason. `spot * exp(r)` would be invisible below
    about 4% and then diverge one-directionally, which is the shape of an error
    that looks like a plausible price at every magnitude. */
function endpoints(result) {
  return result.scenarios.map((s) => ({
    name: s.name,
    weight: s.weight,
    price: result.spot * (1 + s.price_return),
    priceReturn: s.price_return,
  }));
}

/** The fan as the result carries it, or — for a result from before the fan
    existed — the band alone, opening from the spot in one step. Never a level the
    result does not hold. */
function fanOf(result) {
  if (result.fan && Array.isArray(result.fan.sessions) && result.fan.sessions.length > 1) {
    return { levels: result.fan.levels, sessions: result.fan.sessions };
  }
  const band = Array.isArray(result.band) ? [...result.band].sort((a, b) => a.level - b.level) : [];
  if (band.length < 2) return null;
  return {
    levels: band.map((b) => b.level),
    sessions: [
      { session: 0, prices: band.map(() => result.spot) },
      { session: result.horizon_days, prices: band.map((b) => b.price) },
    ],
  };
}

/** Each scenario's curve, densely: its closed form `spot * (end / spot) ** (t / h)`,
    the same `spot * (1 + r) ** (t / h)` the server computes, so it passes exactly
    through every session's price the result carries and is exact in between. The
    end is the result's own last price where it carries curves, else the stated
    return. */
function curvesOf(result) {
  const h = result.horizon_days;
  const carried = Array.isArray(result.scenario_paths) && result.scenario_paths.length
    ? result.scenario_paths.map((c) => ({ name: c.name, weight: c.weight, end: c.prices.at(-1) }))
    : result.scenarios.map((s) => ({ name: s.name, weight: s.weight, end: result.spot * (1 + s.price_return) }));
  const steps = h * PER_INTERVAL;
  return carried.map((c) => ({
    name: c.name,
    weight: c.weight,
    points: Array.from({ length: steps + 1 }, (_, k) => {
      const t = (k / steps) * h;
      return [t, result.spot * (c.end / result.spot) ** (t / h)];
    }),
  }));
}

/** A monotone cubic through points whose x increases (Fritsch–Carlson), sampled
    `per` times per interval. Every given point is on the curve exactly, and
    between two points the curve never goes above or below both — so a close is
    not given a high it did not have, and a band edge does not bulge past its
    quantiles. Fewer than three points are joined straight. */
export function smooth(points, per = PER_INTERVAL) {
  const n = points.length;
  if (n < 2) return points.slice();
  const out = [];
  if (n === 2) {
    const [[xa, ya], [xb, yb]] = points;
    for (let j = 0; j < per; j++) out.push([xa + ((xb - xa) * j) / per, ya + ((yb - ya) * j) / per]);
    out.push(points[1]);
    return out;
  }
  const dx = [];
  const m = [];
  for (let i = 0; i < n - 1; i++) {
    dx[i] = points[i + 1][0] - points[i][0];
    m[i] = (points[i + 1][1] - points[i][1]) / dx[i];
  }
  const t = new Array(n);
  t[0] = m[0];
  t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
    const a = t[i] / m[i];
    const b = t[i + 1] / m[i];
    const r = a * a + b * b;
    if (r > 9) {
      const k = 3 / Math.sqrt(r);
      t[i] = k * a * m[i];
      t[i + 1] = k * b * m[i];
    }
  }
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = points[i];
    const y1 = points[i + 1][1];
    for (let j = 0; j < per; j++) {
      const u = j / per;
      const u2 = u * u;
      const u3 = u2 * u;
      const y = (2 * u3 - 3 * u2 + 1) * y0 + (u3 - 2 * u2 + u) * dx[i] * t[i]
        + (-2 * u3 + 3 * u2) * y1 + (u3 - u2) * dx[i] * t[i + 1];
      out.push([x0 + u * dx[i], y]);
    }
  }
  out.push(points[n - 1]);
  return out;
}

/** A dense run of points as one path. */
function trace(points) {
  return points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
}

/** The height of a dense curve at `x`, by interpolation between its samples. */
export function yAt(points, x) {
  if (x <= points[0][0]) return points[0][1];
  let lo = 0;
  let hi = points.length - 1;
  if (x >= points[hi][0]) return points[hi][1];
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] <= x) lo = mid;
    else hi = mid;
  }
  const [xa, ya] = points[lo];
  const [xb, yb] = points[hi];
  return ya + ((yb - ya) * (x - xa)) / (xb - xa);
}

/** A trading date as a reader says it. The ISO string stays the source. */
function spoken(iso) {
  const d = new Date(`${iso}T12:00:00Z`);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

/** The `t`-th weekday after `iso`. The chart does not know market holidays, and
    the legend says so; the horizon itself is counted in sessions. */
function weekdaysAfter(iso, t) {
  const d = new Date(`${iso}T12:00:00Z`);
  let left = t;
  while (left > 0) {
    d.setUTCDate(d.getUTCDate() + 1);
    const day = d.getUTCDay();
    if (day !== 0 && day !== 6) left -= 1;
  }
  return d.toISOString().slice(0, 10);
}

let clipCount = 0;

/** The fan. Throws rather than drawing an unmarked one.

    `opening`: open the fan once, from the anchor outward, when motion is welcome.
    Everything is drawn at its final geometry first; the opening only uncovers it,
    so a reader who has asked for less motion — or a screenshot — gets the whole
    fan in the first frame. */
export function renderFan(host, result, { opening = true } = {}) {
  host.textContent = "";
  if (!result || typeof result.marking !== "string") {
    // Loudly, because the failure this prevents is a fan that looks settled.
    throw new Error("a fan cannot be drawn without its marking");
  }

  const paths = endpoints(result);
  const fan = fanOf(result);
  const h = result.horizon_days;
  const sessions = fan
    ? fan.sessions
    : [{ session: 0, prices: [result.spot] }, { session: h, prices: [result.spot] }];
  const curves = curvesOf(result);
  const history = Array.isArray(result.history)
    ? result.history.filter((p) => Array.isArray(p) && p.length === 2)
    : [];

  const x0 = PAD.left;
  const x1 = W - PAD.right;
  const today = history.length > 1 ? x0 + HISTORY_SHARE * (x1 - x0) : x0;
  const xh = (i) => x0 + (i / Math.max(history.length - 1, 1)) * (today - x0);
  const xf = (t) => today + (t / h) * (x1 - today);

  // The axis covers everything drawn, the fan's outermost band included, or the
  // band is clipped at the frame and reads as narrower than it is.
  const values = [
    result.spot,
    ...history.map((p) => p[1]),
    ...sessions.flatMap((s) => s.prices),
    ...curves.flatMap((c) => c.points.map((p) => p[1])),
    ...paths.map((p) => p.price),
  ];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || Math.max(1, result.spot * 0.02);
  const top = hi + pad;
  const bottom = lo - pad;
  const y = (price) => PAD.top + ((top - price) / (top - bottom)) * (H - PAD.top - PAD.bottom);

  const svg = svgNode("svg", {
    viewBox: `0 0 ${W} ${H}`,
    class: "anl-fan",
    role: "img",
    "aria-label": `Forecast fan for ${result.ticker} over ${h} sessions, `
      + `with ${history.length} sessions of closes before it`,
  });
  // The whole figure carries the marking, so a screenshot of it is marked too.
  svg.dataset.calibration = result.marking;

  const defs = svgNode("defs");
  const clipId = `anl-open-${++clipCount}`;
  const clip = svgNode("clipPath", { id: clipId });
  const reveal = svgNode("rect", { class: "anl-reveal anl-reveal--fan", x: today - 1, y: 0, width: W - today + 1, height: H });
  clip.append(reveal);
  // The history's own reveal, which the dot draws the closes behind.
  const pastId = `anl-past-${clipCount}`;
  const past = svgNode("clipPath", { id: pastId });
  const pastReveal = svgNode("rect", { class: "anl-reveal anl-reveal--history", x: 0, y: 0, width: today + 1, height: H });
  past.append(pastReveal);
  defs.append(clip, past);
  svg.append(defs);

  // -- axes ------------------------------------------------------------------
  const axis = svgNode("g", { class: "anl-axis" });
  for (const level of ticks(bottom, top)) {
    axis.append(svgNode("line", { class: "anl-grid", x1: x0, x2: x1, y1: y(level), y2: y(level) }));
    const text = svgNode("text", { class: "anl-ytick", x: x0 - 8, y: y(level) + 4 });
    text.textContent = level.toFixed(2);
    text.dataset.prov = DERIVED;
    axis.append(text);
  }
  const base = H - PAD.bottom + 18;
  let month = null;
  history.forEach(([date], i) => {
    const m = date.slice(0, 7);
    if (m !== month && i > 0) {
      const text = svgNode("text", { class: "anl-xtick", x: xh(i), y: base });
      text.textContent = spoken(date).split(" ").slice(2).join(" ");
      text.dataset.chrome = "a month in the price history";
      axis.append(text);
    }
    month = m;
  });
  const every = h <= 5 ? 1 : h <= 10 ? 2 : 5;
  for (let t = every; t <= h; t += every) {
    if (h - t > 0 && h - t < every / 2) continue;
    const text = svgNode("text", { class: "anl-xtick", x: xf(t), y: base });
    text.textContent = `+${t}`;
    text.dataset.chrome = "sessions ahead of the anchor";
    axis.append(text);
  }
  if (h % every) {
    const text = svgNode("text", { class: "anl-xtick", x: xf(h), y: base });
    text.textContent = `+${h}`;
    text.dataset.chrome = "sessions ahead of the anchor";
    axis.append(text);
  }
  svg.append(axis);

  // -- the history, running into the anchor ---------------------------------
  const pastLine = history.length > 1 ? smooth(history.map(([, close], i) => [xh(i), y(close)])) : [];
  if (pastLine.length) {
    svg.append(svgNode("path", { class: "anl-history", d: trace(pastLine), "clip-path": `url(#${pastId})` }));
  }

  // -- the fan: nine bands, outside in, then the scenario curves -------------
  const opened = svgNode("g", { class: "anl-opening", "clip-path": `url(#${clipId})` });
  if (fan) {
    const n = fan.levels.length;
    for (let i = 0; i < Math.floor(n / 2); i++) {
      const upper = smooth(sessions.map((s) => [xf(s.session), y(s.prices[n - 1 - i])]));
      const lower = smooth(sessions.map((s) => [xf(s.session), y(s.prices[i])])).reverse();
      const d = `${trace(upper)} L${trace(lower).slice(1)} Z`;
      const band = svgNode("path", { class: "anl-band", d });
      band.dataset.level = String(Math.round((fan.levels[n - 1 - i] - fan.levels[i]) * 100));
      opened.append(band);
    }
  }
  const drawn = curves.map((curve) => ({ name: curve.name, points: curve.points.map(([t, p]) => [xf(t), y(p)]) }));
  for (const [k, curve] of curves.entries()) {
    const line = svgNode("path", {
      class: "anl-path",
      d: trace(drawn[k].points),
      "data-scenario": curve.name,
    });
    // Weight drives opacity, so the likely path reads as the likely one without
    // a legend having to say so.
    line.style.opacity = String(0.4 + curve.weight * 0.6);
    opened.append(line);
  }
  svg.append(opened);

  // The anchor: the one measured price the fan opens from.
  svg.append(svgNode("line", { class: "anl-anchor", x1: today, x2: today, y1: PAD.top, y2: H - PAD.bottom }));
  if (history.length > 1) svg.append(scaleBreak({ x0, x1, today, h, closes: history.length }));
  svg.append(svgNode("circle", { class: "anl-spot", cx: today, cy: y(result.spot), r: 3.5 }));
  const anchorLabel = svgNode("text", { class: "anl-xtick anl-xtick--anchor", x: today, y: base });
  anchorLabel.textContent = result.anchor ? spoken(result.anchor) : "anchor";
  anchorLabel.dataset.chrome = "the date the forecast was made";
  svg.append(anchorLabel);

  const labels = scenarioLabels(curves, { x: x1 + 10, y, h });
  svg.append(labels);

  // -- the travelling dots: one along the closes, three along the scenarios --
  const dots = svgNode("g", { class: "anl-dots" });
  const lead = svgNode("circle", { class: "anl-dot", "data-scenario": "history", r: DOT_R, cx: today, cy: y(result.spot) });
  lead.setAttribute("visibility", "hidden");
  const heads = drawn.map((curve) => {
    const [ex, ey] = curve.points.at(-1);
    return svgNode("circle", { class: "anl-dot", "data-scenario": curve.name, r: DOT_R, cx: ex, cy: ey });
  });
  dots.append(lead, ...heads);
  svg.append(dots);

  // -- the crosshair ---------------------------------------------------------
  const cross = svgNode("g", { class: "anl-cross" });
  const rule = svgNode("line", { class: "anl-cross-rule", x1: 0, x2: 0, y1: PAD.top, y2: H - PAD.bottom });
  const dot = svgNode("circle", { class: "anl-cross-dot", cx: 0, cy: 0, r: 3 });
  cross.append(rule, dot);
  svg.append(cross);
  const catcher = svgNode("rect", {
    class: "anl-catch", x: x0, y: PAD.top, width: x1 - x0, height: H - PAD.top - PAD.bottom,
  });
  svg.append(catcher);

  const wrap = el("div", "anl-fan-wrap");
  const tip = el("div", "anl-tip");
  tip.setAttribute("aria-hidden", "true");
  wrap.append(svg, tip);
  host.append(wrap);

  const reading = { result, history, sessions, levels: fan?.levels ?? [], h, today, x0, x1, xh, xf, y };
  catcher.addEventListener("pointermove", (event) => point(event, svg, reading, { cross, rule, dot, tip, wrap }));
  catcher.addEventListener("pointerleave", () => { wrap.dataset.pointing = "false"; });

  host.append(fanKey(result, fan, history, h));
  host.append(readout(result, paths));

  if (opening) travel({ reveal, pastReveal, labels, lead, heads, pastLine, drawn, x0, today, x1 });
  return svg;
}

/** The change of scale, drawn where it happens.

    The axis is broken at the anchor — the baseline stops short on each side and
    two slanted strokes cross the gap, the mark a reader already knows means "the
    scale is not continuous here" — and each side is captioned with what it shows.
    Said on the chart itself, because a reader looks at the fan before the legend
    and would otherwise read a session on the right as the same width as one on
    the left. */
function scaleBreak({ x0, x1, today, h, closes }) {
  const group = svgNode("g", { class: "anl-break" });
  const base = H - PAD.bottom;
  const gap = 7;
  group.append(
    svgNode("line", { class: "anl-baseline", x1: x0, x2: today - gap, y1: base, y2: base }),
    svgNode("line", { class: "anl-baseline", x1: today + gap, x2: x1, y1: base, y2: base }),
  );
  for (const dx of [-3, 3]) {
    group.append(svgNode("line", {
      class: "anl-break-mark",
      x1: today + dx - 3, x2: today + dx + 3, y1: base + 6, y2: base - 6,
    }));
  }
  const caption = (text, x, anchor, why) => {
    const node = svgNode("text", { class: "anl-scale-caption", x, y: PAD.top - 14, "text-anchor": anchor });
    node.textContent = text;
    node.dataset.chrome = why;
    return node;
  };
  group.append(
    caption(`← last ${closes} closes`, today - 10, "end", "how many closes the history side shows"),
    caption(
      `${h} ${h === 1 ? "session" : "sessions"} ahead, drawn wider →`,
      today + 10,
      "start",
      "how many sessions the forecast side shows, and that its scale is wider",
    ),
  );
  return group;
}

/** Names and weights at the end of each curve, pushed apart where they would
    collide. Weight is the model's own number, so it is a figure; the name is a
    label. */
function scenarioLabels(curves, { x, y, h }) {
  const group = svgNode("g", { class: "anl-plabels" });
  const ends = curves
    .map((c) => ({ curve: c, at: y(c.points.find(([t]) => t === h)?.[1] ?? c.points.at(-1)[1]) }))
    .sort((a, b) => a.at - b.at);
  const gap = 16;
  for (let i = 1; i < ends.length; i++) {
    if (ends[i].at - ends[i - 1].at < gap) ends[i].at = ends[i - 1].at + gap;
  }
  for (const { curve, at } of ends) {
    const text = svgNode("text", { class: "anl-plabel", x, y: at + 4, "data-scenario": curve.name });
    const name = svgNode("tspan");
    name.textContent = `${LABELS[curve.name] ?? curve.name} `;
    name.dataset.chrome = "a scenario name";
    const weight = svgNode("tspan", { class: "anl-pweight" });
    weight.textContent = `${Math.round(curve.weight * 100)}%`;
    weight.dataset.prov = DERIVED;
    text.append(name, weight);
    group.append(text);
  }
  return group;
}

/** The reading under the pointer: a date and a close behind the anchor, a session
    and the band levels ahead of it. Every number is a figure, marked as the rest
    of the page marks them. */
function point(event, svg, r, { cross, rule, dot, tip, wrap }) {
  const box = svg.getBoundingClientRect?.();
  if (!box || !box.width) return;
  const sx = ((event.clientX - box.left) / box.width) * W;
  let x;
  let at;
  tip.textContent = "";
  const spot = figure(r.result.spot, MEASURED, "price");
  if (r.history.length > 1 && sx < r.today - 1) {
    const i = Math.max(0, Math.min(r.history.length - 1, Math.round(((sx - r.x0) / (r.today - r.x0)) * (r.history.length - 1))));
    const [date, close] = r.history[i];
    x = r.xh(i);
    at = r.y(close);
    tip.append(
      chrome(el("div", "anl-tip-head", spoken(date)), "a trading date"),
      line("close", renderFigure(figure(close, MEASURED, "price"))),
    );
  } else {
    const t = Math.max(0, Math.min(r.h, Math.round(((sx - r.today) / (r.x1 - r.today)) * r.h)));
    const s = r.sessions.reduce((best, c) => (Math.abs(c.session - t) < Math.abs(best.session - t) ? c : best));
    x = r.xf(s.session);
    if (s.session === 0) {
      at = r.y(r.result.spot);
      tip.append(
        chrome(el("div", "anl-tip-head", `anchor · ${r.result.anchor ? spoken(r.result.anchor) : ""}`), "the date the forecast was made"),
        line("price", renderFigure(spot)),
      );
    } else {
      const ahead = r.result.anchor ? ` · ≈ ${spoken(weekdaysAfter(r.result.anchor, s.session))}` : "";
      tip.append(chrome(
        el("div", "anl-tip-head", `+${s.session} ${s.session === 1 ? "session" : "sessions"}${ahead}`),
        "sessions ahead, and the weekday they would fall on",
      ));
      const q = (level) => {
        const i = r.levels.findIndex((l) => Math.abs(l - level) < 1e-9);
        return i < 0 ? null : s.prices[i];
      };
      const median = q(0.5);
      at = r.y(median ?? s.prices[Math.floor(s.prices.length / 2)]);
      if (median !== null) tip.append(line("median", renderFigure(derive(median, "price", spot))));
      for (const [label, lo, hi] of [["50%", 0.25, 0.75], ["80%", 0.1, 0.9], ["90%", 0.05, 0.95]]) {
        const a = q(lo);
        const b = q(hi);
        if (a === null || b === null) continue;
        tip.append(line(label, renderFigure(derive(a, "price", spot)), chromeText(" – ", "a range"), renderFigure(derive(b, "price", spot))));
      }
    }
  }
  rule.setAttribute("x1", x);
  rule.setAttribute("x2", x);
  dot.setAttribute("cx", x);
  dot.setAttribute("cy", at);
  wrap.dataset.pointing = "true";
  // Beside the pointer, flipped to the left of it past the middle of the chart.
  const left = (x / W) * 100;
  tip.style.left = left > 60 ? "auto" : `calc(${left}% + 14px)`;
  tip.style.right = left > 60 ? `calc(${100 - left}% + 14px)` : "auto";
  tip.style.top = `${(Math.max(PAD.top, at - 30) / H) * 100}%`;
}

function line(label, ...parts) {
  const row = el("div", "anl-tip-row");
  row.append(chromeText(label, "what the value beside it is"), el("span", "anl-tip-gap", " "), ...parts);
  return row;
}

/** Open the fan once, from the anchor outward. Decoration: if anything here is
    missing — no animation frame, a reader who asked for less motion — the fan is
    already fully drawn and this simply does nothing. */
/** The dot's journey, on load: along the closes to the anchor, drawing them
    behind it, then three dots out along the scenarios side by side, the fan
    opening with them, to rest on the three endpoints. Timed from when it began,
    and a frame stamped before that is clamped rather than run backwards. */
function travel({ reveal, pastReveal, labels, lead, heads, pastLine, drawn, x0, today, x1 }) {
  if (prefersReducedMotion() || typeof requestAnimationFrame !== "function") return;
  const ease = (x) => (1 - Math.cos(Math.PI * Math.min(1, Math.max(0, x)))) / 2;
  const place = (dot, x, yy) => {
    dot.setAttribute("cx", x.toFixed(2));
    dot.setAttribute("cy", yy.toFixed(2));
  };
  const legOne = pastLine.length ? HISTORY_MS : 0;
  reveal.setAttribute("width", "0");
  if (legOne) {
    pastReveal.setAttribute("width", "0");
    lead.setAttribute("visibility", "visible");
    place(lead, x0, pastLine[0][1]);
  }
  for (const head of heads) head.setAttribute("visibility", "hidden");
  labels.style.opacity = "0";
  const start = performance.now();
  const step = (now) => {
    const elapsed = Math.max(0, now - start);
    if (elapsed < legOne) {
      const x = x0 + ease(elapsed / legOne) * (today - x0);
      pastReveal.setAttribute("width", String(x + 1));
      place(lead, x, yAt(pastLine, x));
      requestAnimationFrame(step);
      return;
    }
    pastReveal.setAttribute("width", String(today + 1));
    lead.setAttribute("visibility", "hidden");
    const k = Math.min(1, (elapsed - legOne) / FORECAST_MS);
    const x = today + ease(k) * (x1 - today);
    reveal.setAttribute("width", String(Math.max(0, x - today) + 1));
    heads.forEach((head, i) => {
      head.setAttribute("visibility", "visible");
      place(head, x, yAt(drawn[i].points, x));
    });
    if (k < 1) {
      requestAnimationFrame(step);
    } else {
      labels.style.transition = "opacity 300ms ease-out";
      labels.style.opacity = "1";
    }
  };
  requestAnimationFrame(step);
}

/** What the shading is, what the two sides of the anchor are, and what the
    dates ahead can and cannot know. */
function fanKey(result, fan, history, h) {
  const key = el("div", "anl-band-key");
  if (fan) {
    const n = fan.levels.length;
    const pairs = Math.floor(n / 2);
    const width = (i) => Math.round((fan.levels[n - 1 - i] - fan.levels[i]) * 100);
    const shade = el("p");
    shade.append(chromeText(
      pairs > 2
        ? `Shaded: the middle ${width(pairs - 1)}% of the forecast, strongest, out to the middle ${width(0)}%, in ${pairs} steps.`
        : `Shaded: the middle ${width(0)}% and ${width(pairs - 1)}% of the forecast.`,
      "what the shaded region is",
    ));
    shade.append(chromeText(
      result.corrected
        ? " The fitted correction widened this. It was fitted at the horizon; between the anchor and the horizon it is carried in proportion."
        : " This raw width was measured too narrow.",
      "whether the correction was applied to this band",
    ));
    key.append(shade);
  }
  const sides = el("p");
  if (history.length > 1) {
    sides.append(chromeText(
      `Left of the anchor: the last ${history.length} closes. Right of it: ${h} sessions ahead, drawn wider so the fan can be read.`
      + " Dates ahead count weekdays and do not know market holidays.",
      "the two scales either side of the anchor",
    ));
  } else if (result.history_why) {
    sides.append(chromeText(`No price history before the anchor: ${result.history_why}.`, "why no history is drawn"));
  }
  if (sides.children.length) key.append(sides);
  return key;
}

/** The numbers under the fan, each as a marked figure. */
function readout(result, paths) {
  const table = el("table", "anl-table");
  const head = el("tr");
  for (const heading of ["Scenario", "Weight", "Return", "Price"]) {
    head.append(chrome(el("th", null, heading), "a column heading"));
  }
  table.append(head);

  const spot = figure(result.spot, MEASURED, "price");
  for (const path of paths) {
    const row = el("tr");
    row.append(chrome(el("td", "anl-name", LABELS[path.name] ?? path.name), "a scenario name"));
    row.append(cell(figure(path.weight, DERIVED, "weight")));
    row.append(cell(figure(path.priceReturn, DERIVED, "pctSigned")));
    row.append(cell(derive(path.price, "price", spot)));
    table.append(row);
  }
  return table;
}

function cell(fig) {
  const td = el("td");
  td.append(renderFigure(fig));
  return td;
}

/** The marking itself: what this fan is, and every reason it is not the other
    thing. Rendered beside the fan rather than under the fold. */
export function renderMarking(host, result) {
  host.textContent = "";
  const box = el("div", "anl-marking");
  box.dataset.calibration = result.marking;

  if (result.corrected) {
    box.append(chrome(el("p", "anl-mark-head", "Corrected fan"), "the state of this fan"));
    box.append(chrome(
      el("p", null,
        "The fitted correction was applied: five sessions, anchored within one trading " +
        "day of the filing, and a company the corpus filters would accept."),
      "the three conditions of ADR 0036",
    ));
    box.append(chrome(
      el("p", "anl-mark-caveat",
        "Still not a calibrated fan. This company is outside the frozen corpus, and the " +
        "correction's out-of-sample evidence is about the panel rather than about " +
        "arbitrary tickers. The conditions make applying it defensible, not verified."),
      "what a corrected fan does not claim",
    ));
  } else {
    box.append(chrome(el("p", "anl-mark-head", "Raw fan — uncalibrated"), "the state of this fan"));
    box.append(chrome(
      el("p", null,
        "The fitted correction was not applied, so this is the raw model output — which " +
        "is the version measured too narrow."),
      "what a raw fan is",
    ));
    const list = el("ul", "anl-reasons");
    for (const reason of result.reasons ?? []) {
      list.append(chrome(el("li", null, reason), "a condition that was not met"));
    }
    box.append(list);
  }
  host.append(box);
  return box;
}
