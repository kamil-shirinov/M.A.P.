/* Commit IDs as the records store them, resolved to the published history.

   The history was rewritten twice: the 8 September rebase replayed 25 commits,
   and the 2026-09-30 cleanup gave every commit a new ID. Records are not edited
   after the fact, so the ledger, the scoring records, the spend record and the
   export all still carry the IDs they were written with. A page that printed
   those alone would name commits nobody can `git show`; a page that printed only
   the successor would silently edit the record. So every commit a page shows
   goes through here, and comes back as both: the ID to look up now, and the one
   the record stores (ADR 0038).

   An ID the map does not know is shown as it is. That is the case for anything
   written after the cleanup, which already names a published commit, and nothing
   is invented for it. */

import { COMMIT_MAP } from "../data/commit-map.js";

export const CLEANUP = "the 2026-09-30 history cleanup";
export const REBASE = "the 8 September rebase";

const HEX = /^[0-9a-f]{7,40}$/;
const SHORT = 7;

/** `{ shown, recorded, event }` for a commit ID as a record stores it.

    `shown` is the 7-character ID in the published history. `recorded` is the
    record's own 7 characters when they differ, else null, and `event` names what
    replaced them. A prefix is resolved only when exactly one old ID carries it. */
export function resolveCommit(id) {
  const stored = String(id ?? "").trim().toLowerCase();
  if (!HEX.test(stored)) return { shown: stored.slice(0, SHORT), recorded: null, event: null };
  const hits = Object.keys(COMMIT_MAP).filter((old) => old.startsWith(stored));
  if (hits.length !== 1) return { shown: stored.slice(0, SHORT), recorded: null, event: null };
  const [published, kind] = COMMIT_MAP[hits[0]];
  return {
    shown: published.slice(0, SHORT),
    recorded: stored.slice(0, SHORT),
    event: kind === "rebased" ? `${REBASE} and ${CLEANUP}` : CLEANUP,
  };
}

/** A record's free text with every old commit ID in it resolved in place, as
    "<published> (recorded as <old>)". Only whole 7–40 character hex words that
    the map knows are touched; everything else is returned as written. */
export function resolveCommitsIn(text) {
  return String(text ?? "").replace(/\b[0-9a-f]{7,40}\b/g, (word) => {
    const { shown, recorded } = resolveCommit(word);
    return recorded ? `${shown} (recorded as ${recorded})` : word;
  });
}
