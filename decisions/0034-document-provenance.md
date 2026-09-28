# 0034 — Recording where a forecast's document came from, positively

**Status:** accepted · **Date:** 2026-09-08 · **Builds on** [0007](0007-determinism-guard-with-auditable-override.md), [0019](0019-corpus-execution-protocol.md), [0020](0020-context-window-and-truncation.md)

## Context

`map run --from-edgar` adds a third way a document can reach the pipeline. Until now
there were two: the frozen corpus (`map corpus run`, an accession listed in
`frozen.json`) and a news directory or RSS feed (`map run`). The new path discovers
the filer's most recent Item 2.02 8-K at runtime — a real exhibit, fetched and
truncated exactly as the corpus path fetches and truncates one, but **not in the
frozen corpus**: unscored, no band, no place in any calibration figure.

That last property is the whole problem. An EDGAR run and a corpus run produce
byte-similar artifacts from byte-identical documents. Nothing about the forecast
distinguishes them, and pooling them would put an item selected by "whatever the
filer published this week" into a sample whose selection rule is the reason its
scores mean anything.

Two questions had to be answered, and answered in code rather than left to whoever
reads the artifact later.

## Question 1 — what happens when the ticker has no Item 2.02 in the window

**Options.** (a) Fall back to the news path. (b) Fail, naming the window searched.
(c) Fail with a generic "not found".

**Decision: (b).**

(a) is the one that produces a wrong number rather than no number. A user who typed
`--from-edgar` and got a forecast would reasonably believe it came from a filing. If
the fallback silently read whatever `.txt` files happened to be in `news.dir`, the
forecast would be built from unrelated commentary under a flag asserting otherwise —
and the manifest, before this ADR, would have agreed with the flag. A wrong forecast
that announces itself is a bug; a wrong forecast that does not is a fabrication.

(c) fails safely but uninformatively. "No filing for AAPL" cannot be told apart from
"you searched the wrong ninety days", and the two have opposite remedies. The message
names the interval and the flag that widens it:

> `no 8-K Item 2.02 filing for AAPL between 2026-05-11 and 2026-09-08`

`--from-edgar` with `--news-dir` is refused outright (exit 2) rather than resolved by
precedence, for the same reason: silently honouring one of two document sources
mislabels the run.

## Question 2 — how the artifact says which path produced it

**Options.** (a) Infer from `freeze_version is None`. (b) A boolean `from_edgar`.
(c) A `document_source` enum recorded by every path.

**Decision: (c)** — `document_source: Literal["corpus", "edgar", "news"] | None`.

(a) was already available and is not sufficient, because **absence is ambiguous in the
wrong direction**. A missing `freeze_version` is consistent with an EDGAR run, a news
run, *and* a corpus run written before the field existed. The inference "no freeze
version, therefore not corpus" is exactly the kind that holds until the day it does
not, and the day it does not is the day something outside the corpus is pooled into
it. A negative signal cannot carry a claim this load-bearing.

(b) records the new path and leaves the two old ones indistinguishable from each
other, which is half a fix.

(c) is asserted at all three call sites or at none: `run.py` passes `"edgar"` or
`"news"`, `corpus/runner.py` passes `"corpus"`. `None` retains its honest meaning —
*this manifest predates the field* — and is never a claim about the source. Tests pin
all three, so a fourth path added without a label fails rather than defaults.

## Consequences

- Phase 2 gains a positive filter. Excluding non-corpus runs no longer requires
  reasoning about which fields happen to be absent.
- Truncation on the EDGAR path uses the same intake budget and the same
  `head_tail_v1` rule as the corpus path ([ADR 0020](0020-context-window-and-truncation.md)), so the two
  paths see an identical document where the exhibit is identical. The budget is read
  from the registry at both call sites rather than duplicated.
- The manifest schema gains an optional field; every existing artifact stays valid and
  reads back as `None`.
- This does not make EDGAR runs scoreable. They remain outside `frozen.json` by
  construction — the field records that fact, it does not change it.
