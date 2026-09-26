/* The company page's notes, in page order.

   Its own module so a test can read them without booting the page: `company.js`
   is a composition root that paints on import and needs a whole document. A
   sentence that moved off the screen and into the disclosure should still be
   assertable, and it cannot be if reaching it requires a browser. */

export const COMPANY_WHY = [
  {
    title: "Company",
    notes: [
      "This is a record of forecasts already made for this company, not a current projection. " +
        "The export holds no live forecast, and the CLOSED count above says how many of the runs " +
        "on this page have an outcome at all.",
      "Exchange sits in symbols.json, loaded lazily on the first search keystroke. It is absent " +
        "here rather than unknown: the page does not fetch a megabyte to fill one field.",
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
