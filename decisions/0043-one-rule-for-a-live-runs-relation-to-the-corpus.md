# 0043 — One rule for a live run's relation to the corpus

**Status:** accepted · **Date:** 2026-10-02 · **Builds on** [0035](0035-run-journal.md) · [0036](0036-live-analysis.md)

## Context

A company page showed two answers about one run. Its table of live runs, read from the
journal, called a live AAPL run on the 2026-07-30 filing `OUTSIDE CORPUS`; the result
the same page had just drawn called the same filing `REPEAT`.

There were two implementations of one question. The journal asked only whether a run's
document **hash** was one the corpus froze. The live result asked `Freeze.relate`, which
also falls back to the filing's **accession**, because a re-fetch of the same filing can
arrive as different bytes and hash differently. `corpus/frozen.json` holds
`0000320193-26-000018` for AAPL, and a test already pins that the live lookup calls it a
repeat by accession. So the two can only have disagreed where the hash differed and the
accession matched. **That is inferred from the two rules, not observed:** the runs themselves
(`runs/`, `var/`) were not available when this was written, so it is not confirmed that the
AAPL runs' documents hash differently from the frozen exhibit.

The journal could not use the accession because nothing recorded it: a run's manifest
holds the document's hash and not the filing it came from.

## Options

1. **Make the live result use the journal's hash-only rule.** Rejected: it would say
   `outside_corpus` for a filing the corpus holds, which is the less true of the two.
2. **Infer the accession in the journal** from the ticker and a date. Rejected: the live
   path reads the company's *latest* 8-K, which may or may not be a held one, so any
   inference is a guess presented as a relation.
3. **One rule, shared; record the accession.**

## Decision

**Option 3.**

- `relate_to_frozen` in `mapf.eval.journal` is the only implementation: document id
  first, accession as the fallback, `unchecked` when nothing was compared. `Freeze.relate`
  in the serve layer calls it. A test gives the page's lookup and the journal's row the
  same frozen sets and requires one answer.
- **The manifest records `document_accession`** (format 1.10.0, optional) for a run that
  read a filing: `map serve` and `map run --from-edgar` pass it to `execute`. A news run carries none, and
  older runs are handled below.
- The journal's reader takes it as an optional field, so every older manifest still
  parses. `read_journal` takes `frozen_accessions`; `map runs`, `map export` and
  `map serve` pass the frozen record's accessions beside its hashes.
- **A ledger entry still wins** over a document lookup, and the row's other fields are
  untouched: a live run of a frozen filing is still `document_source: edgar`, with no
  freeze version.

## Consequences

- **Runs made before this change are related by their own trace, at read time.** The
  trace keeps every prompt, and the intake prompt opens its document block with
  `[document 1 of 1 | source: <url>]`; for an EDGAR exhibit that URL is
  `…/Archives/edgar/data/{cik}/{accession without dashes}/{file}`. `document_accession`
  in `mapf.pipeline.trace` reads it back, and the journal uses it only when the manifest
  has none, the hash found nothing, accessions were supplied, and the run is not a news
  run. **Nothing is written to any artifact.** It is guarded three ways: only the header at
  the very start of the block is read (the document's text is untrusted and could hold a
  line shaped like one); a trace that fails `audit_trace` is not read (a whole band written
  into one directory would give this run the band's first filing); and anything else is
  `None`, never a guessed accession.
- **What is not verified:** this was tested against traces built from the real prompt
  template and written by the real pipeline, not against the real `runs/`. The
  four AAPL runs from August whose documents were sample files have a file path for a
  source, so they stay `outside_corpus`; that is expected, not confirmed.
- `forecast_digest` moves, as for any change under `src/mapf` (ADR 0026).
- The export's run rows gain no field. A run with a recorded accession can change its
  `corpus_relation` and `document_is_frozen_exhibit` in the next export; the counts in
  `docs/export-contract.md` are for the existing runs and do not move.
