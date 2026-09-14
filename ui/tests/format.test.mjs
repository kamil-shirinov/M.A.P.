/* The two halves of the figure contract, and the one arithmetic distinction the
   export's field names do not carry.

   No runner, no package.json, no build step — `node --test tests/`. The README
   promises no framework and no bundler, and a test directory is not the place to
   start breaking that. */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { fmt } from "../assets/js/lib/format.js";
import { DERIVED, FABRICATED, MEASURED, figure, renderFigure } from "../assets/js/lib/figure.js";

/** The smallest `document` renderFigure needs. Not a DOM: enough of one to let a
    thin helper be exercised without pulling jsdom into a repo with no build. */
function stubDocument() {
  globalThis.document = {
    createElement: () => ({ className: "", dataset: {}, textContent: "", title: "" }),
  };
}

describe("renderFigure refuses an unknown format", () => {
  it("throws rather than falling back to fmt.int", () => {
    stubDocument();
    assert.throws(
      () => renderFigure({ value: 0.08, provenance: MEASURED, format: "percent" }),
      /unknown format: percent/,
    );
  });

  it("is the same contract figure() already held for provenance", () => {
    assert.throws(() => figure(1, "guessed"), /unknown provenance: guessed/);
  });

  it("still renders every format the app actually passes", () => {
    stubDocument();
    for (const name of ["int", "ms", "pct", "pctSigned", "price", "ratio3", "weight"]) {
      const el = renderFigure({ value: 0.5, provenance: DERIVED, format: name });
      assert.notEqual(el.textContent, "", `${name} rendered nothing`);
    }
  });

  it("marks a fabricated figure so a reader cannot mistake it for a result", () => {
    stubDocument();
    const el = renderFigure({ value: 1, provenance: FABRICATED, format: "int" });
    assert.match(el.title, /Fabricated/);
  });
});

describe("logpct and pct are not interchangeable", () => {
  /* `realised_return` in the export is log(close/open); `price_return` on a
     scenario is a simple return. The failure mode is not a uniform small bias —
     the two agree on small moves and separate on large ones, so a spot-check of
     typical values passes and the error surfaces on the runs a reader studies
     hardest. One value pinned in each region. */

  it("agrees at one decimal place on a small move", () => {
    assert.equal(fmt.pct(0.021), "2.1%");
    assert.equal(fmt.logpct(0.021), "2.1%");
  });

  it("diverges on a large move, in both directions", () => {
    assert.equal(fmt.pct(0.08), "8.0%");
    assert.equal(fmt.logpct(0.08), "8.3%");
    assert.equal(fmt.pct(-0.082), "-8.2%");
    assert.equal(fmt.logpct(-0.082), "-7.9%");
  });

  it("agrees nowhere above 4.4%, which is why the helpers are separate", () => {
    for (let v = 0.044; v <= 0.15; v += 0.001) {
      assert.notEqual(fmt.pct(v), fmt.logpct(v), `agreed at ${v}`);
    }
  });

  it("keeps six places on a drift ratio, where ratio3 loses the event", () => {
    assert.equal(fmt.ratio(0.9881423249262894), "0.988142");
    assert.equal(fmt.ratio3(0.9881423249262894), "0.988");
  });

  it("aliases date to shortDate", () => {
    assert.equal(fmt.date, fmt.shortDate);
    assert.equal(fmt.date("2026-09-05"), "05 Sep 2026");
  });
});
