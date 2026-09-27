/* The export gate, and why it is per TEST rather than per suite.

   `ui/assets/export/` is generated and gitignored, so a fresh clone has none and
   most of this suite cannot run. That has always been true and always been
   handled — but it was handled with `describe(name, { skip: !HAVE }, ...)`, and
   node:test does not count the children of a skipped suite at all. They are
   never registered, so they are not tests, so they cannot be skipped tests.

   A clone therefore reported:

     ℹ tests 40 · pass 40 · fail 0 · skipped 0

   which reads as a complete green suite. 106 tests had not run, and nothing in
   that summary said so. A stranger following the README had no way to know the
   front end was almost entirely unexercised.

   Gating each `it` instead makes the summary honest:

     ℹ tests 146 · pass 40 · fail 0 · skipped 106

   and every skipped line carries the reason and the command that fixes it. */

import { existsSync, readFileSync } from "node:fs";
import { it as nodeIt } from "node:test";

const MANIFEST = new URL("../assets/export/manifest.json", import.meta.url);

/** A COMPLETE export, not merely a manifest.

    These tests assert on real counts — 779 runs, 175 scored items, 120
    companies — so they need the export that has them. `map export
    --allow-partial` writes a manifest and names what it could not include, and
    gating on the file alone let 106 tests run against an export with no ledger,
    no scores and no prices: 59 failures that were not defects in anything.

    The export states its own completeness. `absent` is empty when every input
    was read and lists what was missing otherwise, so that is the test rather
    than a guess about which files happen to be present. */
function state() {
  if (!existsSync(MANIFEST)) return { complete: false, why: null };
  try {
    const manifest = JSON.parse(readFileSync(MANIFEST, "utf8"));
    const absent = (manifest.absent ?? []).map((a) => a.what);
    return { complete: absent.length === 0, why: absent.length ? absent : null };
  } catch {
    return { complete: false, why: ["unreadable"] };
  }
}

const EXPORT = state();

export const HAVE_EXPORT = EXPORT.complete;

export const NO_EXPORT_WHY = EXPORT.why
  ? `the export at ui/assets/export is partial — no ${EXPORT.why.join(", ")}. ` +
    "These assertions need the full one: `uv run map export`"
  : "no export at ui/assets/export — run `uv run map export` " +
    "(or `--allow-partial` on a clone, which has no ledger)";

/** `it`, skipped WITH A REASON when the export is absent.

    Used in place of `it` inside every suite that reads the export. The suites
    themselves are no longer skipped, so their bodies run and register the tests;
    what does not run is each test body. Anything in those suites that touches
    the export OUTSIDE a test body — a `before` hook — has to return early on its
    own, because a hook is not a test and cannot be skipped this way. */
export function itNeedsExport(name, fn) {
  return nodeIt(name, HAVE_EXPORT ? {} : { skip: NO_EXPORT_WHY }, fn);
}
