# 0035 — A log of what was forecast and what happened, which is not an evaluation

**Status:** accepted · **Date:** 2026-09-08 · **Builds on** [0012](0012-price-cache-and-retroactive-adjustment.md), [0018](0018-corpus-band-and-panel-shape.md), [0031](0031-holdout-spend.md), [0034](0034-document-provenance.md)

## Context

The product needs a page listing past runs: ticker, anchor, what was forecast, and —
where the horizon has elapsed — what the price actually did. Everything it needs is
already on disk in `runs/`, so the feature is a read.

The danger is entirely in what happens next. This is the front half of an evaluation.
Once a page shows a forecast beside an outcome, the distance between them is one
subtraction away, an average over the column is one more, and the resulting number
looks exactly like a result — while being computed over a sample nobody selected.

`runs/` is not a panel. It is whatever has been run: 826 directories accumulated from
smoke tests, retries, the ablation, two abandoned bands and twelve nights of corpus
execution. Its composition is a function of curiosity and interrupted evenings. An
accuracy figure over it would be real arithmetic on an unreal sample, and it would be
quoted, because a number on a screen does not carry its own provenance.

The pre-registered panel is `corpus/frozen.json`, scored by `map evaluate` against a
pinned read-only vintage, with the holdout spendable exactly once
([ADR 0031](0031-holdout-spend.md)). That is the only place a score comes from.

## Decision

Build the journal. Make the two constraints properties of the types, not rules in a
docstring, because a docstring is read once and a type is checked every time.

### Nothing here can become a score by accident

`JournalEntry` carries the scenarios and, where the window has closed, the realised
close. It exposes **no method that takes both sides** — no error, no return, no hit,
no rank. Its only derived member is `window_elapsed`, which reads one field. A test
pins the entry's whole public surface, so adding `def error(self)` fails the suite
rather than shipping.

The realised *close* is recorded, not a realised *return*. A return is one
subtraction from a score and the request was for what happened, which is a price.

An import-linter contract forbids `mapf.eval.journal` from reaching
`mapf.eval.scoring`, `mapf.eval.aggregate` or `mapf.eval.baselines`, transitively
included. Enforcing it required splitting `realised_bar` and `WindowNotClosedError`
out of `scorer` into `mapf.eval.window`, since importing the scorer for calendar
arithmetic dragged in CRPS, the baselines and the aggregator. That split is the
contract doing its job on its first day.

The outcome is fetched **live**, not from the scoring vintage, and that is stated in
the code: a number from an unpinned series is not reproducible, which is a second
reason it is not a score.

### Corpus and live runs cannot be pooled, because there is no pooled accessor

`Journal` exposes `corpus`, `edgar`, `news` and `unknown` separately and defines no
`__iter__`, no `__len__`, and no combined tuple. A caller that wants everything must
name each population. The four names are the manifest's own `document_source` values
([ADR 0034](0034-document-provenance.md)), not a grouping invented here, and
`unknown` — a manifest predating the field — is reported as itself rather than folded
into either.

The `--json` output is keyed the same way, so the artifact cannot be pooled either.
The listing prints per-section counts and never a total.

## Two things this uncovered

**`RunManifest` is a writer's schema.** Its `manifest_version` is a `Literal` pinned
to the current format. That is right when stamping a new run and unusable for reading
old ones: bumping it to 1.8.0 for `document_source` made all 831 stored 1.7.0
manifests fail to validate at once. The only other reader — `map evaluate` — never
noticed because it parses manifests as raw dicts and picks fields out by hand. The
journal now has `StoredManifest`, a reader's view that ignores unknown fields, keeps
the version as a plain string, and validates only the four fields it depends on. A
reader of eight format versions cannot honestly promise more.

*(The 1.8.0 bump itself was a correction: every prior field addition moved the minor
version, and adding `document_source` in the previous commit did not.)*

**Skipped directories are counted.** 47 of the 826 run directories are not readable
runs — 46 pre-manifest captures, and one schema 1.0.0 forecast whose
`price_modifier_pct` is percentage points rather than a fraction
([ADR 0012](0012-price-cache-and-retroactive-adjustment.md)). Reported with the
listing rather than logged and forgotten, for the same reason open windows are shown
as open: a listing that quietly dropped 47 would read as a complete history of 779.

## Consequences

- A company page can show a run history without anything on the path to a score.
- `mapf.eval.window` now holds the shared anchor arithmetic, and `realised_return`
  uses it instead of its own copy — the return and the pinned outcome bar can no
  longer disagree about which session a horizon starts on.
- The journal is the first consumer of `document_source`. Every run written before
  today lands in `unknown`, correctly: absence was never a claim.
- Structlog now writes to stderr. Its default is stdout, which is harmless for a
  table and fatal for `--json` — one warning about one unreachable ticker lands
  inside the document and the consumer gets a parse error.
- Not built: the HTTP server the front end will eventually call. That is a dependency
  decision and is deliberately separate.
