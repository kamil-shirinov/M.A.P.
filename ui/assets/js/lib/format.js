const MINUS = "\u2212";

/** Fixed decimals with a real minus sign. Negative zero prints as zero: a
    difference that rounds to nothing is not a direction. */
const fixed = (v, places) => {
  const text = Math.abs(v).toFixed(places);
  return (v < 0 && Number(text) !== 0 ? MINUS : "") + text;
};

/** The same, with the sign always shown. */
const signed = (v, places) => {
  const text = Math.abs(v).toFixed(places);
  if (Number(text) === 0) return "0." + "0".repeat(places);
  return (v < 0 ? MINUS : "+") + text;
};

export const fmt = {
  price: (v) => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  pct:   (v) => (v * 100).toFixed(1) + "%",
  pctSigned: (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%",
  weight: (v) => Math.round(v * 100) + "%",
  ms: (v) => (v >= 1000 ? (v / 1000).toFixed(1) + " s" : v + " ms"),
  int: (v) => v.toLocaleString("en-US"),
  // Log returns, NOT simple ones. `realised_return` in the export is
  // log(close/open); `price_return` on a scenario is a simple return. One helper
  // for both is invisible below about 4% — 2.0% either way — and then diverges:
  // 8.0 vs 8.3, -8.2 vs -7.9. Systematic, one-directional, and it looks like a
  // plausible return at every magnitude, which is why it needs two helpers rather
  // than a comment.
  logpct: (v) => (Math.expm1(v) * 100).toFixed(1) + "%",
  ratio3: (v) => v.toFixed(3),
  // `anchor_drift.ratio` carries float32 noise off each run's own recorded spot,
  // so the nine drifted rows hold seven distinct values for two corporate
  // actions. Six places collapses them to the two that exist; ratio3 rounds
  // 0.988142 to 0.988 and loses the digits that identify the event.
  ratio: (v) => v.toFixed(6),
  /* Scores, at the places the record's own summary lines use: CRPS to five,
     log score to four. A REAL MINUS (U+2212), not a hyphen — these sit in a
     column of signed differences where the sign is the finding, and a hyphen at
     11px in Inter is a third the width of a plus and reads as a dash.
     `signed` always shows the sign, because "+0.00163 worse" and "-0.00100
     better" are the same column and an unsigned entry in it is ambiguous. */
  dec5: (v) => fixed(v, 5),
  dec4: (v) => fixed(v, 4),
  signed5: (v) => signed(v, 5),
  signed4: (v) => signed(v, 4),
  // File sizes as the export contract states them: DECIMAL KB, so 649,217 bytes
  // is 649.2 KB and not 634.0. Under 1000 the byte count is the honest figure —
  // "0.0 KB" for a 2-byte empty array reads as missing rather than empty.
  kb: (bytes) => (bytes < 1000 ? `${bytes} bytes` : (bytes / 1000).toFixed(1) + " KB"),
  isoDate: (d) => d,
  shortDate: (iso) => {
    const [y, m, d] = iso.split("-");
    return `${d} ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+m - 1]} ${y}`;
  },
};

// The export dates every value it carries, and callers ask for "date".
fmt.date = fmt.shortDate;
