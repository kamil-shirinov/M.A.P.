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
   anchor and nothing else.

   IN THE LOCAL APP THE LINE IS THE LAST TWO YEARS TO TODAY (ADR 0039): exactly
   that window, on New York's calendar, fetched through this machine, and
   split-adjusted like the pinned snapshot so a run's marks sit on it. The part
   newer than the snapshot is drawn differently and labelled, because the record
   was scored against the snapshot and nothing after it. A run's marks sit on the
   line; its figures are the record's. A run the window cannot show is counted in
   a sentence under the chart, never dropped without a word. The hosted copy has
   no server and draws the snapshot as it always did.

   The x axis is calendar time over the window, so "two years to today" is the
   width of the plot and the line ends where the last close is, which during a
   session is yesterday's. */

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

const DAY_MS = 86_400_000;
const dayOf = (iso) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10))) / DAY_MS;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const spoken = (iso) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;
// A close the provider re-based since the snapshot moves every earlier close by
// the same factor; below this the two agree and nothing is said.
const REBASED = 1e-3;

/** `snapshot`, when given, is the pinned series the record was scored against,
    drawn beside a `series` this machine fetched: it says where the newer part
    starts and whether the provider has re-based the history since. */
export function renderSeries(root, { series, runs, title = "Price series and when runs opened", snapshot = null }) {
  root.textContent = "";
  root.append(header(series, title));

  if (isAbsent(series)) {
    root.append(absence(series.why));
    return;
  }

  const rows = Object.values(runs.bySource).flatMap((r) => r);
  const drawn = [];
  const pinned = snapshot && !isAbsent(snapshot) && snapshot.sessions?.length ? snapshot : null;
  const { wrap, after, notes } = plot(series, rows, drawn, pinned);
  root.append(wrap);
  for (const note of notes) root.append(note);
  // A key to run marks on a chart that has none would describe nothing on it.
  if (rows.length || after) root.append(legend(rows, { after }));
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
  if (series.served && series.window) {
    right.append(
      document.createTextNode(" · "),
      chromeText(
        `${spoken(series.window.start)} to ${spoken(series.window.end)}`,
        "the two years to today this chart covers",
      ),
      document.createTextNode(" · "),
      chromeText(
        `${series.provider ?? "provider unrecorded"}, ${String(series.adjustment ?? "basis unrecorded").replace("_", "-")}`,
        "where these closes come from, and their adjustment basis",
      ),
    );
  }
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

function plot(series, rows, drawn, pinned) {
  const bars = series.sessions;
  const closes = bars.map((b) => b[1]);
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const span = hi - lo || 1;
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  // Calendar time over the window the series covers: the served two years, or
  // the snapshot's own first and last session.
  const first = series.window?.start ?? bars[0][0];
  const last = series.window?.end ?? bars.at(-1)[0];
  const d0 = dayOf(first);
  const d1 = Math.max(dayOf(last), d0 + 1);
  const index = new Map(bars.map((b, i) => [b[0], i]));
  const days = bars.map((b) => dayOf(b[0]));
  const xDay = (d) => PAD.left + ((d - d0) / (d1 - d0)) * innerW;
  const x = (i) => xDay(days[i]);
  const y = (v) => PAD.top + innerH - ((v - lo) / span) * innerH;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, class: "cmp-plot", role: "img",
    "aria-label": `Closing prices for ${series.ticker}, ${first} to ${last}, with each run drawn from its anchor to its outcome`,
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

  /* Where the snapshot ends. The record was scored against the snapshot and
     nothing newer, so the closes after its last one are drawn apart and said. */
  const pinnedThrough = pinned ? pinned.sessions.at(-1)[0] : null;
  const split = pinnedThrough ? bars.findLastIndex((b) => b[0] <= pinnedThrough) : bars.length - 1;
  const after = pinnedThrough !== null && split >= 0 && split < bars.length - 1;
  const trace = (from, to) =>
    bars.slice(from, to + 1).map((b, k) => `${k ? "L" : "M"}${x(from + k).toFixed(2)},${y(b[1]).toFixed(2)}`).join(" ");

  // The newer part sits on a faint region of its own, behind everything drawn.
  if (after) {
    const sx = x(split);
    svg.append(svgEl("rect", {
      class: "cmp-snap-region", x: sx, y: PAD.top, width: Math.max(0, W - PAD.right - sx), height: innerH,
    }));
  }
  const line = svgEl("path", { class: "cmp-line", d: trace(0, Math.max(split, 0)) });
  svg.append(line);
  // Drawn after mounting: a detached path has no length. 600ms is the one
  // exception to --dur-3 in the motion spec — this line is two years long and
  // at 400ms it reads as a flicker rather than as a series being laid down.
  drawn.push(line);
  if (after) {
    svg.append(svgEl("path", { class: "cmp-line cmp-line--after", d: trace(split, bars.length - 1) }));
    const sx = x(split);
    svg.append(svgEl("line", { class: "cmp-snap-rule", x1: sx, x2: sx, y1: PAD.top, y2: PAD.top + innerH }));
    // Left of the rule, pointing across it: the newer part is usually a few
    // weeks at the right edge, with no room beside it for a sentence.
    const said = svgEl("text", { class: "cmp-snap-label", x: sx - 6, y: PAD.top + innerH - 6, "text-anchor": "end" });
    said.textContent = `newer than the ${spoken(pinned.snapshot ?? pinnedThrough)} snapshot →`;
    said.dataset.chrome = "where the closes newer than the pinned snapshot begin";
    svg.append(said);
  }

  /* Each run as the segment it actually spans. The markers arrive after the line
     has been laid down: they mark points ON it, and appearing first would make
     them look like the subject. */
  const marks = svgEl("g", { class: "cmp-marks" });
  const runAt = new Map();
  const before = [];
  const missing = [];
  for (const run of rows) {
    const ai = index.get(run.anchor_date);
    if (ai === undefined) {
      // Said under the chart, not dropped: before the window, or a session the
      // series does not hold.
      (dayOf(run.anchor_date) < d0 ? before : missing).push(run);
      continue;
    }
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
  wrap.append(svg, axisDates(first, last));
  attachCrosshair(wrap, svg, { bars, days, d0, d1, x, y, runAt, innerH });

  const notes = [];
  if (before.length) {
    const earliest = before.map((r) => r.anchor_date).sort()[0];
    notes.push(note(
      `${before.length === 1 ? "One recorded run is" : `${before.length} recorded runs are`} anchored before ` +
        `${spoken(first)}, outside this two-year window, so ${before.length === 1 ? "it is" : "they are"} not drawn; ` +
        `the earliest is ${spoken(earliest)}.`,
      "recorded runs this window cannot show",
    ));
  }
  if (missing.length) {
    notes.push(note(
      `${missing.length === 1 ? "One run's anchor session is" : `${missing.length} runs' anchor sessions are`} ` +
        "not in this series, so " + (missing.length === 1 ? "it is" : "they are") + " not drawn.",
      "runs whose anchor the series does not hold",
    ));
  }
  const rebased = pinned ? rebase(bars, pinned) : null;
  if (rebased) {
    notes.push(note(
      `Since the snapshot the provider has re-based this series by ×${rebased.toFixed(4)} — a split or similar. ` +
        "The line is on today's basis; every run's figures are still the record's.",
      "the provider's series moved against the snapshot's",
    ));
  }
  return { wrap, after, notes };
}

/** The factor between the fetched close and the snapshot's on the snapshot's last
    session, when they disagree; null when they agree or share no session. */
function rebase(bars, pinned) {
  const [date, close] = pinned.sessions.at(-1);
  const now = bars.find((b) => b[0] === date);
  if (!now || !close) return null;
  const ratio = now[1] / close;
  return Math.abs(ratio - 1) > REBASED ? ratio : null;
}

function note(text, why) {
  const p = document.createElement("p");
  p.className = "cmp-series-note";
  p.append(chromeText(text, why));
  return p;
}

/** The crosshair, and the readout it drives.

    Pointer position maps to a session by nearest index, so the line snaps to a
    trading day rather than floating between two. Every number in the readout
    goes through `renderFigure`, so the same marks apply here as anywhere else —
    a close is measured, a realised return is derived, and a re-based run shows
    its ratio instead of a return it cannot honestly state. */
function attachCrosshair(wrap, svg, ctx) {
  const { bars, days, d0, d1, x, y, runAt, innerH } = ctx;

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

  /* The session nearest the pointer in calendar time: the line snaps to a
     trading day rather than floating between two, and a weekend under the
     pointer reads as the closer of its two neighbours. */
  const nearest = (event) => {
    const box = svg.getBoundingClientRect();
    if (!box.width) return null;
    const vx = ((event.clientX - box.left) / box.width) * W;
    const t = (vx - PAD.left) / (W - PAD.left - PAD.right);
    if (t < -0.02 || t > 1.02) return null;
    const day = d0 + t * (d1 - d0);
    let lo = 0;
    let hi = days.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (days[mid] <= day) lo = mid;
      else hi = mid;
    }
    return Math.abs(days[hi] - day) < Math.abs(days[lo] - day) ? hi : lo;
  };

  svg.addEventListener("pointermove", (e) => {
    const i = nearest(e);
    if (i === null) hide(); else show(i, e.clientX);
  });
  svg.addEventListener("pointerleave", hide);
}

function axisDates(first, last) {
  const row = document.createElement("div");
  row.className = "cmp-plot-dates";
  row.append(
    chromeText(first, "where the chart's window begins"),
    chromeText(last, "where the chart's window ends"),
  );
  return row;
}

/** Only the states actually present are listed. A legend entry for something the
    page does not draw teaches a reader to look for it. */
function legend(rows, { after = false } = {}) {
  const items = [["cmp-line", "close"]];
  if (after) items.push(["cmp-line--after", "close, newer than the snapshot"]);
  if (rows.length) {
    items.push(["cmp-anchor", "run, anchor to outcome"], ["cmp-dot--outcome", "outcome close"]);
  }
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
