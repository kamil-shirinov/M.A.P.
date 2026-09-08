"""The corpus runner.

The assertions are about the three promises that make a twelve-night run
survivable: it refuses to start against drifted prompts, it resumes without
redoing or double-counting work, and it halts rather than finishing a corpus that
is no longer the one that was frozen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from mapf.core.errors import (
    ForecastRepairExhausted,
    InferenceStatusError,
    InferenceTimeoutError,
    InferenceUnreachableError,
    MapError,
    MarketDataUnavailableError,
    MissingExhibitError,
    ModelBudgetExhaustedError,
    NoMaterialFactsError,
    TemplateNotFoundError,
)
from mapf.corpus.ledger import Ledger, LedgerEntry, is_terminal
from mapf.corpus.runner import (
    REQUIRED_ARTIFACTS,
    CorpusHaltedError,
    CorpusItem,
    FreezeMismatchError,
    Health,
    RunnerConfig,
    _absorb,
    _reason_for,
    plan,
    run_band,
    verify_freeze,
)
from mapf.corpus.selection import Band, BandFilings, Corpus, SelectionCriteria, TickerPlan

VINTAGE = date(2026, 8, 14)
CLEAN = Band(name="clean", first_open=date(2026, 1, 1), last_open=date(2026, 8, 6))
AMBIG = Band(name="ambiguous", first_open=date(2025, 1, 1), last_open=date(2025, 12, 31))


# ---------------------------------------------------------------------------
# Freeze verification — the check that protects twelve nights
# ---------------------------------------------------------------------------
FROZEN = {
    "prompts": {
        "intake": {"template": "intake.v2.md", "version": "v2", "sha256": "a" * 64},
        "analyst": {"template": "scenario_analyst.v3.md", "version": "v3", "sha256": "b" * 64},
    },
    "models": {"analyst": {"alias": "google/gemma-4-12b-qat", "max_tokens": 12000}},
}
LIVE_MODELS = {"analyst": {"alias": "google/gemma-4-12b-qat", "max_tokens": 12000}}


def _digest(mapping: dict[tuple[str, str], str]) -> Callable[[str, str], str]:
    def inner(name: str, version: str) -> str:
        try:
            return mapping[(name, version)]
        except KeyError:
            raise TemplateNotFoundError(name, version, ()) from None

    return inner


MATCHING = _digest({("intake", "v2"): "a" * 64, ("scenario_analyst", "v3"): "b" * 64})


def test_matching_templates_and_models_pass() -> None:
    verify_freeze(FROZEN, live_digest=MATCHING, live_models=LIVE_MODELS)


def test_an_edited_template_refuses_the_run() -> None:
    """The failure this exists for: a prompt improved at 1am costs twelve nights."""
    drifted = _digest({("intake", "v2"): "a" * 64, ("scenario_analyst", "v3"): "c" * 64})
    with pytest.raises(FreezeMismatchError, match="content changed"):
        verify_freeze(FROZEN, live_digest=drifted, live_models=LIVE_MODELS)


def test_the_mismatch_message_names_the_template_and_both_hashes() -> None:
    drifted = _digest({("intake", "v2"): "a" * 64, ("scenario_analyst", "v3"): "c" * 64})
    with pytest.raises(FreezeMismatchError) as caught:
        verify_freeze(FROZEN, live_digest=drifted, live_models=LIVE_MODELS)
    message = str(caught.value)
    assert "scenario_analyst.v3.md" in message
    assert "bbbbbbbbbbbb" in message and "cccccccccccc" in message


def test_a_missing_template_refuses_rather_than_skipping() -> None:
    absent = _digest({("intake", "v2"): "a" * 64})
    with pytest.raises(FreezeMismatchError, match="could not be loaded"):
        verify_freeze(FROZEN, live_digest=absent, live_models=LIVE_MODELS)


def test_a_swapped_model_alias_refuses_the_run() -> None:
    with pytest.raises(FreezeMismatchError, match="alias is"):
        verify_freeze(
            FROZEN,
            live_digest=MATCHING,
            live_models={"analyst": {"alias": "other/model", "max_tokens": 12000}},
        )


def test_a_drifted_sampling_value_refuses_the_run() -> None:
    """Comparing only the alias is how `intake.max_tokens` sat at null in the frozen
    record while the run was configured for 2,048, undetected."""
    with pytest.raises(FreezeMismatchError, match="max_tokens is 999"):
        verify_freeze(
            FROZEN,
            live_digest=MATCHING,
            live_models={"analyst": {"alias": "google/gemma-4-12b-qat", "max_tokens": 999}},
        )


def test_a_config_value_the_freeze_does_not_record_is_not_checked() -> None:
    """An older freeze may say less than the config. It may never disagree."""
    verify_freeze(
        FROZEN,
        live_digest=MATCHING,
        live_models={"analyst": {"alias": "google/gemma-4-12b-qat", "max_tokens": 12000, "new": 1}},
    )


def test_a_frozen_field_the_config_no_longer_has_is_skipped_not_crashed() -> None:
    """Reading a live value that is absent must not raise: the refusal has to report
    every mismatch at once, and an exception here would report none of them."""
    verify_freeze(
        {**FROZEN, "models": {"analyst": {"alias": "google/gemma-4-12b-qat", "gone": 1}}},
        live_digest=MATCHING,
        live_models=LIVE_MODELS,
    )


def test_an_agent_absent_from_the_live_configuration_is_skipped() -> None:
    """A missing model is `map health`'s job; this check is about drift in what is
    configured, and it must not double as a second, weaker existence check."""
    verify_freeze(FROZEN, live_digest=MATCHING, live_models={})


def test_a_freeze_without_prompt_hashes_is_rejected() -> None:
    """An unpinned corpus cannot be verified, so it cannot be run."""
    with pytest.raises(FreezeMismatchError, match="no prompt hashes"):
        verify_freeze({"models": {}}, live_digest=MATCHING, live_models={})


def test_a_malformed_prompt_entry_is_rejected() -> None:
    with pytest.raises(FreezeMismatchError, match="malformed"):
        verify_freeze(
            {"prompts": {"intake": "not-a-mapping"}},
            live_digest=MATCHING,
            live_models={},
        )


def test_every_mismatch_is_reported_not_just_the_first() -> None:
    """Two templates and two sampling fields drifted: the refusal names all four,
    so one restart resolves them rather than four."""
    drifted = _digest({("intake", "v2"): "z" * 64, ("scenario_analyst", "v3"): "c" * 64})
    with pytest.raises(FreezeMismatchError) as caught:
        verify_freeze(
            FROZEN,
            live_digest=drifted,
            live_models={"analyst": {"alias": "other/model", "max_tokens": 999}},
        )
    assert str(caught.value).count("\n  ") == 4


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def _corpus() -> Corpus:
    return Corpus(
        criteria=SelectionCriteria(bands=(CLEAN, AMBIG), seed=1, target_tickers=2),
        ordering_sha256="0" * 64,
        accepted=(
            TickerPlan(
                ticker="BBB",
                split="dev",
                filings=(
                    BandFilings(band="clean", dates=(date(2026, 2, 3), date(2026, 5, 4))),
                    BandFilings(band="ambiguous", dates=(date(2025, 2, 3),)),
                ),
            ),
            TickerPlan(
                ticker="AAA",
                split="holdout",
                filings=(
                    BandFilings(band="clean", dates=(date(2026, 2, 3),)),
                    BandFilings(band="ambiguous", dates=(date(2025, 2, 3),)),
                ),
            ),
        ),
        rejected=(),
    )


def test_plan_selects_one_band_only() -> None:
    assert all(i.band == "clean" for i in plan(_corpus(), "clean"))
    assert len(plan(_corpus(), "clean")) == 3


def test_plan_is_ordered_by_date_then_ticker() -> None:
    """Deterministic order means a resume replays the same sequence."""
    items = plan(_corpus(), "clean")
    assert [(i.filing_date, i.ticker) for i in items] == [
        (date(2026, 2, 3), "AAA"),
        (date(2026, 2, 3), "BBB"),
        (date(2026, 5, 4), "BBB"),
    ]


# ---------------------------------------------------------------------------
# Execution, resume and halting
# ---------------------------------------------------------------------------
@dataclass
class FakeManifest:
    fidelity: object
    quality: object
    agents: tuple[object, ...]


class _Fidelity:
    def __init__(self, unparseable: tuple[str, ...] = (), divergent: tuple[str, ...] = ()):
        self.unparseable, self.divergent = unparseable, divergent


class _Quality:
    def __init__(self, ungrounded: tuple[str, ...] = (), degenerate: bool = False):
        self.ungrounded_numerals, self.degenerate_spread = ungrounded, degenerate


class _Agent:
    def __init__(
        self,
        reasoning: int = 0,
        hits: int = 0,
        alias: str = "intake",
        output_truncated: bool = False,
        degeneration_retry: bool = False,
    ):
        self.reasoning_tokens, self.cache_hits = reasoning, hits
        self.alias, self.output_truncated = alias, output_truncated
        self.degeneration_retry = degeneration_retry


class _Forecast:
    def __init__(self) -> None:
        self.run_id: UUID = uuid4()


class _Result:
    def __init__(self, manifest: FakeManifest) -> None:
        self.manifest, self.forecast = manifest, _Forecast()
        self.run_dir = Path()


def _healthy() -> _Result:
    return _Result(
        FakeManifest(fidelity=_Fidelity(), quality=_Quality(), agents=(_Agent(3773, 0), _Agent()))
    )


class Recorder:
    """Stands in for `execute`, scripted per call."""

    def __init__(
        self, outcomes: list[object], artifacts: tuple[str, ...] = REQUIRED_ARTIFACTS
    ) -> None:
        self.outcomes = list(outcomes)
        self.artifacts = artifacts
        self.calls: list[dict[str, object]] = []

    def __call__(self, request: Any, **kwargs: Any) -> object:
        self.calls.append({"ticker": request.ticker, "as_of": request.as_of, **kwargs})
        outcome = self.outcomes.pop(0) if self.outcomes else _healthy()
        if isinstance(outcome, BaseException):
            raise outcome
        result = cast(_Result, outcome)
        # Write the artifacts a real run would, so the runner's verification is
        # genuinely exercised rather than stubbed past.
        run_dir = Path(kwargs["runs_dir"]) / str(result.forecast.run_id)
        if self.artifacts:
            run_dir.mkdir(parents=True, exist_ok=True)
            for name in self.artifacts:
                # The trace gets a plausible body: three agents, each recording at
                # least one call. "x" is not a trace, and the guard now says so.
                body = (
                    "".join(
                        f'{{"stage":"{stage}"}}\n'
                        for stage in ("intake", "analyst", "structuralist")
                    )
                    if name == "trace.jsonl"
                    else "x"
                )
                (run_dir / name).write_text(body, encoding="utf-8")
        result.run_dir = run_dir
        return result


def _wiring(run_id: UUID) -> Any:
    """Fresh per item, mirroring production: a shared CountingTrace would report
    band-cumulative counters in every manifest."""
    return SimpleNamespace(
        agents=object(), market=object(), dividends=object(), trace=SimpleNamespace()
    )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[object],
    tmp_path: Path,
    items: tuple[CorpusItem, ...] | None = None,
    **overrides: Any,
) -> tuple[Health, Ledger, Recorder]:
    recorder = Recorder(outcomes)
    monkeypatch.setattr("mapf.corpus.runner.execute", recorder)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    config = RunnerConfig(runs_dir=tmp_path / "runs", price_vintage=VINTAGE, **overrides)
    health = run_band(
        items if items is not None else plan(_corpus(), "clean"),
        documents=lambda item: (),
        wiring=_wiring,
        ledger=ledger,
        config=config,
        sleep=lambda _: None,
    )
    return health, ledger, recorder


def test_a_clean_pass_completes_every_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    health, ledger, _ = _run(monkeypatch, [], tmp_path)
    assert health.completed == 3
    assert health.failed == 0
    assert len(list(ledger.entries())) == 3


def test_charts_are_never_rendered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """727 self-contained charts is ~3.3GB of identical JavaScript."""
    _, _, recorder = _run(monkeypatch, [], tmp_path)
    assert all(call["render_chart"] is False for call in recorder.calls)


def test_every_corpus_item_records_that_it_came_from_the_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The counterpart to `map run --from-edgar`, which records "edgar".

    A `freeze_version` already implies a corpus run, but the implication runs one
    way only: a run without one could be news, EDGAR, or a corpus run that predates
    the field. The claim is made positively at both call sites or at neither.
    """
    _, _, recorder = _run(monkeypatch, [], tmp_path)
    assert {call["document_source"] for call in recorder.calls} == {"corpus"}


def test_rendering_is_asserted_not_merely_defaulted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A default is a property of a call site someone can change."""
    with pytest.raises(FreezeMismatchError, match="chart rendering must be off"):
        _run(monkeypatch, [], tmp_path, render_chart=True)


def test_the_price_vintage_is_pinned_for_every_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run crossing midnight must not refetch into a new vintage (ADR 0012)."""
    _, _, recorder = _run(monkeypatch, [], tmp_path)
    assert {call["today"] for call in recorder.calls} == {VINTAGE}


def test_as_of_follows_the_filing_not_the_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, recorder = _run(monkeypatch, [], tmp_path)
    stamps = [cast(datetime, call["as_of"]) for call in recorder.calls]
    dates = sorted({stamp.date() for stamp in stamps})
    assert dates == [date(2026, 2, 4), date(2026, 5, 5)]


def test_a_resume_skips_completed_items_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _run(
        monkeypatch,
        [_healthy(), InferenceUnreachableError("http://x", "down"), _healthy()],
        tmp_path,
    )
    before = list(Ledger(tmp_path / "ledger.jsonl").entries())
    completed = {e.key for e in before if e.status == "complete"}

    recorder = Recorder([])
    monkeypatch.setattr("mapf.corpus.runner.execute", recorder)
    run_band(
        plan(_corpus(), "clean"),
        documents=lambda item: (),
        wiring=_wiring,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        config=RunnerConfig(runs_dir=tmp_path / "runs", price_vintage=VINTAGE),
        sleep=lambda _: None,
    )
    # Only the items that never completed are re-attempted.
    assert len(recorder.calls) == 3 - len(completed)


def test_a_transient_failure_is_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    health, _, recorder = _run(
        monkeypatch,
        [InferenceUnreachableError("http://x", "down"), _healthy()],
        tmp_path,
        items=(CorpusItem("AAA", "clean", date(2026, 2, 3)),),
    )
    assert health.completed == 1
    assert len(recorder.calls) == 2


def test_a_non_transient_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retrying a repair-exhausted forecast reproduces it and wastes the budget."""
    health, _, recorder = _run(
        monkeypatch,
        [ForecastRepairExhausted(3, ("bad",), "{}")],
        tmp_path,
        items=(CorpusItem("AAA", "clean", date(2026, 2, 3)),),
        max_band_failure_rate=1.0,
    )
    assert health.failed == 1
    assert len(recorder.calls) == 1


def test_retries_are_exhausted_then_recorded_as_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    health, ledger, recorder = _run(
        monkeypatch,
        [InferenceTimeoutError("m", 600.0)] * 3,
        tmp_path,
        items=(CorpusItem("AAA", "clean", date(2026, 2, 3)),),
        max_band_failure_rate=1.0,
    )
    assert len(recorder.calls) == 3
    entry = next(iter(ledger.entries()))
    assert entry.status == "failed"
    assert entry.reason == "inference_timeout"


def test_consecutive_failures_halt_the_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A corpus with items missing is no longer the corpus that was frozen."""
    items = tuple(CorpusItem(f"T{i}", "clean", date(2026, 2, 3)) for i in range(10))
    with pytest.raises(CorpusHaltedError, match="consecutive failures"):
        _run(
            monkeypatch,
            [ForecastRepairExhausted(3, ("bad",), "{}")] * 10,
            tmp_path,
            items=items,
            max_consecutive_failures=3,
            max_band_failure_rate=1.0,
        )


def test_the_halt_reports_failures_by_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Systematic failure must look different from scattered bad luck."""
    items = tuple(CorpusItem(f"T{i}", "clean", date(2026, 2, 3)) for i in range(5))
    with pytest.raises(CorpusHaltedError) as caught:
        _run(
            monkeypatch,
            [MarketDataUnavailableError("yf", "throttled")] * 5,
            tmp_path,
            items=items,
            max_consecutive_failures=3,
            max_band_failure_rate=1.0,
        )
    assert caught.value.counts == {"market_data": 3}
    assert "market_data=3" in str(caught.value)


def test_scattered_failures_halt_on_the_rate_not_the_streak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    items = tuple(CorpusItem(f"T{i}", "clean", date(2026, 2, 3)) for i in range(10))
    outcomes: list[object] = []
    for i in range(10):
        outcomes.append(ForecastRepairExhausted(3, ("bad",), "{}") if i % 2 == 0 else _healthy())
    with pytest.raises(CorpusHaltedError, match="exceeds"):
        _run(
            monkeypatch,
            outcomes,
            tmp_path,
            items=items,
            max_consecutive_failures=99,
            max_band_failure_rate=0.1,
        )


def test_work_done_before_a_halt_is_durable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A halt must cost the diagnosis, never the nights already spent."""
    items = tuple(CorpusItem(f"T{i}", "clean", date(2026, 2, 3)) for i in range(6))
    outcomes: list[object] = [_healthy(), _healthy()]
    outcomes += [ForecastRepairExhausted(3, ("bad",), "{}")] * 4
    with pytest.raises(CorpusHaltedError):
        _run(
            monkeypatch,
            outcomes,
            tmp_path,
            items=items,
            max_consecutive_failures=3,
            max_band_failure_rate=1.0,
        )
    entries = list(Ledger(tmp_path / "ledger.jsonl").entries())
    assert sum(1 for e in entries if e.status == "complete") == 2


# ---------------------------------------------------------------------------
# Health — visible during the run, and never a score
# ---------------------------------------------------------------------------
def test_health_accumulates_fidelity_and_quality_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    degraded = _Result(
        FakeManifest(
            fidelity=_Fidelity(unparseable=("bullish",), divergent=("bearish",)),
            quality=_Quality(ungrounded=("21",), degenerate=True),
            agents=(_Agent(100, 1),),
        )
    )
    health, _, _ = _run(
        monkeypatch, [degraded], tmp_path, items=(CorpusItem("A", "clean", date(2026, 2, 3)),)
    )
    assert health.unparseable == 1
    assert health.divergent == 1
    assert health.ungrounded_numerals == 1
    assert health.degenerate_spread == 1
    assert health.reasoning_tokens == 100
    assert health.cache_hits == 1
    assert health.fidelity_ok is False


def test_fidelity_is_ok_when_nothing_diverged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    health, _, _ = _run(monkeypatch, [], tmp_path)
    assert health.fidelity_ok is True


def test_health_carries_no_score() -> None:
    """ADR 0019 §7: nothing the runner reports may inform the continuation rule."""
    fields = set(Health().__dict__)
    forbidden = {"crps", "score", "skill", "brier", "log_score", "leakage", "calibration"}
    assert not (fields & forbidden)


def test_budget_exhaustion_is_counted_separately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    health, _, _ = _run(
        monkeypatch,
        [ModelBudgetExhaustedError("gemma", 12000, 11997)],
        tmp_path,
        items=(CorpusItem("A", "clean", date(2026, 2, 3)),),
        max_band_failure_rate=1.0,
    )
    assert health.budget_exhausted == 1
    assert health.by_reason == {"budget_exhausted": 1}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InferenceUnreachableError("http://x", "down"), "inference_unreachable"),
        (InferenceTimeoutError("m", 600.0), "inference_timeout"),
        (ModelBudgetExhaustedError("m", 1, 1), "budget_exhausted"),
        (MarketDataUnavailableError("p", "r"), "market_data"),
        (ForecastRepairExhausted(3, ("bad",), "{}"), "repair_exhausted"),
        (MapError("x"), "other"),
    ],
)
def test_failure_reasons_are_classified(error: MapError, expected: str) -> None:
    assert _reason_for(error) == expected


def test_absorb_defaults_an_unlabelled_failure_to_other() -> None:
    health = Health()
    _absorb(health, LedgerEntry(ticker="A", band="clean", filing_date=VINTAGE, status="failed"))
    assert health.by_reason == {"other": 1}


# ---------------------------------------------------------------------------
# Ledger durability
# ---------------------------------------------------------------------------
def test_the_ledger_path_is_exposed(tmp_path: Path) -> None:
    assert Ledger(tmp_path / "l.jsonl").path == tmp_path / "l.jsonl"


def test_a_truncated_final_line_is_skipped_not_raised_on(tmp_path: Path) -> None:
    """A process killed mid-append must cost one item, never the whole resume."""
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(LedgerEntry(ticker="A", band="clean", filing_date=VINTAGE, status="complete"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"ticker": "B", "band": "cle')  # killed mid-write
    assert [e.ticker for e in ledger.entries()] == ["A"]
    assert ledger.completed() == {("A", "clean", VINTAGE)}


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(LedgerEntry(ticker="A", band="clean", filing_date=VINTAGE, status="complete"))
    path.write_text(path.read_text() + "\n\n", encoding="utf-8")
    assert len(list(ledger.entries())) == 1


def test_an_absent_ledger_reads_as_empty(tmp_path: Path) -> None:
    assert list(Ledger(tmp_path / "missing.jsonl").entries()) == []


def test_failed_items_are_not_treated_as_done(tmp_path: Path) -> None:
    """A failure must be retried on the next pass, or an outage costs the run."""
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(LedgerEntry(ticker="A", band="clean", filing_date=VINTAGE, status="failed"))
    assert ledger.completed() == set()


def test_no_material_facts_is_classified() -> None:
    assert _reason_for(NoMaterialFactsError("AAPL", 0)) == "no_material_facts"


def test_a_malformed_frozen_model_entry_is_skipped_not_fatal() -> None:
    """Prompts are the load-bearing check; a junk model entry must not mask them."""
    frozen = {**FROZEN, "models": {"analyst": "not-a-mapping"}}
    verify_freeze(frozen, live_digest=MATCHING, live_models=LIVE_MODELS)


# ---------------------------------------------------------------------------
# Transient versus terminal — what a resume retries
# ---------------------------------------------------------------------------
def test_a_missing_exhibit_is_classified_and_terminal() -> None:
    assert _reason_for(MissingExhibitError("no EX-99.1")) == "missing_exhibit"
    assert is_terminal("missing_exhibit") is True


def test_a_server_outage_is_transient() -> None:
    assert is_terminal("inference_unreachable") is False
    assert is_terminal(None) is False


def test_a_terminal_failure_is_not_retried_on_the_next_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A filing with no exhibit has none next time either. Retrying it every pass
    would consume the failure threshold until the run halts on an impossible item."""
    item = (CorpusItem("AAA", "clean", date(2026, 2, 3)),)
    _run(
        monkeypatch,
        [MissingExhibitError("no EX-99.1")],
        tmp_path,
        items=item,
        max_band_failure_rate=1.0,
    )
    recorder = Recorder([])
    monkeypatch.setattr("mapf.corpus.runner.execute", recorder)
    run_band(
        item,
        documents=lambda i: (),
        wiring=_wiring,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        config=RunnerConfig(runs_dir=tmp_path / "runs", price_vintage=VINTAGE),
        sleep=lambda _: None,
    )
    assert recorder.calls == []


def test_a_transient_failure_is_retried_on_the_next_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item = (CorpusItem("AAA", "clean", date(2026, 2, 3)),)
    _run(
        monkeypatch,
        [InferenceUnreachableError("http://x", "down")] * 3,
        tmp_path,
        items=item,
        max_band_failure_rate=1.0,
    )
    recorder = Recorder([])
    monkeypatch.setattr("mapf.corpus.runner.execute", recorder)
    run_band(
        item,
        documents=lambda i: (),
        wiring=_wiring,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        config=RunnerConfig(runs_dir=tmp_path / "runs", price_vintage=VINTAGE),
        sleep=lambda _: None,
    )
    assert len(recorder.calls) == 1


def test_resolved_reports_terminal_outcomes(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(LedgerEntry(ticker="A", band="clean", filing_date=VINTAGE, status="complete"))
    ledger.append(
        LedgerEntry(
            ticker="B",
            band="clean",
            filing_date=VINTAGE,
            status="failed",
            reason="missing_exhibit",
        )
    )
    ledger.append(
        LedgerEntry(
            ticker="C",
            band="clean",
            filing_date=VINTAGE,
            status="failed",
            reason="inference_timeout",
        )
    )
    resolved = ledger.resolved()
    assert {k[0] for k in resolved} == {"A", "B"}
    assert resolved[("B", "clean", VINTAGE)].reason == "missing_exhibit"


def test_the_progress_hook_sees_every_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The runner is a library; the CLI supplies the line that gets watched."""
    seen: list[tuple[int, int, str]] = []
    recorder = Recorder([])
    monkeypatch.setattr("mapf.corpus.runner.execute", recorder)
    run_band(
        plan(_corpus(), "clean"),
        documents=lambda i: (),
        wiring=_wiring,
        ledger=Ledger(tmp_path / "l.jsonl"),
        config=RunnerConfig(runs_dir=tmp_path / "runs", price_vintage=VINTAGE),
        sleep=lambda _: None,
        on_progress=lambda i, t, item, e, h: seen.append((i, t, item.ticker)),
    )
    assert [(i, t) for i, t, _ in seen] == [(1, 3), (2, 3), (3, 3)]


# ---------------------------------------------------------------------------
# Status classification — finer than the exception type
# ---------------------------------------------------------------------------
REAL_400 = (
    '{"error":"Engine protocol predict request received: the request (13830 tokens) '
    'exceeds the available context size (8192 tokens)"}'
)


def test_a_context_overflow_is_terminal_not_transient() -> None:
    """The first corpus run recorded eight of these as transient `other`. Retrying
    them consumes the failure allowance each pass until the run halts again on
    items that can never succeed."""
    reason = _reason_for(InferenceStatusError(400, REAL_400))
    assert reason == "context_overflow"
    assert is_terminal(reason) is True


def test_a_server_error_stays_transient() -> None:
    """HTTP 500 from a loaded server is exactly what a retry exists for."""
    reason = _reason_for(InferenceStatusError(500, "internal server error"))
    assert reason == "other"
    assert is_terminal(reason) is False


def test_a_non_context_400_is_terminal_whatever_the_body_says() -> None:
    """This asserted the opposite until the guard audit (ADR 0022).

    The old rule matched four English phrases and sent anything else to `other` --
    transient -- so a server phrasing its refusal differently was retried on every
    resume and burned the allowance each time, which is the ADR 0020 failure
    exactly. A 4xx means THIS request is unacceptable, so an identical retry is
    refused identically. That is protocol semantics, not one vendor's wording.
    """
    reason = _reason_for(InferenceStatusError(400, "malformed json"))
    assert reason == "request_rejected"
    assert is_terminal(reason)


def test_budget_exhaustion_remains_transient_because_the_analyst_samples() -> None:
    """At temperature 0.7 a second attempt explores a different reasoning path and
    may finish inside the budget. The same reason would be terminal at temperature 0,
    so the distinction is about the sampling rather than the exception."""
    assert is_terminal("budget_exhausted") is False


@pytest.mark.parametrize(
    "body",
    ["exceeds the available context size (8192 tokens)", "context length exceeded (4096 tokens)"],
)
def test_context_phrasings_are_recognised(body: str) -> None:
    assert _reason_for(InferenceStatusError(400, body)) == "context_overflow"


def test_a_refused_oversized_prompt_is_terminal() -> None:
    """Deterministic: the same document renders the same oversized prompt on every
    attempt, so retrying only consumes the failure allowance."""
    from mapf.core.errors import PromptTooLargeError

    reason = _reason_for(PromptTooLargeError("analyst", "intake", 22368, 4384, 16384))
    assert reason == "context_overflow"
    assert is_terminal(reason) is True


# ---------------------------------------------------------------------------
# Artifacts are verified, not assumed
# ---------------------------------------------------------------------------
def test_an_item_without_a_trace_is_not_recorded_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """56 of 57 runs were once recorded complete with no trace.jsonl, because the
    ledger append happened last and the writes were assumed. Ordering is not
    verification."""
    from mapf.core.errors import MissingArtifactError

    recorder = Recorder([], artifacts=("forecast.json", "manifest.json"))
    monkeypatch.setattr("mapf.corpus.runner.execute", recorder)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with pytest.raises(CorpusHaltedError):
        run_band(
            plan(_corpus(), "clean"),
            documents=lambda item: (),
            wiring=_wiring,
            ledger=ledger,
            config=RunnerConfig(runs_dir=tmp_path / "runs", price_vintage=VINTAGE),
            sleep=lambda _: None,
        )
    entries = list(ledger.entries())
    assert all(e.status == "failed" for e in entries)
    assert all(e.reason == "missing_artifact" for e in entries)
    assert _reason_for(MissingArtifactError("r", ["trace.jsonl"])) == "missing_artifact"


def test_an_empty_artifact_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A zero-byte trace satisfies an existence check and holds no audit trail."""
    from mapf.corpus.runner import _verify_artifacts

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in REQUIRED_ARTIFACTS:
        body = (
            "".join(f'{{"stage":"{stage}"}}\n' for stage in ("intake", "analyst", "structuralist"))
            if name == "trace.jsonl"
            else "x"
        )
        (run_dir / name).write_text(body, encoding="utf-8")
    _verify_artifacts(run_dir, "r")

    (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(Exception, match="trace.jsonl"):
        _verify_artifacts(run_dir, "r")


def test_a_missing_artifact_is_terminal() -> None:
    """Re-running would reproduce it; the defect is in the run, not the moment."""
    assert is_terminal("missing_artifact") is True


def test_a_complete_item_writes_every_required_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    health, ledger, recorder = _run(monkeypatch, [], tmp_path)
    assert health.completed == 3
    run_dir = Path(recorder.calls[0]["runs_dir"])  # type: ignore[arg-type]
    written = {p.name for d in run_dir.iterdir() for p in d.iterdir()}
    assert set(REQUIRED_ARTIFACTS) <= written


def test_an_unreachable_edgar_is_not_the_filing_s_fault() -> None:
    """DNS dropped and five items failed together. What they had in common was the
    afternoon, so a repeat says nothing about any of them (ADR 0024)."""
    from mapf.core.errors import ExhibitUnreachableError
    from mapf.corpus.ledger import ALWAYS_RETRIED

    reason = _reason_for(ExhibitUnreachableError("EDGAR was unreachable: [Errno 8]"))
    assert reason == "exhibit_unreachable"
    assert reason in ALWAYS_RETRIED
    assert not is_terminal(reason)


def test_an_edgar_refusal_is_evidence_about_the_filing() -> None:
    """The server answered. A 404 is its view of this filing, and the same view next
    pass — so unlike an outage, a repeat here does mean something."""
    from mapf.core.errors import ExhibitError
    from mapf.corpus.ledger import ALWAYS_RETRIED

    reason = _reason_for(ExhibitError("EDGAR refused: HTTP 404"))
    assert reason == "exhibit_error"
    assert reason not in ALWAYS_RETRIED


def test_a_missing_exhibit_still_outranks_both() -> None:
    """`MissingExhibitError` subclasses `ExhibitError`, so the order of the isinstance
    checks is load-bearing: a filing with no EX-99.1 must not be reported as an EDGAR
    refusal, which would make it look like something a retry could change."""
    assert _reason_for(MissingExhibitError("no EX-99.1")) == "missing_exhibit"


def test_a_drifted_truncation_ratio_refuses_the_run() -> None:
    """The gap that let a 3.5 basis and a 3.0 basis coexist: the ratio is in the
    frozen record and was never compared, while the banner said the freeze matched."""
    from mapf.core.truncation import rule_id

    frozen = {
        "prompts": {"intake": {"template": "intake.v2.md", "version": "v2", "sha256": "a" * 64}},
        "models": {},
        "truncation": {"rule_id": rule_id(), "chars_per_token_estimate": 3.5},
    }
    with pytest.raises(FreezeMismatchError, match="chars_per_token_estimate"):
        verify_freeze(frozen, live_digest=lambda *_: "a" * 64, live_models={})


def test_a_matching_truncation_block_passes() -> None:
    from mapf.core.tokens import CHARS_PER_TOKEN
    from mapf.core.truncation import HEAD_TOKENS, RULE, TAIL_TOKENS, rule_id

    frozen = {
        "prompts": {"intake": {"template": "intake.v2.md", "version": "v2", "sha256": "a" * 64}},
        "models": {},
        "truncation": {
            "rule": RULE,
            "rule_id": rule_id(),
            "head_tokens": HEAD_TOKENS,
            "tail_tokens": TAIL_TOKENS,
            "chars_per_token_estimate": CHARS_PER_TOKEN,
        },
    }
    verify_freeze(frozen, live_digest=lambda *_: "a" * 64, live_models={})


def test_a_freeze_predating_the_rule_id_is_not_refused() -> None:
    """An older record may say less than the code. It may never disagree."""
    frozen = {
        "prompts": {"intake": {"template": "intake.v2.md", "version": "v2", "sha256": "a" * 64}},
        "models": {},
        "truncation": {"rule": "head_tail_v1"},
    }
    verify_freeze(frozen, live_digest=lambda *_: "a" * 64, live_models={})
