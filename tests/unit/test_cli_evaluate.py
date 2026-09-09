"""`map evaluate` — the only place scores appear, and the refusals that guard them.

The separation from `map corpus run` is worth nothing if this command answers on a
half-finished band, so the refusals are the substance rather than error handling.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock
from uuid import UUID, uuid4

import numpy as np
import pytest
from typer.testing import CliRunner

from mapf.cli.app import app
from mapf.cli.commands.evaluate import FreezeBases, _freeze_bases, _frozen_by_digest
from mapf.core.models import (
    Bar,
    Forecast,
    ModelVersions,
    PriceWindow,
    Scenario,
    ScenarioSet,
)
from mapf.core.provenance import freeze_digest
from mapf.corpus.ledger import Ledger, LedgerEntry
from mapf.eval.baselines import BaselineError
from mapf.eval.scorer import BandScores, score_band
from tests.unit.test_cli import _config
from tests.unit.test_cli_corpus import _frozen

runner = CliRunner()

# The two clean items of the fixture corpus, and the day each forecast opens: the
# runner dates a forecast one day after the filing it reads.
CLEAN = (date(2026, 2, 1), date(2026, 5, 1))
AMBIGUOUS = date(2025, 2, 1)
SERIES_START = date(2024, 1, 1)
SERIES_DAYS = 900


def _bars() -> list[Bar]:
    """A deterministic daily series, generated rather than fetched.

    Calendar-daily rather than business-daily so every `as_of` lands on a bar and
    the scorer's fallback to the nearest earlier close is never exercised here —
    that path has its own test in `test_scorer`.
    """
    rng = np.random.default_rng(20260830)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.011, SERIES_DAYS)))
    return [
        Bar(
            date=SERIES_START + timedelta(days=i),
            open=float(c),
            high=float(c),
            low=float(c),
            close=float(c),
            volume=1_000_000,
        )
        for i, c in enumerate(closes)
    ]


BARS = _bars()
CLOSE_ON = {bar.date: bar.close for bar in BARS}


class _Market:
    """Serves the generated series, sliced to the requested range."""

    name = "fake"

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        window = tuple(bar for bar in BARS if start <= bar.date <= end)
        return PriceWindow(ticker=ticker, provider="fake", adjustment="split_adjusted", bars=window)


class _NoCalendar:
    """EDGAR answers for nothing — the case that makes the baseline weakest."""

    def __init__(self) -> None:
        self.failures = {"AAPL": "no CIK for 'AAPL'; it is not in the SEC index"}

    def dates_before(self, ticker: str, as_of: date) -> tuple[date, ...]:
        return ()


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No unit test may reach the network. Ever.

    This patched market data alone and let the real `EdgarEarningsCalendar` be
    built, which reached SEC on a cache miss. It never missed here, because
    `var/earnings/` holds 120 cached filers on this machine — so the promise in
    this docstring was kept by a directory the repository does not ship, not by
    anything in the fixture. On a fresh clone it would have fetched.
    """
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.build_market_data",
        lambda _settings, vintage=None: _Market(),
    )
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.build_earnings_calendar",
        lambda _settings, _client: _NoCalendar(),
    )


def _write_forecast(tmp_path: Path, run_id: UUID, filing_date: date) -> None:
    """A schema-2.0.0 forecast whose spot matches the series it will be scored on.

    A mismatched spot is what `SpotDriftError` exists to catch, so a fixture that
    guessed one would be testing the guard rather than the scoring pass.
    """
    as_of = filing_date + timedelta(days=1)

    def branch(justification: str, weight: float, ret: float) -> Scenario:
        return Scenario(
            justification=justification.ljust(20, "."),
            probability_weight=weight,
            price_return=ret,
            annualised_vol=0.30,
        )

    forecast = Forecast(
        run_id=run_id,
        ticker="AAPL",
        as_of=datetime.combine(as_of, datetime.min.time(), tzinfo=UTC),
        horizon_days=5,
        spot_price=CLOSE_ON[as_of],
        source_doc_ids=("sha256:" + "a" * 64,),
        model_versions=ModelVersions(intake="i", analyst="a", structuralist="s"),
        scenarios=ScenarioSet(
            bullish=branch("upside reasoning", 0.3, 0.04),
            base_case=branch("base reasoning", 0.4, 0.0),
            bearish=branch("downside reasoning", 0.3, -0.04),
        ),
    )
    directory = tmp_path / "runs" / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "forecast.json").write_text(forecast.model_dump_json(), encoding="utf-8")


def _invoke(tmp_path: Path, *args: str, frozen: Path | None = None):  # type: ignore[no-untyped-def]
    return runner.invoke(
        app,
        [
            "evaluate",
            "--frozen",
            str(frozen or _frozen(tmp_path)),
            "--ledger-path",
            str(tmp_path / "ledger.jsonl"),
            "--runs-dir",
            str(tmp_path / "runs"),
            # Pins go to the sandbox: a suite that writes fixture outcomes into the
            # real store would pin the corpus to values no market ever produced.
            "--pins-path",
            str(tmp_path / "realised_pins.jsonl"),
            # And so do scoring records, for the same reason and after the same
            # mistake: the first run of this suite against a defaulted --scores-dir
            # wrote two fabricated AAPL passes into var/corpus/scores/, one of them
            # labelled `holdout`. Second instance of a CLI default reaching a real
            # store from a test (Findings #39).
            "--scores-dir",
            str(tmp_path / "scores"),
            # And its own config. `map evaluate` had no --config at all and called a
            # bare load(), so these tests read the repository's real
            # config/default.toml -- which carries a placeholder SEC user-agent and
            # is rescued on this machine only by a gitignored config/local.toml.
            "--config",
            str(_config(tmp_path)),
            # Unpinned: these tests serve prices from a fake provider, so there is
            # no snapshot to read and a frozen vintage would refuse every window.
            *(() if "--vintage" in args else ("--vintage", "")),
            *(() if "--split" in args else ("--split", "dev")),
            *args,
        ],
    )


def _finish(tmp_path: Path, run_ids: list[UUID] | None = None) -> Ledger:
    """Complete both clean items of the fixture corpus."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for i, day in enumerate(CLEAN):
        run_id = run_ids[i] if run_ids else uuid4()
        ledger.append(
            LedgerEntry(
                ticker="AAPL",
                band="clean",
                filing_date=day,
                status="complete",
                run_id=run_id,
            )
        )
        _write_forecast(tmp_path, run_id, day)
    return ledger


def _one_run_trace() -> str:
    """What one run leaves behind: three agents, each recording at least one call.

    A single line is not a plausible trace and the guard now says so, so a fixture
    that wrote one was asserting against a shape the pipeline never produces.
    """
    return "".join(f'{{"stage":"{stage}"}}\n' for stage in ("intake", "analyst", "structuralist"))


def _manifest(
    tmp_path: Path,
    run_id: UUID,
    commit: str | None,
    dirty: bool = False,
    trace: bool = True,
    freeze: str | None = None,
    digest: str | None = None,
    freeze_digest: str | None = None,
) -> None:
    directory = tmp_path / "runs" / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {}
    if commit is not None:
        version: dict[str, object] = {
            "commit": commit,
            "dirty": dirty,
            # Defaults to a digest derived from the commit, so a fixture that varies
            # the commit varies the digest too — which is what the equality test now
            # actually reads (ADR 0026).
            "forecast_digest": digest if digest is not None else commit[:1] * 64,
        }
        if digest == "":
            # An empty string stands for "the field is absent", which is what a run
            # written before the digest existed actually looks like.
            del version["forecast_digest"]
        body["code_version"] = version
    if freeze is not None:
        body["freeze_version"] = freeze
        # Derived from the version so a fixture varying one varies the other; the
        # digest is what the equality test reads (ADR 0029). Tests that need two
        # versions to SHARE governing content set the digest explicitly.
        body["freeze_digest"] = (
            freeze_digest
            if freeze_digest is not None
            else hashlib.sha256(freeze.encode()).hexdigest()
        )
    (directory / "manifest.json").write_text(json.dumps(body), encoding="utf-8")
    if trace:
        (directory / "trace.jsonl").write_text(_one_run_trace(), encoding="utf-8")


def _traces_for(tmp_path: Path, ids: list[UUID]) -> None:
    """Every completed item needs one, or scoring refuses."""
    for run_id in ids:
        d = tmp_path / "runs" / str(run_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "trace.jsonl").write_text(_one_run_trace(), encoding="utf-8")


# ---------------------------------------------------------------------------
# The refusal that protects the continuation rule
# ---------------------------------------------------------------------------
def test_an_unfinished_band_is_refused(tmp_path: Path) -> None:
    """Looking at a half-band before deciding whether to run the rest is exactly
    the data-dependent stopping the two-pass design prevents."""
    result = _invoke(tmp_path)
    assert result.exit_code == 8
    assert "REFUSED" in result.output
    assert "outstanding" in result.output


def test_a_partially_finished_band_is_still_refused(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(ticker="AAPL", band="clean", filing_date=date(2026, 2, 1), status="complete")
    )
    result = _invoke(tmp_path)
    assert result.exit_code == 8


def test_a_declared_single_pass_is_accepted(tmp_path: Path) -> None:
    """A deliberate stop is a legitimate outcome — provided it was declared."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    run_id = uuid4()
    ledger.append(
        LedgerEntry(
            ticker="AAPL",
            band="clean",
            filing_date=CLEAN[0],
            status="complete",
            run_id=run_id,
        )
    )
    _write_forecast(tmp_path, run_id, CLEAN[0])
    _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    result = _invoke(tmp_path, "--declared", "clean_half_1")
    assert result.exit_code == 0
    assert "clean_half_1" in result.output


def test_a_finished_band_reports_every_pass(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _traces_for(tmp_path, ids)
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "clean_half_1" in result.output
    assert "clean_half_2" in result.output


# ---------------------------------------------------------------------------
# Code provenance across a resumed corpus
# ---------------------------------------------------------------------------
def test_a_single_commit_is_reported(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40)
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "aaaaaaaaaaaa" in result.output
    assert "2 runs" in result.output


def test_two_commits_refuse_unless_acknowledged(tmp_path: Path) -> None:
    """A resumed corpus spanning commits is sometimes fine and sometimes the
    explanation for everything, so it is surfaced rather than averaged."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40)
    _manifest(tmp_path, ids[1], "b" * 40)
    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "more than one forecast digest" in result.output
    assert "aaaaaaaaaaaa" in result.output and "bbbbbbbbbbbb" in result.output


def test_mixed_commits_can_be_scored_when_acknowledged(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40)
    _manifest(tmp_path, ids[1], "b" * 40)
    result = _invoke(tmp_path, "--allow-mixed-code")
    assert result.exit_code == 0


def test_a_dirty_tree_is_visible_in_the_report(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, dirty=True)
    result = _invoke(tmp_path)
    assert "+dirty" in result.output


def test_runs_predating_the_field_report_unknown(tmp_path: Path) -> None:
    """The current corpus started before code_version existed; that is recorded as
    unknown rather than retrofitted."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, None)
    result = _invoke(tmp_path)
    assert "predates the field" in result.output


def test_missing_manifests_are_reported_rather_than_assumed(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _traces_for(tmp_path, ids)
    result = _invoke(tmp_path)
    assert "no manifests found" in result.output


def test_an_unreadable_manifest_is_skipped(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40)
    broken = tmp_path / "runs" / str(ids[1])
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    (broken / "trace.jsonl").write_text(_one_run_trace(), encoding="utf-8")
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "1 runs" in result.output


# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------
def test_a_missing_frozen_corpus_is_a_sentence(tmp_path: Path) -> None:
    result = _invoke(tmp_path, frozen=tmp_path / "absent.json")
    assert result.exit_code != 0
    assert "no frozen corpus" in result.output


def test_an_unknown_band_lists_the_real_ones(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--band", "nonsense")
    assert result.exit_code == 2
    assert "clean" in result.output


def test_a_completed_item_with_no_run_id_refuses_rather_than_shrinking_the_sample(
    tmp_path: Path,
) -> None:
    """Skipping it would remove from the sample exactly the items whose bookkeeping
    is broken, which is a selection effect rather than a smaller sample."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(LedgerEntry(ticker="AAPL", band="clean", filing_date=CLEAN[0], status="complete"))
    result = _invoke(tmp_path, "--declared", "clean_half_1")
    assert result.exit_code != 0
    assert "record no run id" in result.output


def test_a_finished_band_is_scored_end_to_end(tmp_path: Path) -> None:
    """This asserted `not yet implemented` until the pass was wired. It now asserts
    the shape of a real result: a vintage, a count, a paired comparison against each
    baseline, and a calibration ratio."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "vintage    fake / split_adjusted" in result.output
    assert "scored     2 items" in result.output
    assert "M.A.P. vs random_walk" in result.output
    assert "calibration:" in result.output


def test_the_scored_set_comes_from_the_ledger_not_the_directory(tmp_path: Path) -> None:
    """`runs/` still holds first-capture and the loose UUIDs of the first live
    forecasts — different prompts, a different horizon, an older schema. Scanning
    would find them and several would even parse."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    stray = tmp_path / "runs" / "first-capture-v2"
    stray.mkdir(parents=True)
    (stray / "forecast.json").write_text('{"schema_version": "1.0.0"}', encoding="utf-8")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "scored     2 items" in result.output
    assert "from the ledger and not by scanning" in result.output
    assert "1 run director" in result.output


def test_a_ledger_item_absent_from_the_frozen_corpus_refuses(tmp_path: Path) -> None:
    """The ledger and the corpus have diverged, so every rate reported afterwards
    would have the wrong denominator."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    intruder = uuid4()
    for run_id in (*ids, intruder):
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(
            ticker="MSFT",
            band="clean",
            filing_date=date(2026, 3, 3),
            status="complete",
            run_id=intruder,
        )
    )
    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "absent from the frozen corpus" in result.output
    assert "MSFT" in result.output


def test_a_forecast_for_the_wrong_ticker_refuses(tmp_path: Path) -> None:
    """A file in the right directory is not proof it belongs to the right item;
    scoring it would attribute one ticker's forecast to another's outcome."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    path = tmp_path / "runs" / str(ids[0]) / "forecast.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["ticker"] = "MSFT"
    path.write_text(json.dumps(body), encoding="utf-8")

    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "item-to-run mapping is broken" in result.output


def test_leakage_is_not_reported_on_a_half_finished_other_band(tmp_path: Path) -> None:
    """A leakage estimate on an unfinished band is a different number, not a
    preliminary one — the same rule that governs the pass boundary."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    result = _invoke(tmp_path)
    assert "leakage: not reported" in result.output
    assert "outstanding" in result.output


def test_both_pre_registered_sensitivity_checks_run_unconditionally(tmp_path: Path) -> None:
    """Declared before any score existed, so they are not an option here."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    output = _invoke(tmp_path).output
    assert "ADR 0020" in output
    assert "ADR 0021" in output


def test_the_config_option_is_not_required(tmp_path: Path) -> None:
    """Evaluation reads artifacts, not the inference config."""
    _config(tmp_path)
    assert _invoke(tmp_path).exit_code in (0, 8)


def test_a_malformed_frozen_corpus_is_a_sentence(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"corpus": {"nope": 1}}', encoding="utf-8")
    result = _invoke(tmp_path, frozen=broken)
    assert result.exit_code != 0
    assert "not a readable frozen corpus" in result.output


def test_unparseable_json_is_a_sentence(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    result = _invoke(tmp_path, frozen=broken)
    assert "not a readable frozen corpus" in result.output


def test_a_zero_pass_split_is_rejected(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--passes", "0")
    assert result.exit_code == 2
    assert "at least 1" in result.output


def test_an_unexpected_map_error_arrives_as_a_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CLI is an API: every failure a user can cause must be a sentence and an
    exit code, never a traceback."""
    from mapf.core.errors import SymbolIndexMissingError

    def explode(*args: object, **kwargs: object) -> None:
        raise SymbolIndexMissingError("/tmp/x.sqlite")

    monkeypatch.setattr("mapf.cli.commands.evaluate.require_finished", explode)
    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# An unauditable forecast is not scoreable
# ---------------------------------------------------------------------------
def test_a_completed_item_without_a_trace_refuses_scoring(tmp_path: Path) -> None:
    """56 of 57 runs once had no trace and were recorded complete anyway. Full
    provenance is the claim the result rests on."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40)
    _manifest(tmp_path, ids[1], "a" * 40, trace=False)
    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "no usable trace" in result.output
    assert "cannot be audited" in result.output


def test_an_empty_trace_counts_as_missing(tmp_path: Path) -> None:
    """A zero-byte file satisfies an existence check and holds no audit trail."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _traces_for(tmp_path, ids)
    (tmp_path / "runs" / str(ids[1]) / "trace.jsonl").write_text("", encoding="utf-8")
    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "no usable trace" in result.output


def test_a_fully_traced_band_passes_the_check(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _traces_for(tmp_path, ids)
    result = _invoke(tmp_path)
    assert "every completed item has a trace" in result.output


# ---------------------------------------------------------------------------
# The frozen record (ADR 0022)
# ---------------------------------------------------------------------------
def test_a_single_freeze_is_reported(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "(v2.3.0) (2 runs)" in result.output


def test_a_band_spanning_two_freezes_refuses(tmp_path: Path) -> None:
    """The freeze governs sampling, truncation and corpus membership, so two items
    produced under different records were not asked the same question."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.2.0")
    _manifest(tmp_path, ids[1], "a" * 40, freeze="2.3.0")
    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "2 distinct forecast-governing digests" in result.output
    assert "v2.2.0" in result.output and "v2.3.0" in result.output


def test_a_mixed_freeze_has_no_override(tmp_path: Path) -> None:
    """Deliberately unlike --allow-mixed-code. A refactor between commits can be
    harmless; two freezes cannot be."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.2.0")
    _manifest(tmp_path, ids[1], "a" * 40, freeze="2.3.0")
    assert _invoke(tmp_path, "--allow-mixed-code").exit_code == 2


def test_runs_predating_the_freeze_field_report_unknown(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40)
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "predates the field" in result.output


def test_a_trace_holding_more_than_one_run_refuses_scoring(tmp_path: Path) -> None:
    """A file-exists check passes the incident's own worst artifact: the one
    directory whose trace held every item's events."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, trace=False, freeze="2.3.0")
    _manifest(tmp_path, ids[1], "a" * 40, freeze="2.3.0")
    directory = tmp_path / "runs" / str(ids[0])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "trace.jsonl").write_text('{"stage":"intake"}\n' * 200, encoding="utf-8")
    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "cannot be audited" in result.output
    assert "more than one run can produce" in result.output


def test_a_band_where_nothing_could_be_scored_is_a_sentence(tmp_path: Path) -> None:
    """Refused, not reported as an empty result: a comparison over zero items has
    no interval, and printing one would put a shape where a number belongs."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
        # A spot the series cannot produce: every item fails on SpotDriftError.
        path = tmp_path / "runs" / str(run_id) / "forecast.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body["spot_price"] = 1.0
        path.write_text(json.dumps(body), encoding="utf-8")

    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "no item of the clean band could be scored" in result.output
    assert "SpotDriftError" in result.output


def test_an_unscoreable_item_is_counted_by_reason(tmp_path: Path) -> None:
    """Counted rather than dropped: a shrinking sample must say why it shrank."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    path = tmp_path / "runs" / str(ids[0]) / "forecast.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["spot_price"] = 1.0
    path.write_text(json.dumps(body), encoding="utf-8")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "scored     1 items" in result.output
    assert "1 unscored: SpotDriftError" in result.output


def test_leakage_is_reported_when_both_bands_are_finished(tmp_path: Path) -> None:
    """The headline number of the whole project: clean-band performance minus
    ambiguous-band performance, reported as a difference rather than two results."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    ambiguous_id = uuid4()
    Ledger(tmp_path / "ledger.jsonl").append(
        LedgerEntry(
            ticker="AAPL",
            band="ambiguous",
            filing_date=AMBIGUOUS,
            status="complete",
            run_id=ambiguous_id,
        )
    )
    _write_forecast(tmp_path, ambiguous_id, AMBIGUOUS)
    for run_id in (*ids, ambiguous_id):
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "leakage: clean" in result.output
    assert "n=2/1" in result.output


def test_a_sensitivity_subset_that_exists_is_reported_with_its_size(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for i, day in enumerate(CLEAN):
        ledger.append(
            LedgerEntry(
                ticker="AAPL",
                band="clean",
                filing_date=day,
                status="complete",
                run_id=ids[i],
                truncated=i == 0,
                elided_chars=5000 if i == 0 else 0,
            )
        )
        _write_forecast(tmp_path, ids[i], day)
        _manifest(tmp_path, ids[i], "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "excluding truncated exhibits (ADR 0020) — 1 of 2 items" in result.output


def test_leakage_is_silent_when_the_other_band_scored_nothing(tmp_path: Path) -> None:
    """Finished but unscoreable is not the same as unfinished, and it is not a
    leakage estimate either. Neither is reported as the other."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    ambiguous_id = uuid4()
    Ledger(tmp_path / "ledger.jsonl").append(
        LedgerEntry(
            ticker="AAPL",
            band="ambiguous",
            filing_date=AMBIGUOUS,
            status="complete",
            run_id=ambiguous_id,
        )
    )
    _write_forecast(tmp_path, ambiguous_id, AMBIGUOUS)
    path = tmp_path / "runs" / str(ambiguous_id) / "forecast.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["spot_price"] = 1.0
    path.write_text(json.dumps(body), encoding="utf-8")
    for run_id in (*ids, ambiguous_id):
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    # The two forms the report can emit, rather than the bare word: `tmp_path`
    # carries this test's own name and contains "leakage", so a substring check on
    # that would pass on the directory rather than on anything the code did — the
    # Plotly mistake of finding #7, in a fixture.
    assert "leakage: clean" not in result.output
    assert "leakage: not reported" not in result.output


def test_a_baseline_that_declined_to_widen_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A multiplier at 1.0 is the random walk under a second name. Beating it is not
    beating a benchmark that widens for a scheduled event, and a weak baseline
    flatters the result invisibly unless the report says how weak it was."""
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.build_earnings_calendar",
        lambda _settings, _client: _NoCalendar(),
    )
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "neutral (1.00) on 2 of 2" in result.output
    assert "declined to widen" in result.output
    assert "earnings calendar: unavailable for 1 ticker" in result.output


class _FittedCalendar:
    """Prior earnings dates, so the multiplier has something to fit on.

    Supplied explicitly. This test used to pass on the REAL calendar, which found
    dates in `var/earnings/` — 120 cached filers this repository does not ship —
    so it was asserting a fitted baseline on a directory a clone does not have.
    """

    failures: dict[str, str] = {}  # noqa: RUF012 - a fake's fixed empty state

    def dates_before(self, ticker: str, as_of: date) -> tuple[date, ...]:
        return tuple(as_of - timedelta(days=90 * n) for n in range(1, 9))


def test_a_fitted_baseline_reports_its_multiplier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.build_earnings_calendar",
        lambda _settings, _client: _FittedCalendar(),
    )
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    result = _invoke(tmp_path)
    assert "earnings baseline: multiplier median" in result.output
    assert "declined to widen" not in result.output


def test_a_band_where_the_baseline_never_fitted_says_it_plainly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not the same as "fitted and declined to widen": here there is no earnings
    benchmark at all, and any win over it is a win over the random walk."""
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.build_earnings_calendar",
        lambda _settings, _client: _NoCalendar(),
    )
    monkeypatch.setattr(
        "mapf.eval.scorer.earnings_multiplier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BaselineError("too short")),
    )
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "earnings baseline: never fitted" in result.output
    assert "random walk under a second name" in result.output


# ---------------------------------------------------------------------------
# `--check`: the structural pre-flight (ADR 0025)
# ---------------------------------------------------------------------------
def _checked(tmp_path: Path, *args: str):  # type: ignore[no-untyped-def]
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    return _invoke(tmp_path, "--check", *args), ids


def test_the_check_prints_no_score(tmp_path: Path) -> None:
    """The boundary is on what is SHOWN, not on what is run. A pre-flight that
    skipped the computation would not be exercising the path that matters."""
    result, _ = _checked(tmp_path)
    assert result.exit_code == 0
    for forbidden in ("calibration", "M.A.P. vs", "indistinguishable", "leakage"):
        assert forbidden not in result.output


def test_the_check_confirms_every_item_is_scoreable(tmp_path: Path) -> None:
    result, _ = _checked(tmp_path)
    assert "scoreable  2 of 2 loaded items" in result.output
    assert "the whole path runs on real artifacts; no scores printed" in result.output


def test_the_check_reports_each_baseline_and_the_multiplier(tmp_path: Path) -> None:
    result, _ = _checked(tmp_path)
    for name in ("random_walk", "garch", "earnings_scaled_random_walk"):
        assert f"baseline   {name}" in result.output
    assert "multiplier" in result.output


def test_the_check_does_not_enforce_the_pass_boundary(tmp_path: Path) -> None:
    """SKIPPED and named. An unfinished band is the normal case for a pre-flight, so
    enforcing it here would make the check unusable for what it exists to serve."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    run_id = uuid4()
    ledger.append(
        LedgerEntry(
            ticker="AAPL",
            band="clean",
            filing_date=CLEAN[0],
            status="complete",
            run_id=run_id,
        )
    )
    _write_forecast(tmp_path, run_id, CLEAN[0])
    _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    assert _invoke(tmp_path, "--check").exit_code == 0
    assert _invoke(tmp_path).exit_code == 8  # a scoring run still refuses


def test_the_check_reports_every_problem_rather_than_the_first(tmp_path: Path) -> None:
    """A pre-flight that stopped at the first problem would have to be run once per
    problem. `map corpus run --check` reports the whole picture; so does this."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.2.0")
    _manifest(tmp_path, ids[1], "b" * 40, freeze="2.3.0")

    result = _invoke(tmp_path, "--check")
    assert result.exit_code == 2
    assert "2 problem(s) would refuse a scoring run" in result.output
    assert "more than one frozen record" in result.output
    assert "more than one forecast digest" in result.output


def test_the_check_names_the_sensitivity_members(tmp_path: Path) -> None:
    """Membership is structural, so it is named. A partition reported only as a
    count cannot be checked against the ledger, and an empty one reads as
    reassurance (finding #27)."""
    ids = [uuid4(), uuid4()]
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for i, day in enumerate(CLEAN):
        ledger.append(
            LedgerEntry(
                ticker="AAPL",
                band="clean",
                filing_date=day,
                status="complete",
                run_id=ids[i],
                truncated=i == 0,
                elided_chars=5000 if i == 0 else 0,
            )
        )
        _write_forecast(tmp_path, ids[i], day)
        _manifest(tmp_path, ids[i], "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path, "--check")
    assert "excluding truncated exhibits (ADR 0020) — 1 of 2 items" in result.output
    assert f"    AAPL {CLEAN[0] + timedelta(days=1)}" in result.output


def test_an_unscoreable_item_is_a_problem_in_check_mode(tmp_path: Path) -> None:
    """Scoring counts it and carries on; the pre-flight exists to find it first."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    path = tmp_path / "runs" / str(ids[0]) / "forecast.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["spot_price"] = 1.0
    path.write_text(json.dumps(body), encoding="utf-8")

    result = _invoke(tmp_path, "--check")
    assert result.exit_code == 2
    assert "1 unscored: SpotDriftError" in result.output
    assert "could not be scored" in result.output


class _TwoVintages:
    """One ticker served by yfinance, the next by stooq — what `ProviderChain`
    failing over per call actually produces."""

    def __init__(self) -> None:
        self._n = 0

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        self._n += 1
        window = tuple(bar for bar in BARS if start <= bar.date <= end)
        return PriceWindow(
            ticker=ticker,
            provider="yfinance" if self._n == 1 else "stooq",
            adjustment="split_adjusted",
            bars=window,
        )


def test_the_check_reports_a_mixed_vintage_as_a_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scoring raises on this; the pre-flight names both series and carries on, so
    one run shows every problem rather than the first."""
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.build_market_data",
        lambda _settings, vintage=None: _TwoVintages(),
    )
    result, _ = _checked(tmp_path)
    assert result.exit_code == 2
    assert "different series" in result.output
    assert "yfinance" in result.output and "stooq" in result.output


def test_the_check_flags_a_baseline_that_was_never_fitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A band scored against two baselines instead of three is a weaker comparison
    than the one the report will claim, and nothing else would say so."""
    monkeypatch.setattr(
        "mapf.eval.scorer.garch",
        lambda *_a, **_k: (_ for _ in ()).throw(BaselineError("no convergence")),
    )
    result, _ = _checked(tmp_path)
    assert result.exit_code == 2
    assert "0 fitted" in result.output
    assert "the garch baseline was never fitted" in result.output


def test_the_check_names_tickers_edgar_could_not_answer_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.build_earnings_calendar",
        lambda _settings, _client: _NoCalendar(),
    )
    result, _ = _checked(tmp_path)
    assert "calendar   unavailable for 1 ticker(s): AAPL" in result.output


# ---------------------------------------------------------------------------
# The forecast digest (ADR 0026)
# ---------------------------------------------------------------------------
def test_two_commits_with_one_digest_are_forecast_equivalent(tmp_path: Path) -> None:
    """The whole point. A twelve-night band spans every commit made while it runs, so
    equality on the commit is a guard that must be overridden every time — which is
    not a guard. Equality on what a forecast depends on is."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0", digest="d" * 64)
    _manifest(tmp_path, ids[1], "b" * 40, freeze="2.3.0", digest="d" * 64)

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "code       digest dddddddddddd (2 runs)" in result.output


def test_two_digests_refuse_even_on_one_commit(tmp_path: Path) -> None:
    """The converse: the digest is what is compared, not a proxy for the commit."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0", digest="d" * 64)
    _manifest(tmp_path, ids[1], "a" * 40, freeze="2.3.0", digest="e" * 64)

    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "2 distinct forecast digests" in result.output


def test_a_dirty_run_is_counted_apart_rather_than_grouped(tmp_path: Path) -> None:
    """A dirty tree has no honest digest, so it cannot be declared equivalent to
    anything — grouping it with a clean run would claim exactly that."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0", digest="d" * 64)
    _manifest(tmp_path, ids[1], "a" * 40, dirty=True, freeze="2.3.0", digest="d" * 64)

    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "+dirty (no digest)" in result.output


def test_a_run_predating_the_digest_is_labelled_as_such(tmp_path: Path) -> None:
    """Distinct from a dirty run and from an unknown commit: this one could be
    backfilled, and saying so is how someone knows to run the backfill."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0", digest="")
    _manifest(tmp_path, ids[1], "a" * 40, freeze="2.3.0", digest="d" * 64)

    result = _invoke(tmp_path)
    assert "predates the digest" in result.output


def test_the_refusal_names_the_files_that_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns the override into an informed one. The band's first split was three
    files of scoring-only additions — justifiable in one glance, and
    indistinguishable from a real change without this."""
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate._git_names",
        lambda _a, _b: ["config/default.toml", "src/mapf/eval/scorer.py"],
    )
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0", digest="d" * 64)
    _manifest(tmp_path, ids[1], "b" * 40, freeze="2.3.0", digest="e" * 64)

    result = _invoke(tmp_path)
    assert "differs: config/default.toml" in result.output
    # Excluded paths are filtered even out of the diff, or the evidence would
    # contradict the digest that produced it.
    assert "eval/scorer.py" not in result.output


def test_a_failed_git_diff_reports_nothing_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The diff is evidence for a human, never the thing being decided. Losing it
    must not turn a refusal into a crash."""
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.subprocess.run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no git")),
    )
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0", digest="d" * 64)
    _manifest(tmp_path, ids[1], "b" * 40, freeze="2.3.0", digest="e" * 64)

    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "2 distinct forecast digests" in result.output


def test_a_version_bump_that_changes_no_governing_field_does_not_split_the_band(
    tmp_path: Path,
) -> None:
    """The case this was built for: recording the execution order took the freeze
    from 2.3.0 to 2.4.0 while every field deciding what a model is asked stayed
    identical. Comparing versions would have refused the band on a restart, with no
    override — finding #27 from the side it bit last time."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0")
    _manifest(tmp_path, ids[1], "a" * 40, freeze="2.4.0")
    for run_id, version in zip(ids, ("2.3.0", "2.4.0"), strict=True):
        path = tmp_path / "runs" / str(run_id) / "manifest.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body["freeze_version"] = version
        body["freeze_digest"] = "d" * 64  # same governing content
        path.write_text(json.dumps(body), encoding="utf-8")

    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "dddddddddddd (v2.3.0, v2.4.0)" in result.output


def test_a_run_predating_the_freeze_digest_is_labelled_as_such(tmp_path: Path) -> None:
    """Distinct from a missing freeze entirely: this one can be backfilled from the
    commit, and saying so is how someone knows to run the backfill."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
        path = tmp_path / "runs" / str(run_id) / "manifest.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        del body["freeze_digest"]
        path.write_text(json.dumps(body), encoding="utf-8")

    result = _invoke(tmp_path)
    assert "predates the digest" in result.output


def test_the_freeze_refusal_names_the_governing_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mapf.cli.commands.evaluate._frozen_at",
        lambda commit: {"models": {"a": commit[:1]}, "horizon_days": 5},
    )
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.2.0")
    _manifest(tmp_path, ids[1], "b" * 40, freeze="2.3.0")

    result = _invoke(tmp_path)
    assert result.exit_code == 2
    assert "differs: models" in result.output
    assert "differs: horizon_days" not in result.output


def test_an_unrecoverable_frozen_record_reports_no_fields_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The field list is evidence for a reader, never the thing being decided."""
    monkeypatch.setattr("mapf.cli.commands.evaluate._frozen_at", lambda _c: None)
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.2.0")
    _manifest(tmp_path, ids[1], "b" * 40, freeze="2.3.0")
    assert _invoke(tmp_path).exit_code == 2


# ---------------------------------------------------------------------------
# The split filter (ADR 0031)
# ---------------------------------------------------------------------------
def test_the_split_is_required_and_has_no_default(tmp_path: Path) -> None:
    """The holdout must not be scoreable by omission, so there is nothing to omit."""
    result = runner.invoke(
        app,
        [
            "evaluate",
            "--frozen",
            str(_frozen(tmp_path)),
            "--ledger-path",
            str(tmp_path / "ledger.jsonl"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
    )
    assert result.exit_code != 0
    assert "--split" in result.output


def test_an_unknown_split_is_a_sentence(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--split", "test")
    assert result.exit_code == 2
    assert "unknown split" in result.output


def test_scoring_the_other_split_finds_nothing_of_this_one(tmp_path: Path) -> None:
    """The fixture corpus is all `dev`, so a holdout run must load zero items rather
    than silently scoring the dev half."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")
    result = _invoke(tmp_path, "--split", "holdout")
    assert result.exit_code == 2
    assert "unknown split 'holdout'" in result.output
    assert "Splits: dev" in result.output


def test_a_holdout_run_refuses_once_the_record_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And it refuses BEFORE loading anything, so no holdout number is computed."""
    spend = tmp_path / "spend.jsonl"
    spend.write_text(json.dumps({"scored_on": "2026-09-01"}) + "\n", encoding="utf-8")
    monkeypatch.setattr("mapf.cli.commands.evaluate.HOLDOUT_LEDGER", spend)
    frozen = _frozen_with_holdout(tmp_path)
    result = _invoke(tmp_path, "--split", "holdout", frozen=frozen)
    assert result.exit_code == 9
    assert "already scored" in result.output


def test_the_check_does_not_spend_the_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--check` prints no score, so it cannot spend what it never shows."""
    spend = tmp_path / "spend.jsonl"
    monkeypatch.setattr("mapf.cli.commands.evaluate.HOLDOUT_LEDGER", spend)
    _invoke(tmp_path, "--split", "holdout", "--check", frozen=_frozen_with_holdout(tmp_path))
    assert not spend.exists()


def _frozen_with_holdout(tmp_path: Path) -> Path:
    """The fixture corpus is all `dev`; these tests need a holdout ticker to exist."""
    body = json.loads(_frozen(tmp_path).read_text(encoding="utf-8"))
    body["corpus"]["accepted"][0]["split"] = "holdout"
    path = tmp_path / "frozen_holdout.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_holdout_run_records_the_spend_before_printing_a_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering is the point: a crash between computing and displaying must leave
    the holdout spent, not apparently intact."""
    spend = tmp_path / "spend.jsonl"
    monkeypatch.setattr("mapf.cli.commands.evaluate.HOLDOUT_LEDGER", spend)
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path, "--split", "holdout", frozen=_frozen_with_holdout(tmp_path))
    assert result.exit_code == 0
    entry = json.loads(spend.read_text(encoding="utf-8").strip())
    assert entry["band"] == "clean"
    assert entry["items"] == 2
    assert entry["calibration"] is None

    # And the record is what makes a second run impossible.
    again = _invoke(tmp_path, "--split", "holdout", frozen=_frozen_with_holdout(tmp_path))
    assert again.exit_code == 9


# Reconciling two digests against one record (ADR 0029's per-item truncation scoping)


def _record(*, ratio: float = 3.0, prompt: str = "p1") -> dict[str, object]:
    return {
        "models": {"analyst": "g"},
        "prompts": {"analyst": prompt},
        "truncation": {"chars_per_token_estimate": ratio},
        "horizon_days": 21,
    }


def _bases(
    monkeypatch: pytest.MonkeyPatch,
    labels: list[str],
    table: dict[str, tuple[dict[str, object], bool]],
) -> FreezeBases:
    monkeypatch.setattr("mapf.cli.commands.evaluate._frozen_by_digest", lambda: table)
    return _freeze_bases(Counter(dict.fromkeys(labels, 1)))


def test_one_record_seen_through_the_scoping_reconciles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The band's real shape: every run shares a record, and the truncated ones hash
    differently only because the rule that applied to them is included."""
    rec = _record()
    whole = str(freeze_digest(rec, truncated=False))[:12]
    cut = str(freeze_digest(rec, truncated=True))[:12]
    bases = _bases(monkeypatch, [whole, cut], {whole: (rec, False), cut: (rec, True)})
    assert bases.reconciled
    assert bases.shared_label == whole
    assert bases.cut_label == cut


def test_two_truncation_bases_still_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure the count was there to catch: truncated items built under two
    different ratios. Both share the non-truncation record, so ONLY the cut digests
    separate them -- which is why `cut` is compared and not merely counted."""
    old, new = _record(ratio=3.5), _record(ratio=3.0)
    a = str(freeze_digest(old, truncated=True))[:12]
    b = str(freeze_digest(new, truncated=True))[:12]
    bases = _bases(monkeypatch, [a, b], {a: (old, True), b: (new, True)})
    assert not bases.reconciled
    assert len(bases.cut) == 2


def test_a_difference_outside_truncation_still_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed prompt survives the scoping: it is in the shared half."""
    one, two = _record(prompt="p1"), _record(prompt="p2")
    a = str(freeze_digest(one, truncated=False))[:12]
    b = str(freeze_digest(two, truncated=False))[:12]
    bases = _bases(monkeypatch, [a, b], {a: (one, False), b: (two, False)})
    assert not bases.reconciled
    assert len(bases.shared) == 2


def test_a_digest_git_cannot_resolve_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unresolvable is not reconcilable. A digest whose record cannot be recovered
    might be anything, and the safe reading of "might be anything" is a refusal."""
    rec = _record()
    whole = str(freeze_digest(rec, truncated=False))[:12]
    bases = _bases(monkeypatch, [whole, "deadbeefcafe"], {whole: (rec, False)})
    assert not bases.reconciled
    assert bases.unresolved == 1


def test_the_reconciled_band_says_so_rather_than_refusing(tmp_path: Path) -> None:
    """End to end: two digests that resolve to one record report a basis, not a
    problem. Guarded by the unit tests above so this cannot become "two is fine"."""
    rec = _record()
    whole, cut = str(freeze_digest(rec, truncated=False)), str(freeze_digest(rec, truncated=True))
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40, freeze="2.3.0", freeze_digest=whole)
    _manifest(tmp_path, ids[1], "a" * 40, freeze="2.6.0", freeze_digest=cut)

    with mock.patch(
        "mapf.cli.commands.evaluate._frozen_by_digest",
        return_value={whole[:12]: (rec, False), cut[:12]: (rec, True)},
    ):
        result = _invoke(tmp_path, "--split", "dev", "--check")
    assert "one basis, seen through the per-item scoping" in result.output
    assert "more than one frozen record" not in result.output


def test_a_repo_without_the_frozen_record_resolves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside a git checkout the table is empty, so every digest is unresolved and
    the band refuses. Failing to read history must not read as agreement."""

    class _Failed:
        returncode = 128
        stdout = ""

    monkeypatch.setattr("mapf.cli.commands.evaluate.subprocess.run", lambda *a, **k: _Failed())
    assert _frozen_by_digest() == {}


# Direction, dispersion and the named strata


def test_a_drifting_baseline_is_reported_per_baseline(tmp_path: Path) -> None:
    """The coin-flip collapse is conditional. A baseline that makes a directional
    claim must be compared against on its own, or the collapse would hide it."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    real = score_band

    def _drifting(*args: object, **kwargs: object) -> BandScores:
        scored = real(*args, **kwargs)  # type: ignore[arg-type]
        return BandScores(
            items=tuple(
                replace(i, baseline_brier=dict.fromkeys(i.baseline_brier, 0.16))
                for i in scored.items
            ),
            unscored=scored.unscored,
        )

    with mock.patch("mapf.cli.commands.evaluate.score_band", _drifting):
        result = _invoke(tmp_path, "--split", "dev")
    assert "a coin flip" not in result.output
    assert "zero-drift by construction" not in result.output


def test_an_undefined_calibration_ratio_is_named_not_crashed(tmp_path: Path) -> None:
    """Every outcome exactly zero has no ratio. The run must say so and carry on to
    the strata rather than dying between the comparisons and the rest of the report."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0")

    real = score_band

    def _flat(*args: object, **kwargs: object) -> BandScores:
        scored = real(*args, **kwargs)  # type: ignore[arg-type]
        return BandScores(
            items=tuple(replace(i, realised_return=0.0) for i in scored.items),
            unscored=scored.unscored,
        )

    with mock.patch("mapf.cli.commands.evaluate.score_band", _flat):
        result = _invoke(tmp_path, "--split", "dev")
    assert result.exit_code == 0
    assert "calibration: not computed" in result.output
    assert "named strata" in result.output


def test_a_recovered_item_lands_in_the_stratum_its_failure_names(tmp_path: Path) -> None:
    """`resolved()` keeps only the final entry, so an item that failed and then
    succeeded looks untouched there. The stratum has to read the raw history."""
    ids = [uuid4(), uuid4()]
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(
            ticker="AAPL",
            band="clean",
            filing_date=CLEAN[0],
            status="failed",
            reason="budget_exhausted",
        )
    )
    for i, day in enumerate(CLEAN):
        ledger.append(
            LedgerEntry(
                ticker="AAPL", band="clean", filing_date=day, status="complete", run_id=ids[i]
            )
        )
        _write_forecast(tmp_path, ids[i], day)
        _manifest(tmp_path, ids[i], "a" * 40, freeze="2.3.0")

    result = _invoke(tmp_path, "--split", "dev")
    assert result.exit_code == 0
    assert "recovered from a budget exhaustion: 1 of 2" in result.output
    assert "recovered from the DNS outage: no scored item" in result.output


def test_a_stratum_too_small_for_an_interval_says_so(tmp_path: Path) -> None:
    """A bootstrap interval over one occupied block is a number with no content;
    printing it anyway would be the most confident thing on the page."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0", dirty=True)
    result = _invoke(tmp_path, "--split", "dev")
    assert "produced from an uncommitted tree: 2 of 2" in result.output
    assert "no interval — 2 items" in result.output
    assert "without: empty" in result.output


def test_a_stratum_large_enough_gets_the_full_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the threshold. Driven by lowering the minimum rather than
    by a 40-item fixture: the branch under test is the threshold, not the corpus."""
    monkeypatch.setattr("mapf.cli.commands.evaluate._INTERVAL_MINIMUM", 2)
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, freeze="2.3.0", dirty=True)
    result = _invoke(tmp_path, "--split", "dev")
    assert "produced from an uncommitted tree: 2 of 2" in result.output
    assert "no interval" not in result.output
    assert "M.A.P. vs random_walk" in result.output
