/* The PIT histogram, and the four figures that say what it means.

   PIT = Phi((realised - forecast mean) / sigma): where the outcome fell inside
   the forecast. Under a calibrated forecaster these are uniform, and the SHAPE
   of the departure is the diagnostic — U-shaped means too narrow, humped means
   too wide, tilted means the centre is off.

   THE BARS ARE A PICTURE, NOT EVIDENCE. Ten bins give ten chances to look
   extreme and the eye goes to whichever one did. The uniform line is drawn so
   the reader can see the reference rather than infer it, and the claim is made
   by the four figures below, which were named before the bars were looked at.

   Z IS Phi^-1(PIT). Not realised/sigma — see lib/gaussian.js. The two differ on
   this record (11 against 13 over 2.5) and only one of them is the statistic the
   project pre-registered and published. */

import { DERIVED, chromeText, figure, renderFigure } from "../lib/figure.js";

const NS = "http://www.w3.org/2000/svg";
const W = 620, H = 210;
/* The right margin holds the uniform line's label. Inside the plot it landed on
   whichever bar was tallest at that end — on this record, the 20 in the last
   bin — and two numbers on top of each other is worse than no label. */
const PAD = { t: 22, r: 74, b: 26, l: 30 };

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

export function renderPit(root, { stats, pending }) {
  root.textContent = "";
  const card = el("section", "res-card res-pit");
  const head = el("header");
  head.append(el("h2", null, "PIT"), el("span", "res-note", "where the outcome fell inside the forecast"));
  card.append(head);

  card.append(stats ? chart(stats) : waiting(pending));
  card.append(figures(stats));
  root.append(card);
  return card;
}

function chart(stats) {
  const counts = stats.histogram;
  const expected = stats.n / stats.bins;
  // Headroom above whichever is taller, so the uniform line never sits on the
  // frame and a bar that beats it is visibly above it rather than clipped.
  const yMax = Math.max(expected, ...counts) * 1.14;

  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const x = (i) => PAD.l + (i / counts.length) * plotW;
  const y = (v) => PAD.t + (1 - v / yMax) * plotH;
  const barW = (plotW / counts.length) * 0.82;

  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "res-chart", role: "img" });
  s.setAttribute("aria-label", `PIT histogram, ${stats.bins} bins over ${stats.n} items`);

  s.append(svg("line", { x1: PAD.l, y1: y(0), x2: W - PAD.r, y2: y(0), class: "res-axis" }));

  for (const [i, count] of counts.entries()) {
    const left = x(i) + (plotW / counts.length - barW) / 2;
    s.append(svg("rect", { x: left, y: y(count), width: barW, height: Math.max(y(0) - y(count), 0.5), class: "res-bar" }));
    s.append(tick(left + barW / 2, y(count) - 5, String(count)));
  }

  // Drawn last so it sits over the bars: it is the reference they are read
  // against, and a uniform line hidden behind the tallest bar is no reference.
  s.append(svg("line", { x1: PAD.l, y1: y(expected), x2: W - PAD.r, y2: y(expected), class: "res-uniform" }));
  s.append(tick(W - PAD.r + 6, y(expected) + 3, `uniform ${expected.toFixed(1)}`, "start"));

  for (const at of [0, 0.5, 1]) s.append(tick(PAD.l + at * plotW, H - 8, String(at)));
  return s;
}

/** The four statistics, each with the definition it was computed under.

    The tail counts name their sample. "13" and "11" are two definitions of z on
    the same items, and "11 on 175" and "11 on 178" are the same definition on
    two samples; an unlabelled count is a contradiction waiting to be found. */
function figures(stats) {
  const grid = el("dl", "res-figs");
  /* Both the label and its note are marked chrome with a reason. "|z| > 2.5" and
     "1.0 is calibrated" carry digits that are thresholds and definitions, not
     measurements, and the audit is given nothing to guess with. */
  const row = (label, note, node) => {
    const dt = el("dt");
    const l = chromeText(label, "the name of the statistic; any digits in it are a threshold");
    l.className = "res-fig-label";
    const n = chromeText(note, "the definition the statistic was computed under");
    n.className = "res-fig-note";
    dt.append(l, n);
    const dd = el("dd");
    dd.append(node);
    grid.append(dt, dd);
  };
  const value = (v, format) => (stats ? renderFigure(figure(v, DERIVED, format)) : chromeText("…", "the record is still being read"));

  row("Calibration ratio", "RMS(sigma) ÷ RMS(realised); 1.0 is calibrated", value(stats?.calibrationRatio, "ratio3"));
  row("PIT mean", "0.5 under a centred forecast", value(stats?.pitMean, "ratio3"));

  for (const threshold of [2.5, 3]) {
    const dd = el("span", "res-tail");
    if (stats) {
      dd.append(
        renderFigure(figure(stats.tails[threshold], DERIVED, "int")),
        el("span", "res-fig-of", " of "),
        renderFigure(figure(stats.zn, DERIVED, "int")),
        el("span", "res-fig-of", ", in "),
        renderFigure(figure(stats.tailBlocks[threshold], DERIVED, "int")),
        el("span", "res-fig-of", " blocks"),
      );
    } else {
      dd.append(chromeText("…", "the record is still being read"));
    }
    row(`|z| > ${threshold}`, "z = Φ⁻¹(PIT), the definition the record was published under", dd);
  }
  /* Stated, not silently absorbed into a smaller denominator: if some items had
     no finite z, the tail counts above are over fewer items than the record
     holds and the difference is the reader's to see. */
  if (stats?.zUndefined) {
    const dt = el("dt");
    const l = chromeText("not standardisable", "why some items are outside the tail counts");
    l.className = "res-fig-label";
    const note = chromeText("PIT at 0 or 1 — the outcome fell outside every path, so z is undefined", "the reason z cannot be formed");
    note.className = "res-fig-note";
    dt.append(l, note);
    const dd = el("dd");
    dd.append(renderFigure(figure(stats.zUndefined, DERIVED, "int")));
    grid.append(dt, dd);
  }
  return grid;
}

/* The reading line carries a file size, so it is marked chrome with the reason.
   It is the one thing on the card before the record lands, and an unmarked
   number there fires the audit on the first paint of every load. */
function waiting(text) {
  const p = chromeText(text, "a progress line; its digits are a file size");
  p.className = "res-waiting";
  return p;
}
