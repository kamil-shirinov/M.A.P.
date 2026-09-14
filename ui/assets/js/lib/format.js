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
  isoDate: (d) => d,
  shortDate: (iso) => {
    const [y, m, d] = iso.split("-");
    return `${d} ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+m - 1]} ${y}`;
  },
};

// The export dates every value it carries, and callers ask for "date".
fmt.date = fmt.shortDate;
