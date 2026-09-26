/* The leakage control, as a slope chart.

   THE QUESTION. The models were trained on text that includes what actually
   happened to well-known tickers. If M.A.P. is remembering rather than
   forecasting, it should do better on the clean band — companies whose earnings
   the training data is least likely to hold — than on the ambiguous one. Mean
   CRPS on each band, four models, two columns: a memory effect is M.A.P.'s line
   sloping differently from the three baselines'.

   BOTH BANDS ARE ALWAYS SHOWN. This is the one panel the band switch does not
   drive, because the comparison IS the two bands and a version of it showing one
   at a time is not the control.

   THE FIGURE IS DERIVED, THE INTERVAL IS QUOTED. The difference of the two means
   is arithmetic the page can do and shows its working for. The interval around
   it is in neither record — it was printed by `map evaluate` from a 2000-draw
   bootstrap and lives in the README — so it is quoted, dashed, and never
   recomputed. The agreement check compares this page's arithmetic against the
   published figure and says which it got, because a reproduction that cannot
   fail is not a reproduction. */

import { DERIVED, chromeText, figure, renderFigure } from "../lib/figure.js";
import { BASELINES } from "./results-baselines.js";
import { fmt } from "../lib/format.js";
import { draw } from "../lib/motion.js";

const NS = "http://www.w3.org/2000/svg";
const W = 560, H = 230;
/* The left margin carries the longest label the export can produce —
   "earnings scaled random walk  0.03280" — and clipping the name of the one
   baseline M.A.P. beats would be the worst label to lose. */
const PAD = { t: 18, r: 86, b: 30, l: 218 };

/* Quoted, with where each came from. Neither is in the export: the page must not
   be able to produce them by arithmetic, or the agreement check below would be
   comparing a number against itself. */
export const PUBLISHED = {
  difference: "−0.00169",
  interval: "[−0.0093, +0.0060]",
  where: "README, from `map evaluate --leakage`",
};

const el = (tag, className, text) => {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
};
const svg = (name, attrs = {}) => {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
const label = (x, y, text, anchor, cls) => {
  const t = svg("text", { x, y, "text-anchor": anchor, class: cls });
  t.dataset.chrome = "chart series label";
  t.textContent = text;
  return t;
};

export function renderLeakage(root, { clean, ambiguous, pending }) {
  root.textContent = "";
  const card = el("section", "res-card res-leakage");
  const head = el("header");
  head.append(
    el("h2", null, "Leakage control"),
    el("span", "res-note", "mean CRPS, both bands, always"),
  );
  card.append(head);

  if (!clean || !ambiguous) {
    card.append(waiting(pending));
    root.append(card);
    return card;
  }

  const drawn = [];
  card.append(slope(clean, ambiguous, drawn), verdict(clean, ambiguous));
  root.append(card);
  // Now that it is in the document the paths have a length to draw along.
  for (const line of drawn) draw(line);
  return card;
}

function series(clean, ambiguous) {
  return [
    { name: "M.A.P.", left: clean.map.crps, right: ambiguous.map.crps, lead: true },
    ...BASELINES.map((b) => ({
      name: b.replace(/_/g, " "),
      left: clean.baselines[b].crps,
      right: ambiguous.baselines[b].crps,
      lead: false,
    })),
  ];
}

function slope(clean, ambiguous, drawn) {
  const lines = series(clean, ambiguous);
  const values = lines.flatMap((l) => [l.left, l.right]);
  const min = Math.min(...values), max = Math.max(...values);
  const pad = (max - min) * 0.08 || 1;
  const y = (v) => PAD.t + (1 - (v - (min - pad)) / (max - min + 2 * pad)) * (H - PAD.t - PAD.b);
  const xL = PAD.l, xR = W - PAD.r;

  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "res-chart res-slope", role: "img" });
  s.setAttribute("aria-label", "mean CRPS for four models on the clean and ambiguous bands");

  for (const [x, text] of [[xL, "clean"], [xR, "ambiguous"]]) {
    s.append(svg("line", { x1: x, y1: PAD.t - 6, x2: x, y2: H - PAD.b + 2, class: "res-slope-rail" }));
    s.append(label(x, H - 10, text, "middle", "res-tick"));
  }

  // Baselines first, M.A.P. last: the accent line is the subject and must not be
  // crossed over by a grey one.
  for (const l of [...lines].sort((a, b) => Number(a.lead) - Number(b.lead))) {
    const cls = l.lead ? "res-slope-line res-slope-line--lead" : "res-slope-line";
    const line = svg("line", { x1: xL, y1: y(l.left), x2: xR, y2: y(l.right), class: cls });
    s.append(line);
    // Drawn after the chart is in the document: a detached path has no length.
    drawn.push(line);
    for (const [x, v] of [[xL, l.left], [xR, l.right]]) {
      s.append(svg("circle", { cx: x, cy: y(v), r: l.lead ? 4.5 : 3, class: `${cls}-dot` }));
    }
    s.append(label(xL - 8, y(l.left) + 3, `${l.name}  ${fmt.dec5(l.left)}`, "end", l.lead ? "res-slope-label res-slope-label--lead" : "res-slope-label"));
    s.append(label(xR + 8, y(l.right) + 3, fmt.dec5(l.right), "start", l.lead ? "res-slope-label res-slope-label--lead" : "res-slope-label"));
  }
  return s;
}

function verdict(clean, ambiguous) {
  const difference = clean.map.crps - ambiguous.map.crps;
  const shown = figure(difference, DERIVED, "signed5");

  const box = el("div", "res-leak-verdict");

  const big = el("p", "res-leak-figure");
  big.append(renderFigure(shown, { className: "res-leak-big" }));
  box.append(big);

  const working = el("p", "res-leak-working");
  working.append(
    renderFigure(figure(clean.map.crps, DERIVED, "dec5")),
    chromeText(" − ", "an arithmetic operator"),
    renderFigure(figure(ambiguous.map.crps, DERIVED, "dec5")),
    chromeText(" = ", "an arithmetic operator"),
    renderFigure(shown),
  );
  box.append(working);

  const quoted = el("p", "res-leak-quoted");
  const pub = chromeText(`published ${PUBLISHED.difference}`, "the figure as the README states it");
  pub.className = "res-quoted";
  const ci = chromeText(`interval ${PUBLISHED.interval}`, "the interval as the README states it; it is in neither record");
  ci.className = "res-quoted";
  quoted.append(pub, ci);
  box.append(quoted);

  /* The check. Formatted against formatted, because that is what a reader
     compares: a strict equality on the floats would fail on the last bit and
     report a disagreement nobody can see. */
  const agrees = fmt.signed5(difference) === PUBLISHED.difference;
  const note = el("p", "res-leak-check");
  note.dataset.agrees = String(agrees);
  note.textContent = agrees
    ? "agrees with the published figure"
    : "differs from the published figure — the export and the README are not the same measurement";
  box.append(note);
  return box;
}

/* The reading line carries a file size, so it is marked chrome with the reason.
   It is the one thing on the card before the record lands, and an unmarked
   number there fires the audit on the first paint of every load. */
function waiting(text) {
  const p = chromeText(text, "a progress line; its digits are a file size");
  p.className = "res-waiting";
  return p;
}
