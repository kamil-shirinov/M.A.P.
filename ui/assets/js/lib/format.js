export const fmt = {
  price: (v) => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  pct:   (v) => (v * 100).toFixed(1) + "%",
  pctSigned: (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%",
  weight: (v) => Math.round(v * 100) + "%",
  ms: (v) => (v >= 1000 ? (v / 1000).toFixed(1) + " s" : v + " ms"),
  int: (v) => v.toLocaleString("en-US"),
  ratio3: (v) => v.toFixed(3),
  isoDate: (d) => d,
  shortDate: (iso) => {
    const [y, m, d] = iso.split("-");
    return `${d} ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+m - 1]} ${y}`;
  },
};
