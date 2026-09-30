/* The company page's notes, in page order.

   Its own module so a test can read them without booting the page: `company.js`
   is a composition root that paints on import and needs a whole document. A
   sentence that moved off the screen and into the disclosure should still be
   assertable, and it cannot be if reaching it requires a browser. */

export const COMPANY_WHY = [
  {
    title: "Company",
    notes: [
      "The page has two halves. Above the last section is the record: forecasts already made " +
        "for this company from the frozen corpus, and the CLOSED count says how many have an " +
        "outcome at all. The last section holds live runs, made on demand; they are listed, " +
        "counted and drawn there and nowhere else.",
      "Exchange comes from corpus.json, which this page already opens. It used to be absent " +
        "here because the field lived only in the 864 KB symbol index; the export copies it " +
        "onto the corpus row now, so a fact the app plainly knew stopped reading as missing.",
    ],
  },
  {
    title: "Filings and runs",
    notes: [
      "A filing with an empty run list is one the corpus holds that nothing ran — 8 of 709. It is " +
        "shown rather than dropped: a page listing only filings with runs would show 701 and " +
        "misstate the record it is drawing from.",
      "The filing date is carried from the ledger and never derived from the anchor date. They " +
        "coincide on 66 runs corpus-wide and differ by one day on 635.",
      "clean is after the models' training cutoff and ambiguous is before it. Both are factual " +
        "partitions of the corpus and read neutral: neither is the good half.",
      "A repeat's link to its panel run is matched on (ticker, anchor_date), not on a key. " +
        "source_doc_ids is not exported, so nothing in the data states that the two runs read the " +
        "same document. It is unambiguous throughout this export, and still inference.",
    ],
  },
  {
    title: "Outcomes",
    notes: [
      "An open window has no outcome — absent, not zero — and is marked by a dash rather than by " +
        "colour. Nothing is wrong, nothing was refused, and it resolves by itself.",
      "retrieved_on moves on every export: it is the day the export read the close, not a property " +
        "of the run. It is read from the row rather than written into the copy.",
    ],
  },
  {
    title: "Scoring",
    notes: [
      "No score is attached to a run here, and none can be. A run carries its own forecast and " +
        "outcome; a scoring record is a separate pass over a band and a split. They are related at " +
        "band, split and vintage and at nothing finer.",
      "A scored item's as_of is the forecast's own date and a run's anchor_date is the trading " +
        "session it opened from. Those coincide for 161 of the 175 clean items; the other 14 are " +
        "Saturdays and Good Friday.",
    ],
  },
  {
    title: "Scoring",
    notes: [
      "No score is attached to a run on this page, and none can be. A run carries its own " +
        "forecast and outcome; a scoring record is a separate pass over a band and a split. They " +
        "are related at band, split and vintage — never per item.",
      "A second clean record ships from an unidentifiable tree: the same measurement recorded " +
        "twice under different code states, not two results. It is not shown and not averaged in.",
      "What survives of the holdout, and where: the calibration coefficients and their fitted " +
        "form, and the band, item count, date, commit, freeze version and price vintage. They are " +
        "in corpus/holdout_spend.jsonl, whose git history is the record of the single spend.",
      "Why the per-item detail is gone: the holdout was scored once, its scores were printed once " +
        "and never persisted, and `map evaluate --split holdout` is refused before anything is " +
        "computed once the spend is recorded (ADR 0031). Nothing is coming later. This is not an " +
        "empty state.",
    ],
  },
  {
    title: "Refused",
    kind: "refused",
    notes: [
      "“Not scored.” The record covers one band and one split, and most panel runs sit outside its " +
        "scope legitimately — the ambiguous band and the whole holdout were never in it. Printing " +
        "the negative would claim that scored-eligible runs went unscored.",
      "A reconstructed band. Scored items carry map_sigma but no p10, p50 or p90. Building a band " +
        "from sigma is modelling presented as reading. The percentiles do not exist, so the column " +
        "does not either.",
    ],
  },
];

/* The live section's notes, used on every company page: the corpus's and the
   ones outside it. Carried over from the retired live-analysis screen. */
export const LIVE_WHY = [
  {
    title: "What a live run is",
    notes: [
      "The company's most recent 8-K Item 2.02 exhibit, read by three models running on the " +
        "machine serving this page. No hosted API is called and no data is sent to a model provider.",
      "It is a run, not a score. Nothing in the live section is compared to an outcome, because " +
        "the outcome does not exist yet when the run is made.",
      "Every run is permanent. It lands in the journal, it is counted, and it is exported. There " +
        "is no discard.",
      "Why a separate section rather than rows in the table above: a live run is not part of the " +
        "pre-registered panel, and a table that mixed them would put one row away from a corpus " +
        "figure. ADR 0036 keeps them apart in the data; this page keeps them apart on screen.",
    ],
  },
  {
    title: "Why most fans are amber",
    meta: "ADR 0036",
    metaWhy: "the decision record the live section implements",
    notes: [
      "The fitted correction was measured on a panel: 175 development items at five sessions, " +
        "anchored within one trading day of the filing, from companies that passed the corpus " +
        "filters. Applying it anywhere else is extrapolation.",
      "So it is applied only where all three of those hold, and the fan is raw and marked " +
        "otherwise, with the failing condition named. The liquidity floor alone is $50M median " +
        "daily dollar volume, so a great many companies land here.",
      "A raw fan is not a neutral one. The uncorrected fan is the version measured too narrow — " +
        "calibration ratio 0.733 on development and 0.592 on the holdout, both intervals " +
        "excluding 1.0.",
      "Ten and twenty-one sessions are always uncalibrated. Nothing was fitted at either, and " +
        "the horizon control says so before the run rather than after it.",
      "A corrected fan still does not claim to be calibrated. A live run reads a filing the " +
        "correction was never tested on, even for a corpus company, and the three conditions " +
        "make applying it defensible, not verified.",
    ],
  },
];
