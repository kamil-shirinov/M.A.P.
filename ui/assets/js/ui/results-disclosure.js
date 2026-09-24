/* One closed <details>, and everything the charts above cannot say in a chart.

   WHY ONE. This is an app screen, not a methodology report. Ten caveats printed
   beside ten figures is a paper; ten caveats behind one disclosure is a screen
   that a reader can use and then interrogate. Nothing load-bearing hides in
   here — every figure above already carries its definition — but every trap a
   reader could fall into on their own is named.

   EVERY BLOCK IS PROSE, MARKED CHROME WITH ITS REASON. The digits in it are
   citations, sample sizes and thresholds, not measurements this page computed;
   marking them as figures would claim a provenance they do not have. */

import { chrome } from "../lib/figure.js";
import { fmt } from "../lib/format.js";

const el = (tag, className, text) => {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
};

/* `body` is filled at render time for the two blocks that quote the export's own
   words back, so the export stays the source of its own reason. */
const BLOCKS = [
  ["What was scored",
   "n is the panel runs the pass loaded, less the ones it refused. Items are not runs: the journal " +
   "holds 779 runs across both bands, both splits and every repeat, and it is not the denominator " +
   "for anything on this screen."],
  ["A score does not join a run",
   "Scoring keys an item on ticker and as_of; a run keys on run_id and anchor_date. Those coincide " +
   "for 161 of the 175 clean items and not for the other 14, whose forecast dates are Saturdays and " +
   "Good Friday. There is no join, so no figure here is per-run."],
  ["The log score is stored lower-is-better"],
  ["Brier is one comparison, by construction",
   "Every baseline predicts a zero mean, so each states P(up) = 0.5 and scores exactly 0.25 on every " +
   "item whatever happened. Three rows would show one number three times. The page checks the claim " +
   "against every item before printing it."],
  ["The intervals are prose",
   "They come from a moving-block bootstrap. The seed, the draw count and the cluster map are not in " +
   "the export, so no interval on this screen is recomputed — each bar is parsed out of the record's " +
   "own summary sentence, and a sentence with no interval gets no bar."],
  ["Tail counts name their sample"],
  ["Leakage, from two records",
   "The comparison reads the clean and the ambiguous record, which were scored on different days and " +
   "under different commits. The difference of the means is arithmetic this page does; the interval " +
   "around it is quoted, because it is in neither file."],
  ["Two clean records, one measurement",
   "The clean band ships twice — the same items scored from a committed tree and from a dirty one. " +
   "The one with a forecast digest is shown, the other is named, and they are never averaged."],
  ["The holdout"],
  ["Not in this export",
   "The four-arm ablation's 786 runs, the 22 pre-registrations on refs/notes/commits, and stratum " +
   "membership per item. None of them is on this screen, and none of them is reachable from it."],
];

/* Two blocks quote the record ON SCREEN and are written at render time. Their
   numbers are band-specific — the clean band's two z definitions give 13 and 11
   over 2.5 while the ambiguous band's agree at 11 — and a fixed sentence would
   be wrong on whichever band it was not written for. */
function live(title, { stats, band }) {
  if (!stats) return "The record for this band has not been read yet.";
  if (title === "The log score is stored lower-is-better") {
    return (
      "It is a negative log density. On the " + band + " band M.A.P.'s " +
      fmt.dec4(stats.map.log_score) + " against the random walk's " +
      fmt.dec4(stats.baselines.random_walk.log_score) + " means M.A.P. is WORSE, and any sort or " +
      "axis that reads it the other way inverts the result. That is what the amber tag on the log " +
      "block guards."
    );
  }
  return (
    "z is Φ⁻¹(PIT) — the standardised distance from the forecast's own centre, which is the " +
    "definition the pre-registration on ad71b13 names and the one the published counts were made " +
    "under. On the " + band + " band it gives " + stats.tails[2.5] + " over 2.5 and " + stats.tails[3] +
    " over 3. realised_return ÷ sigma ignores the centre and gives " +
    stats.tailsIgnoringCentre[2.5] + " and " + stats.tailsIgnoringCentre[3] + " on the same items. " +
    "Two definitions, not two routes to one number."
  );
}

const LIVE = new Set(["The log score is stored lower-is-better", "Tail counts name their sample"]);

export function renderDisclosure(root, { holdoutReason, stats, band }) {
  root.textContent = "";
  const d = el("details", "srch-why cmp-disclosure res-why");
  const s = el("summary");
  s.append(
    el("span", "srch-why-caret", "▸"),
    el("span", "srch-why-title", "How to read these"),
    el("span", "srch-note", "ten things the charts above cannot say in a chart"),
  );
  d.append(s);

  const body = el("div", "srch-why-body res-why-body");
  for (const [title, text] of BLOCKS) {
    const card = el("div", "srch-res res-why-card");
    card.append(el("h3", "cmp-h3", title));
    if (title === "The holdout") {
      /* The export's own reason, verbatim, followed by the one sentence from
         Findings #57 that belongs to it. The sentence is prose and stays prose:
         the holdout's baseline comparison was never persisted, so stating it as
         a figure would invent a measurement. */
      card.append(
        prose(holdoutReason ?? "The export records no holdout absence."),
        prose(
          "Findings #57: the holdout's own baseline comparison survives only as a sentence. The " +
          "per-item scores that backed it were printed once and never written down, so the " +
          "comparison cannot be re-derived, re-plotted or checked — it is quoted here and nowhere " +
          "rendered as a number.",
        ),
      );
    } else if (LIVE.has(title)) {
      card.append(prose(live(title, { stats, band })));
    } else {
      card.append(prose(text));
    }
    body.append(card);
  }
  d.append(body);
  root.append(d);
  return d;
}

function prose(text) {
  const p = el("p", "cmp-note", text);
  return chrome(p, "explanatory prose; its digits are citations, sample sizes and thresholds");
}

export { BLOCKS };
