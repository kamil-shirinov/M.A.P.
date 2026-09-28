# Honest claims, and one incident

Four things are easy to overstate about a project like this, and one thing went
wrong that is worth reading in full.

---

## What this is not

**This is not financial advice, and it is not a trading system.** No order execution, no
broker integration, no position sizing. It is a research and engineering exercise whose
purpose is to produce forecasts that can be *scored* — a forecast that cannot be scored
is a bug, not a feature.

---

## Honest claims

Four things are easy to overstate about a project like this. The accurate versions:

**All *inference* is local.** No data is sent to a third-party model provider. This is
**not** "100% offline": price data comes from Yahoo Finance or Stooq over the network,
the symbol universe is downloaded from SEC EDGAR, and news may be fetched from RSS.
Those are third parties, and they see what you ask for.

**Training-cutoff leakage makes naive backtests worthless.** The models already know what
happened to well-known tickers. Any backtest run on news published before a model's
training cutoff is contaminated, and a *good* result from such a backtest is evidence of
memorisation, not of forecasting skill. Phase 2's evaluation harness is designed around
this from the start. Treat any pre-cutoff result as invalid until proven otherwise.

**Name search covers US-listed companies only.** The searchable symbol universe comes
from the SEC's `company_tickers_exchange.json` (~10k US-listed companies). Non-US
listings work only if you already know the suffixed ticker (`.L`, `.TO`, `.DE`); they do
not appear in name search. There is no global name coverage.

**Nearly two-thirds of the clean band cannot be reconstructed from a commit.** 208 of
351 completed items were produced while the working tree had uncommitted changes, so no
code digest was recorded. Development continued against a live run for days, which was a
mistake. The honest figure is **214 of 349 at the moment the band finished**; correcting
an unrelated defect later happened to clean six. The second band has none — **350 of 350
carry one digest at one commit** — so the defect was fixed rather than merely survived.

What survives this: the forecast-governing surface was verified against the frozen record
at every launch. What does not: that verification did not cover the truncation
parameters, one of which drifted mid-band under an unchanged identifier, affecting six
items that were found and re-run.

**The price vintage pinned nothing until 5 September 2026.** Every manifest recorded
`fetched_on: 2026-08-14`. No price was ever fetched on that date. The cache was keyed on
the real calendar day in every code path, so the corpus was built across at least seven
daily snapshots while every manifest asserted a single one that never existed. What
protected the result was not the pin but a drift guard written for a different purpose,
which refuses to score an item whose recorded spot has moved. The corpus now exists at
one deliberately pinned snapshot of **701 windows** — the first time in the project's
history that has been true.

**"Reproducible" is four separate claims here. Three hold; the fourth does not.**

| claim | verdict |
| --- | --- |
| **Pre-registered** — the corpus, the bands and every threshold were fixed before any result was seen | **holds**, and the commit order is the evidence for it. **Twenty-two pre-registration records** are stored as git notes on `refs/notes/commits`, each written before the result it constrains. They fix the statistics, the predicted direction, and the interpretation of every outcome including those that would disconfirm. **Verify them yourself — see below** |
| **Auditable** — every prompt and every raw response is preserved in `runs/<run_id>/trace.jsonl` | **holds**; a run is refused if any trace is missing or empty |
| **Replayable from cache** — re-reading a completed run returns byte-identical output | **holds** |
| **Re-derivable** — a cold cache reproduces the same forecasts | **does not hold** |

### Verifying the pre-registrations yourself

**GitHub does not display git notes in its web interface, and `git clone` does not
fetch them.** They are not in the repository you get by default; you have to ask for
the ref.

```
git fetch origin 'refs/notes/*:refs/notes/*'
```

**The ordering evidence is the ref's own commit history, not the note's contents.**
Each record was appended in a separate operation, so the ref carries one commit per
record, each with the timestamp at which that record was written:

```
git log --format='%h %ad %s' --date=iso refs/notes/commits
```

Twenty-two commits, oldest last. Compare any record's timestamp against the commit
that produced the result it constrains — `git log --format='%h %ad %s' --date=iso
main` — and the claim "written before the result" is checkable rather than asserted.
A record appended after its result would show it here, and that is the point of
keeping them in a ref whose history cannot be rewritten without the rewrite being
visible.

Then read them:

```
git notes --ref=commits show ad71b13
```

All twenty-two are one note on that commit, about 120 KB. `git log --show-notes`
displays it inline against the commit it annotates.

Agents 1 and 3 request `temperature=0` and a fixed seed, and every run records the
seed, the sampling parameters and the model fingerprint *as requested* — many local
inference servers ignore both. **Temperature 0 is near-deterministic, not
deterministic, on this backend, and that is measured rather than assumed: replaying
five identical recorded prompts returned byte-identical output twice out of five.**

So a re-run from a cold cache produces *similar* forecasts, not identical ones. What
is exact is replay **from the cache** — which is why the cache is provenance
infrastructure and not an optimisation.

**Measured at the level of results, not strings.** A cold re-run of the whole
pipeline on 60 items leaves the aggregate unmoved — mean CRPS 0.03255 cached against
0.03240 cold, a paired difference of −0.00016 with an interval from −0.00072 to
+0.00066 — while **individual items shift by 4.3% on average and 53% come back
byte-identical**. So non-determinism is real and visible per item, and it does not
move the reported means. Both halves of that are worth stating: the first is why
"re-derivable" fails, the second is why the published figures are nonetheless
stable.

**Scoring was non-reproducible for a second, unrelated reason.** Until the vintage was
pinned, prices were re-fetched on every run, and an upstream split or correction rewrites
history retroactively. Three items were lost to a genuine SCCO split the provider applied
25 days late. Note that dropping those items is *conservative rather than correct* — a
return is scale-invariant under a split, so they are scoreable once the recorded spot is
rescaled. The guard refuses because it cannot distinguish a split from genuine drift.

**One phase opened without its criteria committed.** Phase 1's eight acceptance criteria
were committed in the initial commit, before a line of `src/` existed. **Phase 2's seven
were never committed at all.** They were written in advance, in a brief that only ever
existed as a chat message, and by the standard applied everywhere else here — git history
is the pre-registration — that is the same as not having them. Every decision made
*during* the phases was committed as it happened: thirty-three ADRs and fourteen
timestamped notes. The gap was in the opening statement only, and Phase 3 opened with its
criteria committed.

**The quality checks read prose, not the forecast.** Every run records whether figures in
a scenario's *justification* trace back to a material fact. That check does **not** cover
`price_return`, `annualised_vol` or `probability_weight` — the numbers actually scored.
Nothing grounds those against the source, and nothing could straightforwardly: a forecast
is supposed to state something the source did not. Their only checks are the schema's
bounds and the ordering invariant. Read a clean `ungrounded_numerals` as "the prose cites
nothing invented", never as "the forecast is supported".

**The three-agent architecture is a hypothesis, and the ablation that would have
tested it could not be run.** Four arms were pre-registered; two of them — both
requiring the 12B model to work inside a token budget — failed identically and were
abandoned. Losing one of them lost both primary comparisons, so **the ablation has no
primary and makes no causal claim**. What survives is descriptive: the full pipeline
beats a no-analyst variant by 13.6% on CRPS, and three things differ between them
(the analyst, the model size, and necessarily the prompt), so "the analyst helps" is
one of three readings the design cannot separate. Nothing here claims the
architecture is better.

**Why the arms failed is the more useful result.** A reasoning model spends its
budget on reasoning first and the answer last, so capping the budget truncates the
output rather than the deliberation. At 1,000, 12,000 and 15,000 tokens — the last
being the most a 16,384-token window allows — roughly **99.98% of the allowance went
to reasoning and no answer was produced**, every time. *A reasoning model's cost is
not tunable by its budget*, and it does not drop into a fixed-budget pipeline slot.
It can be made cheaper only by removing the agent, by choosing a model that reasons
less, or by a provider-side reasoning-effort control this backend does not expose.

**The corpus is a reusable benchmark.** 709 filings identified by accession number, with
recorded outcomes, two baselines scored, a frozen protocol and a pinned price snapshot.
Any future model can be run against the identical panel with one configuration change,
because the backend is named only in configuration and never in code.

---

## What Phase 1 does not guarantee — an incident

The first live run produced a forecast that passed every check in this project and
contained a figure the model invented. It is worth reading in full, because it is
the clearest available statement of what the machinery here is and is not for.

The source article said Apple's gross margin was **46.3%**. Agent 1 extracted that
correctly. Agent 2 reasoned about it correctly, quoting 46.3% twice. Agent 3, while
transcribing that reasoning into the structured forecast, wrote:

> "the high gross margin of **66.3%** suggests a stable profit floor"

Nothing caught it. The output was valid JSON under a constrained grammar. Its three
probability weights summed to 1.0. Its scenarios were correctly ordered. Every
field was inside its bounds. The repair loop was never triggered because there was
nothing to repair. 489 tests passed, `mypy --strict` passed, four architectural
contracts held. The forecast was written to disk, charted, and reported as a
success — **and one of the premises underneath it did not exist.**

That is not a bug that was fixed. **It is the failure mode this project is
structurally unable to detect**, and it is documented in `src/mapf/agents/__init__.py`
in exactly those terms, written before it happened:

> A forecast can be schema-valid, internally consistent, fully traced, and built
> entirely on a premise the model invented. […] Nothing here detects that, because
> nothing here compares the forecast to reality.

The same run also produced three scenarios spanning 0.15% — a "bullish" case of
+0.05% over 21 days, for a stock that routinely moves several percent in that
window. Also valid. Also unremarked.

**What changed as a result:** a crude numeral check now flags figures in a
justification that trace back to no extracted fact, and a spread check flags
scenarios that cluster too tightly for their horizon. Both are **warnings recorded
in the manifest, never rejections** — a model paraphrasing "46.3%" as "about 46%"
must not fail a run, and a genuinely flat outlook is a legitimate forecast. Neither
check is reliable. Both convert an invisible failure into a visible one *some* of
the time, which is the entire claim being made for them.

**What did not change, and cannot:** nothing here verifies that a forecast is
*right*. Validators guarantee internal consistency. Grammars guarantee shape.
Neither has any access to whether the numbers mean anything. That is Phase 2's job
and only Phase 2's — which is why a forecast that cannot be scored is treated in
this project as a bug rather than a feature.

The forecasts this system produces are **falsifiable, not verified.** The incident
above is the evidence for that distinction, not an exception to it.

---
