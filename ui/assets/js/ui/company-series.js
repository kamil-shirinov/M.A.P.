/* Section 3 — the price series, and when runs opened.

   A TIMELINE, not a forecast chart. Closes only: the export carries `[date,
   close]` pairs and no OHLC, so there is no candle to draw. No cone, because the
   page shows runs that already closed.

   THE Y-AXIS, AND WHY IT IS HERE NOW. This file used to carry a comment refusing
   one: "a tick this code invented would be a figure with no provenance". That was
   right when the series was a fixture. It is not right now — the closes are real,
   read from `prices/<TICKER>.json`, so a level between the lowest and the highest
   of them is COMPUTED FROM MEASURED INPUTS, which is exactly what `derived`
   means. The ticks carry the dotted mark like every other derived figure, and the
   reader can see that the page chose them.

   Without an axis the chart said only "the shape went like this". With one it
   says what the company was worth, which is most of why anyone opens it.

   A RUN IS A SEGMENT, NOT A FULL-HEIGHT LINE. A run spans from its anchor close
   to its outcome close; a line from the top of the plot to the bottom asserts
   nothing about either and covered the series it was drawn over. The segment is
   the run: where it opened, where it closed, and the slope between them. A run
   whose window is still open has no end point, so it gets a short stub at the
   anchor and nothing else. */

import { DERIVED, chromeText, figure, renderFigure, MEASURED } from "../lib/figure.js";
import { DRIFT_CAUSES, isAbsent } from "../data/source.js";
import { draw, prefersReducedMotion } from "../lib/motion.js";

const NS = "http://www.w3.org/2000/svg";
const W = 960;
const H = 260;
// Left padding holds the price labels; bottom holds the dates.
const PAD = { top: 14, right: 14, bottom: 24, left: 60 };

const svgEl = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  return n;
};

export function renderSeries(root, { series, runs, title = "Price series and when runs opened" }) {
  root.textContent = "";
  root.append(header(series, title));

  if (isAbsent(series)) {
    root.append(absence(series.why));
    return;
  }

  const rows = Object.values(runs.bySource).flatMap((r) => r);
  const drawn = [];
  root.append(plot(series, rows, drawn));
  // A key to run marks on a chart that has none would describe nothing on it.
  if (rows.length) root.append(legend(rows));
  // Now in the document, so the paths have a length.
  for (const path of drawn) draw(path, { duration: 600 });
}

function header(series, title) {
  const h = document.createElement("div");
  h.className = "cmp-series-head";
  h.append(Object.assign(document.createElement("h2"), { className: "cmp-h", textContent: title }));
  if (isAbsent(series)) return h;

  const right = document.createElement("div");
  right.className = "cmp-series-meta";
  right.append(
    document.createTextNode("last close "),
    renderFigure(series.last_close),
    document.createTextNode(" on "),
    chromeText(series.last_close_date, "the trading date of the last close"),
    document.createTextNode(" · "),
    /* A served series is not a snapshot anyone can re-read: it is what the
       provider said today, through this machine's cache. The label says which,
       because "snapshot" beside it would claim a pin that does not exist. */
    series.served
      ? chromeText(`fetched ${series.fetched_on} by this machine`, "the day the local server fetched this series")
      : chromeText(`${series.snapshot} snapshot`, "the pinned price vintage"),
  );
  h.append(right);
  return h;
}

function absence(why) {
  const p = document.createElement("p");
  p.className = "cmp-absent";
  p.dataset.chrome = "no series for this company in this snapshot";
  p.textContent = why;
  return p;
}

/** Round levels spanning the data, 4 or 5 of them.

    A "nice" step — 1, 2 or 5 times a power of ten — so the labels read as prices
    a person would say out loud rather than as arbitrary slices of the range. */
function ticks(lo, hi, target = 4) {
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

function plot(series, rows, drawn) {
  const bars = series.sessions;
  const closes = bars.map((b) => b[1]);
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const span = hi - lo || 1;
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const index = new Map(bars.map((b, i) => [b[0], i]));
  const x = (i) => PAD.left + (i / Math.max(bars.length - 1, 1)) * innerW;
  const y = (v) => PAD.top + innerH - ((v - lo) / span) * innerH;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, class: "cmp-plot", role: "img",
    "aria-label": `Closing prices for ${series.ticker}, ${bars[0][0]} to ${bars.at(-1)[0]}, with each run drawn from its anchor to its outcome`,
  });

  /* The axis first, behind everything. Each level is a figure the page computed
     from the measured closes, so it is marked derived and the legend says what
     that mark means. */
  const axis = svgEl("g", { class: "cmp-axis" });
  for (const level of ticks(lo, hi)) {
    const ly = y(level);
    axis.append(svgEl("line", { class: "cmp-grid", x1: PAD.left, x2: W - PAD.right, y1: ly, y2: ly }));
    const label = svgEl("text", { class: "cmp-ytick", x: PAD.left - 8, y: ly + 3.5, "text-anchor": "end" });
    label.dataset.prov = DERIVED;
    label.textContent = level.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    axis.append(label);
  }
  svg.append(axis);

  const line = svgEl("path", {
    class: "cmp-line",
    d: bars.map((b, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(b[1]).toFixed(2)}`).join(" "),
  });
  svg.append(line);
  // Drawn after mounting: a detached path has no length. 600ms is the one
  // exception to --dur-3 in the motion spec — this line is two years long and
  // at 400ms it reads as a flicker rather than as a series being laid down.
  drawn.push(line);

  /* Each run as the segment it actually spans. The markers arrive after the line
     has been laid down: they mark points ON it, and appearing first would make
     them look like the subject. */
  const marks = svgEl("g", { class: "cmp-marks" });
  const runAt = new Map();
  for (const run of rows) {
    const ai = index.get(run.anchor_date);
    if (ai === undefined) continue;  // every anchor is on its series today; this is not assumed
    const ax = x(ai);
    const ay = y(bars[ai][1]);

    const drifted = !isAbsent(run.anchor_drift);
    const openWindow = run.outcome_status === "window_open";
    const cls = drifted ? "cmp-anchor cmp-anchor--drift"
      : openWindow ? "cmp-anchor cmp-anchor--open"
      : "cmp-anchor";

    const oi = isAbsent(run.outcome) ? undefined : index.get(run.outcome.trading_date);
    if (oi === undefined) {
      // No outcome to reach: a stub at the anchor, not a line to nowhere.
      marks.append(svgEl("line", { class: `${cls} cmp-stub`, x1: ax, x2: ax, y1: ay - 10, y2: ay + 10 }));
    } else {
      marks.append(svgEl("line", {
        class: `${cls} cmp-span`, x1: ax, y1: ay, x2: x(oi), y2: y(bars[oi][1]),
      }));
      marks.append(svgEl("circle", { class: "cmp-dot cmp-dot--outcome", cx: x(oi), cy: y(bars[oi][1]), r: 3.5 }));
    }
    marks.append(svgEl("circle", { class: `${cls} cmp-dot`, cx: ax, cy: ay, r: 3 }));
    runAt.set(ai, [...(runAt.get(ai) ?? []), run]);
  }
  svg.append(marks);

  const wrap = document.createElement("div");
  wrap.className = "cmp-plot-wrap";
  wrap.append(svg, axisDates(bars));
  attachCrosshair(wrap, svg, { bars, x, y, index, runAt, innerH });
  return wrap;
}

/** The crosshair, and the readout it drives.

    Pointer position maps to a session by nearest index, so the line snaps to a
    trading day rather than floating between two. Every number in the readout
    goes through `renderFigure`, so the same marks apply here as anywhere else —
    a close is measured, a realised return is derived, and a re-based run shows
    its ratio instead of a return it cannot honestly state. */
function attachCrosshair(wrap, svg, ctx) {
  const { bars, x, y, index, runAt, innerH } = ctx;

  const hair = svgEl("g", { class: "cmp-hair", "aria-hidden": "true" });
  const vline = svgEl("line", { class: "cmp-hair-line", y1: PAD.top, y2: PAD.top + innerH });
  const dot = svgEl("circle", { class: "cmp-hair-dot", r: 3.5 });
  hair.append(vline, dot);
  svg.append(hair);

  const read = document.createElement("div");
  read.className = "cmp-read";
  wrap.append(read);

  const hide = () => { wrap.dataset.hover = "false"; read.textContent = ""; };
  hide();

  const show = (i, clientX) => {
    const [date, close] = bars[i];
    const px = x(i);
    vline.setAttribute("x1", px); vline.setAttribute("x2", px);
    dot.setAttribute("cx", px); dot.setAttribute("cy", y(close));
    wrap.dataset.hover = "true";

    read.textContent = "";
    const head = document.createElement("div");
    head.className = "cmp-read-head";
    head.append(
      chromeText(date, "the session under the pointer"),
      renderFigure(figure(close, MEASURED, "price")),
    );
    read.append(head);

    for (const run of runAt.get(i) ?? []) {
      const row = document.createElement("div");
      row.className = "cmp-read-run";
      row.append(chromeText(run.run_id.slice(0, 8), "an abbreviated run id"));
      row.append(document.createTextNode(" anchor "));
      row.append(renderFigure(run.anchor_spot));
      if (isAbsent(run.outcome)) {
        row.append(document.createTextNode(" · window open"));
      } else {
        row.append(document.createTextNode(" → "));
        row.append(renderFigure(run.outcome.close));
        if (isAbsent(run.anchor_drift)) {
          row.append(document.createTextNode(" · "));
          row.append(renderFigure(run.outcome.realised_log_return));
        } else {
          // The drift rule, here too: a realised return would divide a
          // split-adjusted close by an unadjusted spot.
          row.append(document.createTextNode(" · "));
          row.append(chromeText("×", "the ratio the snapshot moved by"));
          row.append(renderFigure(run.anchor_drift.ratio));
        }
      }
      read.append(row);
    }
    // Keep the readout inside the plot rather than off its right edge.
    const box = wrap.getBoundingClientRect();
    const at = clientX - box.left;
    read.style.left = `${Math.min(Math.max(at, 8), box.width - 8)}px`;
    read.dataset.flip = String(at > box.width * 0.6);
  };

  const nearest = (event) => {
    const box = svg.getBoundingClientRect();
    if (!box.width) return null;
    const vx = ((event.clientX - box.left) / box.width) * W;
    const t = (vx - PAD.left) / (W - PAD.left - PAD.right);
    if (t < -0.02 || t > 1.02) return null;
    return Math.max(0, Math.min(bars.length - 1, Math.round(t * (bars.length - 1))));
  };

  svg.addEventListener("pointermove", (e) => {
    const i = nearest(e);
    if (i === null) hide(); else show(i, e.clientX);
  });
  svg.addEventListener("pointerleave", hide);
}

function axisDates(bars) {
  const row = document.createElement("div");
  row.className = "cmp-plot-dates";
  row.append(
    chromeText(bars[0][0], "first session on the chart"),
    chromeText(bars.at(-1)[0], "last session on the chart"),
  );
  return row;
}

/** Only the states actually present are listed. A legend entry for something the
    page does not draw teaches a reader to look for it. */
function legend(rows) {
  const items = [
    ["cmp-line", "close"],
    ["cmp-anchor", "run, anchor to outcome"],
    ["cmp-dot--outcome", "outcome close"],
  ];
  /* Named by cause. AAPL's two marks were labelled "re-based anchor" and were
     never re-based: they were priced at 13:02 and 13:11 on a session still
     trading. One legend entry per cause actually on this page. */
  const causes = new Set(rows.filter((r) => !isAbsent(r.anchor_drift)).map((r) => r.anchor_drift.cause));
  for (const cause of causes) {
    const label = (DRIFT_CAUSES[cause] ?? DRIFT_CAUSES.unknown).short;
    items.push(["cmp-anchor--drift", cause === "corporate_action" ? "re-based anchor" : `anchor ${label}`]);
  }
  if (rows.some((r) => r.outcome_status === "window_open")) items.push(["cmp-anchor--open", "open window"]);

  const ul = document.createElement("ul");
  ul.className = "cmp-legend";
  for (const [cls, label] of items) {
    const li = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = `cmp-swatch ${cls}`;
    li.append(swatch, document.createTextNode(label));
    ul.append(li);
  }
  return ul;
}
