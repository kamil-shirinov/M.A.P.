/* A figure is a number plus where it came from. The two travel together so a
   value cannot be rendered without saying what it is.

   measured   read from a real artifact under runs/
   derived    computed here from measured inputs
   fabricated from a fixture, OR derived from any fabricated input

   Weakest input wins. That rule is what stops provenance being laundered
   through arithmetic: an invented scenario weight cannot become an
   innocent-looking target price. */

export const MEASURED = "measured";
export const DERIVED = "derived";
export const FABRICATED = "fabricated";

const RANK = { [MEASURED]: 0, [DERIVED]: 1, [FABRICATED]: 2 };

export function figure(value, provenance, format = "int") {
  if (!(provenance in RANK)) throw new Error(`unknown provenance: ${provenance}`);
  return { value, provenance, format };
}

/** Provenance of a value computed from several figures: the weakest of them. */
export function weakest(...provenances) {
  return provenances.reduce((a, b) => (RANK[a] >= RANK[b] ? a : b), MEASURED);
}

/** Derive a new figure from others, propagating provenance automatically. */
export function derive(value, format, ...inputs) {
  const p = weakest(...inputs.map((f) => f.provenance));
  // Anything computed from measured inputs is DERIVED, never MEASURED: it was
  // not read from an artifact and no trace contains it.
  return figure(value, p === MEASURED ? DERIVED : p, format);
}

import { fmt } from "./format.js";

/** The only sanctioned way to put a number on screen. Returns a node, not a
    string, so it cannot be concatenated into innerHTML without the marking. */
export function renderFigure(fig, { className = "" } = {}) {
  const el = document.createElement("span");
  el.className = ("fig " + className).trim();
  el.dataset.prov = fig.provenance;
  el.textContent = (fmt[fig.format] || fmt.int)(fig.value);
  if (fig.provenance === FABRICATED) el.title = "Fabricated sample value — not a result";
  return el;
}

/** Positively mark a node that legitimately contains digits but is not a
    figure: dates, counts of listings, accession numbers, horizon labels.
    The audit has no heuristics, so this is the only way past it. */
export function chrome(el, why) {
  el.dataset.chrome = why;
  return el;
}

/** Convenience: a <span data-chrome> carrying text with digits in it. */
export function chromeText(text, why) {
  const el = document.createElement("span");
  el.textContent = text;
  return chrome(el, why);
}
