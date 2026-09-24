/* Direction — one dot per item, and the one comparison Brier actually makes.

   WHAT THE STRIP SHOWS. Each item at x = P(up), filled when the direction was
   right. The finding is in the picture and needs no sentence: every dot sits in
   a narrow band around 0.5, so the model almost never commits to a direction,
   and the hit rate is a coin's.

   JITTER IS DETERMINISTIC. `(i * 7919) mod 101` — a prime step through a prime
   modulus, so the sequence spreads without clustering and, more importantly,
   the same item lands in the same place on every paint and in every screenshot.
   Math.random() here would make a chart that changes when nothing changed.

   BRIER IS ONE COMPARISON, NOT THREE. Every baseline predicts a zero mean, so
   each assigns P(up) = 0.5 and scores exactly 0.25 on every item whatever
   happened. Three rows would present one number as three independent results.
   The page CHECKS the claim against every item rather than asserting it, and
   says which way the check went. */

import { DERIVED, chromeText, figure, renderFigure } from "../lib/figure.js";

const NS = "http://www.w3.org/2000/svg";
const W = 620, H = 120;
const PAD = { t: 10, r: 14, b: 26, l: 14 };

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
const tick = (x, y, text, anchor = "middle") => {
  const t = svg("text", { x, y, "text-anchor": anchor, class: "res-tick" });
  t.dataset.chrome = "chart axis tick";
  t.textContent = text;
  return t;
};

export const jitter = (i) => 4 + ((i * 7919) % 101) / 101 * 74;

export function renderDirection(root, { stats, items, pending }) {
  root.textContent = "";
  const card = el("section", "res-card res-direction");
  const head = el("header");
  head.append(el("h2", null, "Direction"), el("span", "res-note", "one dot per item, at P(up)"));
  card.append(head);

  if (!stats) {
    card.append(waiting(pending));
    root.append(card);
    return card;
  }

  card.append(strip(items), range(stats), hitRate(stats), brier(stats));
  root.append(card);
  return card;
}

function strip(items) {
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "res-chart res-dots", role: "img" });
  s.setAttribute("aria-label", "every scored item at its stated probability of an upward move");
  const plotW = W - PAD.l - PAD.r;
  const x = (p) => PAD.l + p * plotW;

  s.append(svg("line", { x1: x(0.5), y1: PAD.t, x2: x(0.5), y2: H - PAD.b, class: "res-dots-half" }));
  s.append(svg("line", { x1: PAD.l, y1: H - PAD.b, x2: W - PAD.r, y2: H - PAD.b, class: "res-axis" }));

  for (const [i, item] of items.entries()) {
    const right = (item.map_probability_up > 0.5) === (item.realised_return > 0);
    s.append(svg("circle", {
      cx: x(item.map_probability_up),
      cy: PAD.t + jitter(i),
      r: 2.6,
      class: right ? "res-dot res-dot--right" : "res-dot res-dot--wrong",
    }));
  }

  for (const at of [0, 0.5, 1]) s.append(tick(x(at), H - 8, String(at)));
  return s;
}

function range(stats) {
  const p = el("p", "res-range");
  p.append(
    el("span", "res-k", "P(up) "),
    renderFigure(figure(stats.probabilityUp.min, DERIVED, "ratio3")),
    el("span", null, " to "),
    renderFigure(figure(stats.probabilityUp.max, DERIVED, "ratio3")),
  );
  return p;
}

function hitRate(stats) {
  const p = el("p", "res-hits");
  p.append(
    renderFigure(figure(stats.directionRight, DERIVED, "int"), { className: "res-hits-big" }),
    el("span", null, " of "),
    renderFigure(figure(stats.n, DERIVED, "int")),
    el("span", null, " — "),
    renderFigure(figure(stats.directionRight / stats.n, DERIVED, "pct")),
  );
  return p;
}

function brier(stats) {
  const box = el("div", "res-brier");
  const one = stats.baselineBrierIsOneComparison;

  const head = el("div", "res-brier-head");
  head.append(el("h3", null, "Brier"), chromeText("one comparison", "how many baselines this row stands for"));
  box.append(head);

  const line = el("p", "res-brier-line");
  line.append(
    el("span", "res-k", "M.A.P. "),
    renderFigure(figure(stats.map.brier, DERIVED, "dec5")),
    el("span", null, " against "),
    el("span", "res-k", "all three "),
    // Derived, not quoted: the page read every item to get it, which is the
    // whole point of the check below.
    renderFigure(figure(0.25, DERIVED, "dec5")),
  );
  box.append(line);

  const note = el("p", "res-brier-note");
  const text = one
    ? "0.25 on every item, for every baseline — computed, no line in the record"
    : "the baselines do NOT all score 0.25 on every item, so this is not one comparison and the record needs reading per baseline";
  const marked = chromeText(text, "explanatory prose; its digits are the checked constant");
  marked.className = "res-brier-note-text";
  note.dataset.check = one ? "passed" : "failed";
  note.append(marked);
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
