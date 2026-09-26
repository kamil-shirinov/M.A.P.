/* Section 3 — the price series, and when runs opened.

   A TIMELINE, not a forecast chart. Closes only: the export carries `[date,
   close]` pairs and no OHLC, so there is no candle to draw. No cone, because the
   page shows runs that already closed.

   NO Y-AXIS TICKS. An axis tick is a number on screen, and a tick this code
   invented would be a figure with no provenance — the audit would be right to
   flag it and hiding it behind `data-chrome` would be a lie. The shape carries
   the series; the last close is printed as a marked figure beside it. */

import { chromeText, figure, renderFigure, MEASURED } from "../lib/figure.js";
import { isAbsent } from "../data/source.js";
import { draw } from "../lib/motion.js";

const NS = "http://www.w3.org/2000/svg";
const W = 960;
const H = 220;
const PAD = { top: 12, right: 12, bottom: 22, left: 12 };

const svgEl = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  return n;
};

export function renderSeries(root, { series, runs }) {
  root.textContent = "";
  root.append(header(series));

  if (isAbsent(series)) {
    root.append(absence(series.why));
    return;
  }

  const rows = Object.values(runs.bySource).flatMap((r) => r);
  const drawn = [];
  root.append(plot(series, rows, drawn));
  root.append(legend(rows));
  // Now in the document, so the paths have a length.
  for (const path of drawn) draw(path, { duration: 600 });
}

function header(series) {
  const h = document.createElement("div");
  h.className = "cmp-series-head";
  h.append(Object.assign(document.createElement("h2"), { className: "cmp-h", textContent: "Price series and when runs opened" }));
  if (isAbsent(series)) return h;

  const right = document.createElement("div");
  right.className = "cmp-series-meta";
  right.append(
    document.createTextNode("last close "),
    renderFigure(series.last_close),
    document.createTextNode(" on "),
    chromeText(series.last_close_date, "the trading date of the last close"),
    document.createTextNode(" · "),
    chromeText(`${series.snapshot} snapshot`, "the pinned price vintage"),
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
    "aria-label": `Closing prices for ${series.ticker} with a tick where each run opened`,
  });

  const line = svgEl("path", {
    class: "cmp-line",
    d: bars.map((b, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(b[1]).toFixed(2)}`).join(" "),
  });
  svg.append(line);
  // Drawn after mounting: a detached path has no length. 600ms is the one
  // exception to --dur-3 in the motion spec — this line is two years long and
  // at 400ms it reads as a flicker rather than as a series being laid down.
  drawn.push(line);

  for (const run of rows) {
    const ai = index.get(run.anchor_date);
    if (ai === undefined) continue;  // every anchor is on its series today; this is not assumed
    const ax = x(ai);
    const ay = y(bars[ai][1]);
    // Markers arrive after the line has been laid down: they mark points ON it,
    // and appearing first would make them look like the subject.

    const drifted = !isAbsent(run.anchor_drift);
    const openWindow = run.outcome_status === "window_open";
    const cls = drifted ? "cmp-anchor cmp-anchor--drift"
      : openWindow ? "cmp-anchor cmp-anchor--open"
      : "cmp-anchor";

    svg.append(svgEl("line", { class: cls, x1: ax, x2: ax, y1: PAD.top, y2: PAD.top + innerH }));
    svg.append(svgEl("circle", { class: `${cls} cmp-dot`, cx: ax, cy: ay, r: 3 }));

    if (!isAbsent(run.outcome)) {
      const oi = index.get(run.outcome.trading_date);
      if (oi !== undefined) {
        svg.append(svgEl("circle", {
          class: "cmp-dot cmp-dot--outcome", cx: x(oi), cy: y(bars[oi][1]), r: 3.5,
        }));
      }
    }
  }

  const wrap = document.createElement("div");
  wrap.className = "cmp-plot-wrap";
  // The only text in the plot is the first and last session date, as chrome.
  wrap.append(svg, axisDates(bars));
  return wrap;
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
    ["cmp-anchor", "run anchor"],
    ["cmp-dot--outcome", "outcome close"],
  ];
  if (rows.some((r) => !isAbsent(r.anchor_drift))) items.push(["cmp-anchor--drift", "re-based anchor"]);
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
