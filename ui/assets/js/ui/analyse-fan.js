/* The fan, and the marking that is part of drawing it.

   THE MARKING IS NOT A DECORATION ADDED AFTER. `renderFan` refuses a result that
   carries no `marking`, so there is no code path — and no earlier commit of this
   file — in which a fan reaches the screen without saying what it is. ADR 0036 §1
   is the rule; this is the place it cannot be forgotten.

   Amber keeps the one meaning it was narrowed to: a number that is not a settled
   measurement. An uncorrected fan is one, because the uncorrected fan is the one
   measured too narrow — 0.733 on development and 0.592 on the holdout, both
   intervals excluding 1.0. So the amber case is the common one here, and the
   reasons are printed rather than summarised. */

import { DERIVED, MEASURED, chrome, chromeText, derive, figure, renderFigure } from "../lib/figure.js";

const SVG = "http://www.w3.org/2000/svg";
const W = 760;
const H = 300;
const PAD = { top: 18, right: 96, bottom: 28, left: 64 };

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
function ticks(lo, hi, target = 4) {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

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

const LABELS = { bullish: "Bullish", base_case: "Base case", bearish: "Bearish" };

/** The fan. Throws rather than drawing an unmarked one. */
export function renderFan(host, result) {
  host.textContent = "";
  if (!result || typeof result.marking !== "string") {
    // Loudly, because the failure this prevents is a fan that looks settled.
    throw new Error("a fan cannot be drawn without its marking");
  }

  const paths = endpoints(result);
  const prices = [
    result.spot,
    ...paths.map((p) => p.price),
    // The band is usually wider than the scenarios, so the axis has to cover it
    // or the ribbon is clipped at the frame and reads as narrower than it is.
    ...(Array.isArray(result.band) ? result.band.map((b) => b.price) : []),
  ];
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  const pad = (hi - lo) * 0.18 || Math.max(1, result.spot * 0.02);
  const top = hi + pad;
  const bottom = lo - pad;

  const x0 = PAD.left;
  const x1 = W - PAD.right;
  const y = (price) =>
    PAD.top + ((top - price) / (top - bottom)) * (H - PAD.top - PAD.bottom);

  const svg = svgNode("svg", {
    viewBox: `0 0 ${W} ${H}`,
    class: "anl-fan",
    role: "img",
    "aria-label": `Three scenarios for ${result.ticker} over ${result.horizon_days} sessions`,
  });
  // The whole figure carries the marking, so a screenshot of it is marked too.
  svg.dataset.calibration = result.marking;

  for (const level of ticks(bottom, top)) {
    svg.append(svgNode("line", {
      class: "anl-grid", x1: x0, x2: x1, y1: y(level), y2: y(level),
    }));
    const text = svgNode("text", { class: "anl-ytick", x: x0 - 8, y: y(level) + 4 });
    text.textContent = level.toFixed(2);
    text.dataset.prov = DERIVED;
    svg.append(text);
  }

  /* THE BAND, behind the lines. It is what M.A.P. actually forecasts: the three
     scenarios are the shape of the reasoning, and the width is the claim. Drawn
     first so the lines sit on top of it, and drawn from quantiles the server took
     off the same simulation the scorer would score — not re-derived here from the
     three endpoints, which would be a second, prettier distribution.

     When the correction applies the server has already widened these, so a
     corrected band is visibly wider than its raw twin. That difference is the
     reason the band exists at all. */
  const band = Array.isArray(result.band) ? result.band : [];
  if (band.length >= 2) {
    const sorted = [...band].sort((a, b) => a.level - b.level);
    // Pairs from the outside in, so the inner ribbon overlays the outer one.
    for (let i = 0; i < Math.floor(sorted.length / 2); i++) {
      const lo = sorted[i];
      const hi = sorted[sorted.length - 1 - i];
      const area = svgNode("path", {
        class: "anl-band",
        d: `M${x0} ${y(result.spot)} Q${(x0 + x1) / 2} ${(y(result.spot) + y(hi.price)) / 2} ${x1} ${y(hi.price)}`
          + ` L${x1} ${y(lo.price)} Q${(x0 + x1) / 2} ${(y(result.spot) + y(lo.price)) / 2} ${x0} ${y(result.spot)} Z`,
      });
      area.dataset.level = String(Math.round((hi.level - lo.level) * 100));
      svg.append(area);
    }
  }

  // The anchor: one measured price, which is the only measured number on the
  // chart. Everything to the right of it is a statement about the future.
  svg.append(svgNode("line", {
    class: "anl-anchor", x1: x0, x2: x0, y1: PAD.top, y2: H - PAD.bottom,
  }));
  svg.append(svgNode("circle", { class: "anl-spot", cx: x0, cy: y(result.spot), r: 3.5 }));

  for (const path of paths) {
    const target = y(path.price);
    // A quadratic, not a straight line: the spread opens over the horizon rather
    // than being a ruler drawn between two points.
    const d = `M${x0} ${y(result.spot)} Q${(x0 + x1) / 2} ${(y(result.spot) + target) / 2} ${x1} ${target}`;
    const line = svgNode("path", { class: "anl-path", d, "data-scenario": path.name });
    // Weight drives opacity, so the likely path reads as the likely one without
    // a legend having to say so.
    line.style.opacity = String(0.35 + path.weight * 0.65);
    svg.append(line);

    const label = svgNode("text", { class: "anl-plabel", x: x1 + 8, y: target + 4 });
    label.textContent = LABELS[path.name] ?? path.name;
    label.dataset.chrome = "a scenario name";
    svg.append(label);
  }

  host.append(svg);
  /* The band needs naming. Shading with no legend is a region a reader has to
     guess at, and the guess available is "the scenarios", which it is not: the
     ribbons are quantiles of the whole predictive distribution and the lines are
     three points inside it. */
  if (band.length >= 2) host.append(bandLegend(band, result));
  host.append(readout(result, paths));
  return svg;
}

/** What the shading is, in one line. */
function bandLegend(band, result) {
  const sorted = [...band].sort((a, b) => a.level - b.level);
  const span = (lo, hi) => Math.round((hi.level - lo.level) * 100);
  const line = el("p", "anl-band-key");
  line.append(chromeText(
    `Shaded: the middle ${span(sorted[0], sorted.at(-1))}% and ${span(sorted[1], sorted.at(-2))}% `
    + "of the forecast.",
    "what the shaded region is",
  ));
  line.append(chromeText(
    result.corrected
      ? " The fitted correction widened this."
      : " This raw width was measured too narrow.",
    "whether the correction was applied to this band",
  ));
  return line;
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
