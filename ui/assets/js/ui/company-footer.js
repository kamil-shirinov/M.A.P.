/* Section 7 — four independent vintage stamps.

   There is no single export vintage and the footer says so. Each source stamps
   itself: the symbol index is a month older than the prices, and flattening them
   into one date would assert a uniformity the data does not have. */

import { chromeText } from "../lib/figure.js";

/** A vintage that does not exist is "not exported", never the word `null`.

    `map export --allow-partial` on a clone has no symbol index, so
    `symbols.synced_on` is null — and both the masthead and the footer printed
    `symbols null`, which reads as a value rather than as an absence. */
const vintage = (value) => (value === null || value === undefined ? "not exported" : String(value));

export function renderMastheadVintage(root, manifest) {
  root.textContent = "";
  root.append(
    chromeText(`prices ${vintage(manifest.prices?.snapshot)}`, "the pinned price vintage"),
    chromeText(`symbols ${vintage(manifest.symbols?.synced_on)}`, "when the symbol index was synced"),
  );
}

/** One quiet mono line, the way the door's bottom line reads.

    The sentence that used to sit under these stamps now lives in the page-foot
    disclosure (`STAMPS_NOTE`). It is a note about how to read the stamps, and it
    was being printed on every screen whether or not anyone was asking. */
export function renderFooter(root, manifest) {
  root.textContent = "";
  const stamps = document.createElement("div");
  stamps.className = "cmp-stamps";
  for (const [label, value] of [
    ["export", manifest.export_version],
    ["prices", manifest.prices?.snapshot],
    ["symbols", manifest.symbols?.synced_on],
    ["freeze", manifest.freeze?.version],
    // Which code wrote the export. Abbreviated to seven, like every other commit
    // reference in this project.
    ["code", manifest.code?.commit ? manifest.code.commit.slice(0, 7) : null],
  ]) {
    stamps.append(stamp(label, vintage(value), `the ${label} vintage stamp`));
  }
  root.append(stamps);
}

/** Label quiet, value bright, both inside one chrome wrapper so the audit sees
    the digits marked wherever they fall. */
export function stamp(label, value, why) {
  const wrap = chromeText("", why);
  wrap.className = "cmp-stamp";
  const name = document.createElement("span");
  name.className = "cmp-stamp-label";
  name.textContent = `${label} `;
  const shown = document.createElement("span");
  shown.className = "cmp-stamp-value";
  shown.textContent = String(value);
  wrap.append(name, shown);
  return wrap;
}
