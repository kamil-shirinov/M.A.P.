# 0009 — Deterministic quarantine delimiters

Status: Accepted · Date: 2026-08-10 · Phase 1

## Context

Untrusted news text is interpolated into a prompt whose output is parsed as
numbers. The oldest attack in prompt injection applies directly: the untrusted
text contains the closing delimiter, followed by instructions, and the model reads
everything after it as coming from us.

The textbook defence is a **random nonce in the delimiter** — the attacker cannot
close a block whose terminator they cannot predict.

**That defence is unavailable here, and the reason is worth stating precisely.** A
fresh nonce per call means a fresh prompt on every run. A fresh prompt means a
fresh cache key. A fresh cache key means every run is a total miss, and DoD
criterion 5 — a second `map run` in under two seconds with zero inference calls —
becomes unreachable by construction.

On this hardware the cache is not an optimisation (`CLAUDE.md` §6): a 12B runs at
8–15 tok/s and a three-agent run pays three model swaps. A defence that destroys
the cache does not trade security for speed; it trades security for the project
being able to run a backtest at all.

## Options

1. **Nonce delimiter.** Strongest against forgery, and incompatible with the cache.
2. **Fixed delimiter, no sanitisation.** Cache-safe and trivially defeated.
3. **Fixed delimiter, escape occurrences.** Cache-safe, but an escape scheme needs
   an encoding the model must not misread as content, and it leaves near-misses
   (`<<<END UNTRUSTED DATA >>>`, with a space) intact — which an exact-match filter
   ignores and a model may well honour anyway.
4. **Fixed delimiter, strip occurrences to a fixpoint.**

## Decision

**Fixed, public delimiters**, and safety from the other side: the payload is
transformed so that it *cannot contain* the marker. Three steps, and the order is
load-bearing.

1. **NFKC normalise.** Compatibility lookalikes — fullwidth `＜`, and similar —
   collapse into their ASCII equivalents. Done first, they become ordinary markers
   that step 3 removes. Done last, or not at all, they pass through as characters
   that render like a delimiter while matching no filter.
2. **Strip control and format characters** (`Cc`, `Cf`, `Co`, keeping `\n` and
   `\t`). Beyond hygiene this removes bidirectional overrides, which can make text
   display in an order different from the one the model reads, and zero-width
   characters used to split a marker into non-matching fragments.
3. **Delete every `<<<` and `>>>`, to a fixpoint.** Whole marker sequences rather
   than the exact delimiter strings, so near-misses die too. A **single pass is not
   sufficient**: `<<<END UNT<<<END UNTRUSTED DATA>>>RUSTED DATA>>>` has its inner
   marker removed and the outer fragments then sit adjacent, forming a new one. The
   replacement is shorter than the marker, so each pass strictly shrinks the text
   and the loop provably terminates.

Two structural decisions in the renderer carry the rest:

- **Role markers are parsed before slots are substituted.** Message boundaries are
  fixed before any untrusted character is seen, so untrusted text containing
  `[[system]]` is literal content and cannot create a message.
- **Our instruction comes after the untrusted block**, so the last thing the model
  reads is ours.

## Consequences

- The rendered prompt is **byte-identical across runs for identical input**, which
  is asserted directly in the tests rather than assumed. Injection attempts do not
  destabilise it either: neutralisation is deterministic, so hostile input caches
  like any other.
- Sanitisation is lossy, and knowingly. NFKC rewrites some legitimate characters
  (`№` → `No`, ligatures decompose), and stripping `Cf` breaks some emoji
  sequences. Acceptable for financial news; it would not be for arbitrary text.
  The document **id is unaffected** — it hashes the raw bytes as fetched
  (ADR 0005), so provenance survives a lossy rendering.
- **Two things this does not stop, and neither is quietly ignored.** Visual
  lookalikes NFKC leaves alone (`⟨⟨⟨` is not `<<<` under any normalisation) and
  plain-prose instructions inside the block. Neither can *forge the delimiter*, so
  neither escapes quarantine; the residual mitigation is the template's
  data-not-instructions rule and the instruction-last ordering. Both limits have
  tests that assert the limit rather than pretending it is covered.
- Marker removal is logged at warning level with a count. It is either an
  injection attempt or a source document behaving oddly, and both are things a
  human should learn about before reading a forecast rather than after.
- Changing the delimiter, or the sanitiser, invalidates every cached entry for
  every agent. That is correct — the prompt genuinely changed — but it makes the
  sanitiser a place to think before editing.
