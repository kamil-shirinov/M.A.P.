/* Corpus-wide measured reliability. NEVER per ticker: with two or three filings
   a company, a coverage rate on a single name would be an interval spanning
   most of the unit line. The `scope` field exists so a renderer can refuse to
   display this inside a ticker panel — the separation is enforced by the data,
   not by remembering where to put the element.

   These numbers are placeholders and are marked as such. They deliberately do
   NOT reuse the project's real development-half figures. */

export const CORPUS_RELIABILITY = {
  scope: "corpus",
  band: "clean",
  split: "dev",
  horizon_days: 5,
  n: 164,
  date_clusters: 17,
  stated_coverage: 0.8,
  measured_coverage: 0.74,
  interval: { low: 0.66, high: 0.82, method: "moving-block bootstrap, 10-day blocks" },
  as_of: "2026-09-01",
  note: "Development half only. The holdout is unspent.",
};

/* Below this count a coverage rate cannot separate a calibrated forecaster from
   a materially miscalibrated one, so no rate is shown at all. n = 78 gives 80%
   power to detect a 20-point departure from stated coverage at the 5% level;
   20 points is the smallest miscalibration that would change what you do. */
export const MIN_N_FOR_A_RATE = 80;
