/* One closed <details>, and everything the charts above cannot say in a chart.

   WHY ONE. This is an app screen, not a methodology report. Ten caveats printed
   beside ten figures is a paper; ten caveats behind one disclosure is a screen
   that a reader can use and then interrogate. Nothing load-bearing hides in
   here — every figure above already carries its definition — but every trap a
   reader could fall into on their own is named.

   EVERY BLOCK IS PROSE, MARKED CHROME WITH ITS REASON. The digits in it are
   citations, sample sizes and thresholds, not measurements this page computed;
   marking them as figures would claim a provenance they do not have. */

import { resolveCommitsIn } from "../lib/commits.js";
import { fmt } from "../lib/format.js";


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
  ["The subtraction is done before the rounding",
   "Each mean is shown to five places and their difference to five, but the difference is taken " +
   "from the full values and rounded once at the end. So the figures on screen need not subtract " +
   "to the figure beside them: 0.03179 minus 0.03105 reads as 0.00074 while the page shows " +
   "+0.00075. Rounding first and subtracting after would put the error into the result instead of " +
   "leaving it visible between two displays."],
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
    "definition the pre-registration on " + resolveCommitsIn("ad71b13") + " names and the one the " +
    "published counts were made " +
    "under. On the " + band + " band it gives " + stats.tails[2.5] + " over 2.5 and " + stats.tails[3] +
    " over 3. realised_return ÷ sigma ignores the centre and gives " +
    stats.tailsIgnoringCentre[2.5] + " and " + stats.tailsIgnoringCentre[3] + " on the same items. " +
    "Two definitions, not two routes to one number."
  );
}

const LIVE = new Set(["The log score is stored lower-is-better", "Tail counts name their sample"]);

/** The notes this screen contributes to the page-foot disclosure.

    Same ten blocks, in page order, now as groups for the shared component
    instead of a grid of cards this screen drew for itself. The two band-specific
    blocks are still written at render time from the record on screen — see
    `live()` — and the holdout block still quotes the export's own reason before
    the Findings #57 sentence.

    "Must not" becomes the "Refused" group: the shared system gives refusals
    their own heading, and these were the only notes on the page that stated what
    it will not draw rather than how to read what it did. */
export function whyGroups({ holdoutReason, stats, band } = {}) {
  const groups = BLOCKS.map(([title, text]) => ({
    title,
    notes: [LIVE.has(title) ? live(title, { stats, band }) : text],
  }));

  const holdout = groups.find((g) => g.title === "The holdout");
  if (holdout) {
    holdout.notes = [
      holdoutReason ?? "The export records no holdout absence.",
      "Findings #57: the holdout's own baseline comparison survives only as a sentence. The " +
        "per-item scores that backed it were printed once and never written down, so the " +
        "comparison cannot be re-derived, re-plotted or checked — it is quoted here and nowhere " +
        "rendered as a number.",
    ];
  }

  groups.push({
    title: "Refused",
    kind: "refused",
    notes: [
      "Dividing 175 by 779. Items are not runs, and the journal is not this screen's denominator.",
      "Printing a holdout score. None exists; the panel states that rather than leaving a gap.",
      "Recomputing an interval. Every one on this screen is parsed from the record's own sentence.",
      "Attaching a score to a run or a run_id. There is no key that joins them.",
      "Sorting or orienting the log score as higher-is-better.",
      "Showing Brier as three comparisons, or averaging the two clean records.",
    ],
  });

  return groups;
}
