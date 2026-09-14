/* Section 7 — four independent vintage stamps.

   There is no single export vintage and the footer says so. Each source stamps
   itself: the symbol index is a month older than the prices, and flattening them
   into one date would assert a uniformity the data does not have. */

import { chromeText } from "../lib/figure.js";

export function renderMastheadVintage(root, manifest) {
  root.textContent = "";
  root.append(
    chromeText(`prices ${manifest.prices.snapshot}`, "the pinned price vintage"),
    chromeText(`symbols ${manifest.symbols.synced_on}`, "when the symbol index was synced"),
  );
}

export function renderFooter(root, manifest) {
  root.textContent = "";
  const stamps = document.createElement("div");
  stamps.className = "cmp-stamps";
  for (const [label, value] of [
    ["export", manifest.export_version],
    ["prices", manifest.prices.snapshot],
    ["symbols", manifest.symbols.synced_on],
    ["freeze", manifest.freeze.version],
  ]) {
    stamps.append(chromeText(`${label} ${value}`, `the ${label} vintage stamp`));
  }
  root.append(stamps);

  const note = document.createElement("p");
  note.className = "cmp-note";
  note.textContent =
    "Four independent stamps, not one export vintage. Each source dates itself; " +
    "the symbol index is a month older than the prices.";
  root.append(note);
}
