/* Commit IDs after the history cleanup of 2026-09-30 (ADR 0038).

   The records keep the IDs they were written with; docs/commit-map.tsv says what
   each became; every commit a page shows goes through lib/commits.js. What is
   asserted: the app's copy of the map IS the map, the map cannot be misread, the
   resolver shows both IDs and invents none, and no page names an old commit
   except through it. NO EXPORT NEEDED: all of it reads checked-in files. */

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { describe, it } from "node:test";

const ROOT = new URL("../", import.meta.url);
const file = (p) => readFileSync(new URL(p, ROOT), "utf8");
const load = (m) => import(new URL(`assets/js/${m}?${Math.random()}`, ROOT));

// Only the final newline goes: a trailing tab is an empty `via`, not whitespace.
const TSV = file("../docs/commit-map.tsv").replace(/\n$/, "").split("\n").map((l) => l.split("\t"));
const [HEADER, ...ROWS] = TSV;

describe("the map", () => {
  it("has one row per old ID, of three kinds, each old ID unique to seven characters", () => {
    assert.deepEqual(HEADER, ["old", "new", "kind", "via"]);
    for (const row of ROWS) {
      assert.equal(row.length, 4, row.join(" "));
      assert.match(row[0], /^[0-9a-f]{40}$/);
      assert.match(row[1], /^[0-9a-f]{40}$/);
      assert.ok(["commit", "rebased", "note"].includes(row[2]), row[2]);
    }
    const olds = ROWS.map((r) => r[0]);
    assert.equal(new Set(olds).size, olds.length);
    assert.equal(new Set(olds.map((o) => o.slice(0, 7))).size, olds.length);
    const count = (kind) => ROWS.filter((r) => r[2] === kind).length;
    assert.deepEqual([count("commit"), count("rebased"), count("note")], [276, 25, 22]);
  });

  it("sends every rebased original where its published copy went", () => {
    const commits = new Map(ROWS.filter((r) => r[2] === "commit").map((r) => [r[0], r[1]]));
    for (const [old, now, , via] of ROWS.filter((r) => r[2] === "rebased")) {
      const copy = [...commits.keys()].filter((c) => c.startsWith(via));
      assert.equal(copy.length, 1, `${old.slice(0, 7)} names ${via} as its copy`);
      assert.equal(commits.get(copy[0]), now, old.slice(0, 7));
    }
  });

  it("gives no published ID the seven characters of an old one", () => {
    const olds = new Set(ROWS.map((r) => r[0].slice(0, 7)));
    for (const [, now] of ROWS) assert.ok(!olds.has(now.slice(0, 7)), `${now.slice(0, 7)} reads as an old ID`);
  });

  it("is what the app imports, row for row", async () => {
    const { COMMIT_MAP } = await load("data/commit-map.js");
    const expected = Object.fromEntries(
      ROWS.filter((r) => r[2] !== "note").map(([old, now, kind]) => [old, [now, kind]]),
    );
    assert.deepEqual(COMMIT_MAP, expected);
  });
});

describe("resolving a commit", () => {
  it("shows the published ID and keeps the recorded one", async () => {
    const { resolveCommit, CLEANUP } = await load("lib/commits.js");
    assert.deepEqual(resolveCommit("ad71b139f6d1d056d38320d7ff468a5db1a89424"), {
      shown: "171a4d6", recorded: "ad71b13", event: CLEANUP,
    });
    assert.deepEqual(resolveCommit("ad71b13"), { shown: "171a4d6", recorded: "ad71b13", event: CLEANUP });
  });

  it("names both rewrites for a commit the rebase had already replaced", async () => {
    const { resolveCommit, REBASE, CLEANUP } = await load("lib/commits.js");
    const r = resolveCommit("9cb1b84f21726a82d211b9c7b62b2ada2abd1e41");
    assert.equal(r.shown, "5d928ea");
    assert.equal(r.recorded, "9cb1b84");
    assert.equal(r.event, `${REBASE} and ${CLEANUP}`);
    // And its published copy lands on the same commit.
    assert.equal(resolveCommit("710879a").shown, "5d928ea");
  });

  it("invents nothing for an ID the map does not know", async () => {
    const { resolveCommit } = await load("lib/commits.js");
    const published = ROWS[0][1];
    for (const id of [published, "deadbeef", "not-a-commit", "", null, undefined]) {
      const r = resolveCommit(id);
      assert.equal(r.recorded, null, String(id));
      assert.equal(r.event, null);
      assert.equal(r.shown, String(id ?? "").trim().toLowerCase().slice(0, 7));
    }
  });

  it("resolves commits inside a record's own words and leaves the rest as written", async () => {
    const { resolveCommitsIn } = await load("lib/commits.js");
    assert.equal(
      resolveCommitsIn("git note record 14 on ad71b13"),
      "git note record 14 on 171a4d6 (recorded as ad71b13)",
    );
    assert.equal(resolveCommitsIn("digest 1997f7352e47, freeze 2.5.0"), "digest 1997f7352e47, freeze 2.5.0");
  });
});

describe("the pages", () => {
  it("name an old commit only through the resolver", async () => {
    const { COMMIT_MAP } = await load("data/commit-map.js");
    const olds = Object.keys(COMMIT_MAP).map((o) => o.slice(0, 7));
    const walk = (dir) => readdirSync(new URL(dir, ROOT), { withFileTypes: true }).flatMap((d) =>
      d.isDirectory() ? walk(`${dir}${d.name}/`) : d.name.endsWith(".js") ? [`${dir}${d.name}`] : []);
    for (const path of walk("assets/js/")) {
      if (path.endsWith("data/commit-map.js")) continue;
      // Comments cite commits as records do; only code can put one on a page.
      const code = file(path).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
      for (const m of code.matchAll(/\b[0-9a-f]{7,40}\b/g)) {
        if (!olds.some((o) => m[0].startsWith(o))) continue;
        const before = code.slice(Math.max(0, m.index - 20), m.index);
        assert.match(before, /resolveCommit(?:sIn)?\("$/, `${path} names ${m[0]} outside the resolver`);
      }
    }
  });
});
