/* M.A.P. against three baselines, as a forest plot.

   TWO SOURCES OF TRUTH, AND THEY ARE KEPT APART.

     the POINT is derived here — mean(map_<rule>) − mean(baseline_<rule>);
     the INTERVAL is quoted, parsed out of the record's own summary string;
     the VERDICT is quoted too, read from the same string.

   The intervals come from a moving-block bootstrap whose seed, draw count and
   cluster map are not in the export. Recomputing one here would produce a
   number that looks like the published one and is not it, so nothing in this
   module computes an interval: the bar is parsed or it is not drawn.

   The verdict is taken from the string rather than from the sign of the point,
   for the same reason. "worse by 5.4%" is a claim the bootstrap licensed;
   "the point is positive" is not the same claim, and on this record three of
   the six rows have a point off zero and an interval that spans it.

   BOTH RULES ARE LOWER-IS-BETTER. The log score is stored as a negative log
   density, so −1.38 against −1.58 means M.A.P. is WORSE, and a plot that sorts
   or orients it the other way inverts the project's headline result. The rule
   tag on the log block is amber for exactly that reason — it is the guard, not
   decoration. */

import { DERIVED, chromeText, figure, renderFigure } from "../lib/figure.js";

const NS = "http://www.w3.org/2000/svg";

/* The order is the order of the argument, not of the record: the random walk is
   the baseline the README's claim names, GARCH is the harder one, and the
   earnings-scaled walk is the one M.A.P. beats. The summaries arrive sorted
   alphabetically and are matched back to these by name. */
export const BASELINES = ["random_walk", "garch", "earnings_scaled_random_walk"];

const RULES = [
  { key: "crps", label: "CRPS", field: "crps", places: "dec5", delta: "signed5",
    tag: "lower is better", tagKind: "plain" },
  { key: "log score", label: "Log score", field: "log_score", places: "dec4", delta: "signed4",
    tag: "stored lower-is-better", tagKind: "guard" },
];

const W = 320, ROW_H = 46;

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

/** The interval as the record states it. A real minus may appear in the string,
    so both signs are accepted; nothing is recomputed when it is missing. */
const INTERVAL = /\[([+\-−]?[\d.]+),\s*([+\-−]?[\d.]+)\]/;
const num = (t) => Number(t.replace("−", "-"));

export function parseSummary(line) {
  const m = INTERVAL.exec(line);
  const interval = m ? { lo: num(m[1]), hi: num(m[2]) } : null;
  // The wording, not the arithmetic. ": worse by" and ": better by" are the two
  // the aggregator emits when the interval excludes zero; everything else —
  // "indistinguishable at n=..." — is neither.
  const verdict = /:\s*worse by/.test(line) ? "worse" : /:\s*better by/.test(line) ? "better" : "neither";
  return { interval, verdict, line };
}

/** Summary lines matched back to the baseline each one is about. */
export function summaryFor(lines, baseline) {
  const line = (lines ?? []).find((l) => l.includes(`vs ${baseline}:`));
  return line ? parseSummary(line) : null;
}

/** One domain per rule, fixed across both bands, so switching band moves the
    points and never the axis. Rounded UP to one significant figure: an axis
    whose end is 0.0030564 is an axis nobody can read a tick off. */
export function domainFor(records, rule) {
  let worst = 0;
  for (const { stats, summaries } of records) {
    for (const b of BASELINES) {
      if (stats) worst = Math.max(worst, Math.abs(stats.map[rule.field] - stats.baselines[b][rule.field]));
      const parsed = summaryFor(summaries?.[rule.key], b);
      if (parsed?.interval) worst = Math.max(worst, Math.abs(parsed.interval.lo), Math.abs(parsed.interval.hi));
    }
  }
  if (!worst) return 1;
  const padded = worst * 1.08;
  const magnitude = 10 ** Math.floor(Math.log10(padded));
  // toPrecision(1) after the multiply, because 7 * 0.1 is 0.7000000000000001 in
  // binary floating point and an axis end is a label as well as a number.
  return Number((Math.ceil(padded / magnitude) * magnitude).toPrecision(1));
}

export function renderBaselines(root, { stats, summaries, domains, pending }) {
  root.textContent = "";
  const card = el("section", "res-card res-baselines");
  const head = el("header");
  head.append(
    el("h2", null, "M.A.P. against three baselines"),
    el("span", "res-note", "point derived here, interval and verdict quoted from the record"),
  );
  card.append(head);

  if (!stats) {
    card.append(waiting(pending));
    root.append(card);
    return card;
  }

  for (const rule of RULES) card.append(block(rule, stats, summaries, domains[rule.key]));
  root.append(card);
  return card;
}

function block(rule, stats, summaries, domain) {
  const box = el("div", "res-rule");
  const head = el("div", "res-rule-head");
  // The shared tag component. No tone: amber means "not a settled measurement"
  // and an instruction about reading an axis is not that, so the word carries it.
  const tag = chromeText(rule.tag, "how the rule is oriented");
  tag.className = `tag res-rule-tag res-rule-tag--${rule.tagKind}`;
  head.append(el("h3", null, rule.label), tag);
  box.append(head);

  const axis = el("div", "res-axis-row");
  axis.append(
    el("span", "res-axis-better", "← M.A.P. better"),
    el("span", "res-axis-worse", "M.A.P. worse →"),
  );
  box.append(axis);

  for (const baseline of BASELINES) {
    box.append(row(rule, baseline, stats, summaryFor(summaries?.[rule.key], baseline), domain));
  }
  return box;
}

function row(rule, baseline, stats, parsed, domain) {
  const mapMean = stats.map[rule.field];
  const baseMean = stats.baselines[baseline][rule.field];
  const point = figure(mapMean - baseMean, DERIVED, rule.delta);
  const verdict = parsed?.verdict ?? "neither";

  /* An expandable row, per the shared system §8. The record's sentence is the
     authority for the verdict and it is long — six of them stacked was most of
     this panel's height, and a reader comparing two rows had to scroll past a
     paragraph to reach the next one. Closed by default, and several can be open
     at once.

     WHAT THE CLOSED ROW MUST STILL CARRY, without the sentence and in
     greyscale: whether the interval crosses zero. It is the dashed bar against
     the zero rule, which is visible whether or not the row is open and whether
     or not the colour survives. */
  const line = el("details", "res-row row-x");
  line.dataset.verdict = verdict;
  line.dataset.baseline = baseline;

  const summary = document.createElement("summary");
  summary.append(el("span", "row-x-caret", "\u25b8"));
  summary.append(el("div", "res-row-name", baseline.replace(/_/g, " ")));
  summary.append(plot(point.value, parsed?.interval, domain, verdict));

  const means = el("div", "res-row-means");
  const deltaCell = el("span", "res-row-delta");
  deltaCell.append(renderFigure(point, { className: `res-delta res-delta--${verdict}` }));
  means.append(
    renderFigure(figure(mapMean, DERIVED, rule.places)),
    chromeText(" vs ", "a comparator"),
    renderFigure(figure(baseMean, DERIVED, rule.places)),
    deltaCell,
  );
  summary.append(means);
  line.append(summary);

  /* The record's own sentence, verbatim and full width. It is already written
     and already hedged; rewording it to fit a column is how "indistinguishable,
     and this is not evidence of no difference" becomes "no difference". */
  const body = el("div", "row-x-body");
  const said = chromeText(parsed?.line ?? "No summary line for this baseline in the record.", "the record's own summary sentence, verbatim");
  said.className = "res-row-said";
  body.append(said);
  line.append(body);
  return line;
}

function plot(point, interval, domain, verdict) {
  const host = el("div", "res-plot");
  const s = svg("svg", { viewBox: `0 0 ${W} ${ROW_H}`, class: "res-forest", role: "img" });
  s.setAttribute("aria-label", `difference against the baseline, on an axis from minus ${domain} to plus ${domain}`);
  const mid = ROW_H / 2;
  const x = (v) => (W / 2) * (1 + Math.max(-1, Math.min(1, v / domain)));

  s.append(svg("line", { x1: 0, y1: mid, x2: W, y2: mid, class: "res-forest-axis" }));
  s.append(svg("line", { x1: W / 2, y1: 6, x2: W / 2, y2: ROW_H - 6, class: "res-forest-zero" }));

  // Drawn only when the record states one. A bar the page invented would be
  // indistinguishable from a bar the bootstrap produced.
  if (interval) {
    const bar = svg("line", { x1: x(interval.lo), y1: mid, x2: x(interval.hi), y2: mid, class: `res-forest-ci enter-span res-forest-ci--${verdict}` });
    /* Extends outward FROM the point, which is the reading: the estimate is
       there and the interval is how far it could be. Scaling from the left edge
       would animate it as a bar growing, which is a different claim. */
    bar.style.transformBox = "view-box";
    bar.style.transformOrigin = `${x(point)}px ${mid}px`;
    bar.style.animationDelay = "var(--dur-1)";
    s.append(bar);
    for (const end of [interval.lo, interval.hi]) {
      s.append(svg("line", { x1: x(end), y1: mid - 5, x2: x(end), y2: mid + 5, class: `res-forest-cap res-forest-cap--${verdict}` }));
    }
  }
  s.append(svg("circle", { cx: x(point), cy: mid, r: 4.5, class: `res-forest-dot enter-point res-forest-dot--${verdict}` }));
  host.append(s);
  return host;
}

/* The reading line carries a file size, so it is marked chrome with the reason.
   It is the one thing on the card before the record lands, and an unmarked
   number there fires the audit on the first paint of every load. */
function waiting(text) {
  const p = chromeText(text, "a progress line; its digits are a file size");
  p.className = "res-waiting";
  return p;
}
