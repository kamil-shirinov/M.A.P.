"""The three adapters between stored artifacts and the scoring pass (ADR 0023).

Each is a place where something correct-looking would produce a wrong number:

1. **Loading** — `runs/` is not a corpus, so the scored set comes from the ledger.
2. **Vintage** — a return is a ratio, and a ratio needs one measurement basis.
3. **Earnings** — "the ticker's earnings dates" reads as a static property of the
   company, which is how look-ahead re-enters through the benchmark.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from mapf.corpus.forecasts import (
    ForecastLoadError,
    ForecastMismatchError,
    UnknownItemError,
    load_band,
    unreferenced_runs,
)
from mapf.corpus.ledger import Ledger, LedgerEntry
from mapf.corpus.selection import Corpus
from mapf.eval.scorer import LookAheadError, VintageError, score_band, score_item
from tests.unit.test_scorer import (
    HORIZON,
    _forecast,
    _prices_for,
    _realistic_window,
    _window,
)

CLEAN = date(2026, 2, 1)


# ---------------------------------------------------------------------------
# 1. Loading comes from the ledger
# ---------------------------------------------------------------------------
def _corpus() -> Corpus:
    return Corpus.model_validate(
        {
            "criteria": {
                "bands": [
                    {"name": "clean", "first_open": "2026-01-01", "last_open": "2026-08-06"},
                    {"name": "ambiguous", "first_open": "2025-01-01", "last_open": "2025-12-31"},
                ],
                "seed": 1,
                "target_tickers": 1,
            },
            "ordering_sha256": "0" * 64,
            "accepted": [
                {
                    "ticker": "AAPL",
                    "cik": 320193,
                    "split": "dev",
                    "filings": [
                        {
                            "band": "clean",
                            "dates": [CLEAN.isoformat()],
                            "accessions": ["0000000001-26-000001"],
                        },
                        {
                            "band": "ambiguous",
                            "dates": ["2025-02-03"],
                            "accessions": ["0000000001-26-000002"],
                        },
                    ],
                }
            ],
            "rejected": [],
        }
    )


def _store(tmp_path: Path, run_id: object, *, ticker: str = "AAPL", as_of: date | None = None):  # type: ignore[no-untyped-def]
    directory = tmp_path / "runs" / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    forecast = _forecast(as_of or CLEAN + timedelta(days=1), 100.0, ticker=ticker)
    (directory / "forecast.json").write_text(forecast.model_dump_json(), encoding="utf-8")


def _ledger(tmp_path: Path, **overrides: object) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    fields: dict[str, object] = {
        "ticker": "AAPL",
        "band": "clean",
        "filing_date": CLEAN,
        "status": "complete",
        "run_id": uuid4(),
    }
    fields.update(overrides)
    ledger.append(LedgerEntry(**fields))  # type: ignore[arg-type]
    return ledger


def test_a_completed_item_loads_from_its_ledger_entry(tmp_path: Path) -> None:
    run_id = uuid4()
    ledger = _ledger(tmp_path, run_id=run_id)
    _store(tmp_path, run_id)
    loaded = load_band(ledger, _corpus(), tmp_path / "runs", "clean")
    assert [item.forecast.ticker for item in loaded] == ["AAPL"]
    assert [item.entry.filing_date for item in loaded] == [CLEAN]


def test_a_pre_corpus_capture_on_disk_is_never_loaded(tmp_path: Path) -> None:
    """`first-capture` and the loose UUIDs of the first live forecasts sit in the
    same directory under a different prompt, horizon and schema. The ledger does not
    name them, so no amount of them being parseable matters."""
    run_id = uuid4()
    ledger = _ledger(tmp_path, run_id=run_id)
    _store(tmp_path, run_id)
    _store(tmp_path, "first-capture-v2")

    loaded = load_band(ledger, _corpus(), tmp_path / "runs", "clean")
    assert len(loaded) == 1
    assert list(unreferenced_runs(ledger, tmp_path / "runs")) == ["first-capture-v2"]


def test_an_item_absent_from_the_frozen_corpus_refuses(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, ticker="MSFT")
    with pytest.raises(UnknownItemError, match="absent from the frozen corpus"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_the_refusal_names_the_offending_items(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, filing_date=date(2026, 7, 7))
    with pytest.raises(UnknownItemError, match="2026-07-07"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_a_completed_item_with_no_run_id_refuses(tmp_path: Path) -> None:
    """Skipping it would drop from the sample exactly the items whose bookkeeping
    is broken, which is a selection effect rather than a smaller sample."""
    ledger = _ledger(tmp_path, run_id=None)
    with pytest.raises(ForecastLoadError, match="record no run id"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_a_terminal_failure_is_absent_rather_than_unscoreable(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, status="failed", reason="missing_exhibit", run_id=None)
    assert load_band(ledger, _corpus(), tmp_path / "runs", "clean") == ()


def test_a_forecast_for_another_ticker_refuses(tmp_path: Path) -> None:
    run_id = uuid4()
    ledger = _ledger(tmp_path, run_id=run_id)
    _store(tmp_path, run_id, ticker="MSFT")
    with pytest.raises(ForecastMismatchError, match="item-to-run mapping is broken"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_a_forecast_dated_before_its_filing_refuses(tmp_path: Path) -> None:
    """The forecast must open AFTER the filing it reads. A forecast dated before it
    is either the wrong run or a look-ahead, and both are unscoreable."""
    run_id = uuid4()
    ledger = _ledger(tmp_path, run_id=run_id)
    _store(tmp_path, run_id, as_of=CLEAN - timedelta(days=1))
    with pytest.raises(ForecastMismatchError, match="not within"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_a_forecast_far_after_its_filing_refuses(tmp_path: Path) -> None:
    run_id = uuid4()
    ledger = _ledger(tmp_path, run_id=run_id)
    _store(tmp_path, run_id, as_of=CLEAN + timedelta(days=60))
    with pytest.raises(ForecastMismatchError, match="not within"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_an_older_schema_fails_to_parse_rather_than_being_coerced(tmp_path: Path) -> None:
    run_id = uuid4()
    ledger = _ledger(tmp_path, run_id=run_id)
    directory = tmp_path / "runs" / str(run_id)
    directory.mkdir(parents=True)
    (directory / "forecast.json").write_text('{"schema_version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ForecastLoadError, match="not a readable v2 forecast"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_a_missing_forecast_file_refuses(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ForecastLoadError, match="not a readable v2 forecast"):
        load_band(ledger, _corpus(), tmp_path / "runs", "clean")


def test_unreferenced_runs_is_empty_when_the_directory_is_absent(tmp_path: Path) -> None:
    assert list(unreferenced_runs(_ledger(tmp_path), tmp_path / "nowhere")) == []


# ---------------------------------------------------------------------------
# 2. One vintage across both endpoints, and across the band
# ---------------------------------------------------------------------------
def test_a_window_on_another_basis_is_refused() -> None:
    """Both endpoints of a return must share a measurement basis. Within one window
    that holds by construction — which is exactly why it is asserted."""
    window = _realistic_window()
    other = window.model_copy(update={"adjustment": "raw"})
    as_of = window.bars[-HORIZON - 1].date
    with pytest.raises(VintageError, match="canonical"):
        score_item(
            _forecast(as_of, window.bars[-HORIZON - 1].close), other, band="clean", paths=200
        )


def test_a_band_priced_from_two_providers_is_refused() -> None:
    """The reachable half. `ProviderChain` fails over per call, so one ticker can be
    served by yfinance and the next by stooq, and the price cache is keyed by
    `fetched_on`, so a pass spanning midnight mixes two vintages. Both produce
    well-formed windows that mean different things."""
    a = _realistic_window(ticker="AAA")
    b = _realistic_window(ticker="BBB", seed=3).model_copy(update={"provider": "stooq"})
    forecasts = [
        (_forecast(w.bars[-HORIZON - 1].date, w.bars[-HORIZON - 1].close, ticker=w.ticker), "clean")
        for w in (a, b)
    ]
    with pytest.raises(VintageError, match="different series"):
        score_band(forecasts, prices=_prices_for({"AAA": a, "BBB": b}), paths=200)


def test_one_provider_across_the_band_is_accepted() -> None:
    a = _realistic_window(ticker="AAA")
    b = _realistic_window(ticker="BBB", seed=3)
    forecasts = [
        (_forecast(w.bars[-HORIZON - 1].date, w.bars[-HORIZON - 1].close, ticker=w.ticker), "clean")
        for w in (a, b)
    ]
    scores = score_band(forecasts, prices=_prices_for({"AAA": a, "BBB": b}), paths=200)
    assert scores.n == 2


def test_the_vintage_travels_with_every_scored_item() -> None:
    """So the refusal above can be made at all, and so a report can name the series
    it scored against rather than leaving the reader to assume one."""
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    item = score_item(
        _forecast(as_of, window.bars[-HORIZON - 1].close), window, band="clean", paths=200
    )
    assert (item.provider, item.adjustment) == ("fake", "split_adjusted")


# ---------------------------------------------------------------------------
# 3. Earnings are point-in-time, not a property of the ticker
# ---------------------------------------------------------------------------
def test_an_earnings_date_inside_the_window_is_refused() -> None:
    """Raised rather than filtered. The multiplier only ever sees dates that land in
    an already-truncated history, so a future one is dropped silently — which leaves
    a broken adapter looking correct forever."""
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    with pytest.raises(LookAheadError, match="at or after the forecast opens"):
        score_item(
            _forecast(as_of, window.bars[-HORIZON - 1].close),
            window,
            band="clean",
            past_earnings=[as_of],
            paths=200,
        )


def test_an_earnings_date_after_the_window_is_refused() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    with pytest.raises(LookAheadError):
        score_item(
            _forecast(as_of, window.bars[-HORIZON - 1].close),
            window,
            band="clean",
            past_earnings=[window.bars[-1].date],
            paths=200,
        )


def test_future_earnings_cannot_change_the_score() -> None:
    """The exact statement of no look-ahead, in the form that caught the last one:
    identical earnings history through the window, a different one afterwards, and
    every score bit-identical.

    Asserting that the multiplier merely 'looks reasonable' would pass under both
    the bug and the correct behaviour — the CRPS mistake of ADR 0023, one layer up.
    """
    window = _realistic_window(n=420)
    index = 380
    as_of = window.bars[index].date
    spot = window.bars[index].close
    forecast = _forecast(as_of, spot)

    shared = [window.bars[i].date for i in range(60, index, 63)]
    later = [window.bars[i].date for i in range(index + 1, 420, 7)]
    assert later, "the fixture must actually have a future to differ in"

    quiet = score_item(forecast, window, band="clean", past_earnings=shared, paths=2000)
    with pytest.raises(LookAheadError):
        score_item(forecast, window, band="clean", past_earnings=shared + later, paths=2000)

    # And when the adapter cuts correctly, the future is invisible rather than
    # merely rejected: the same prior dates score identically however many future
    # ones the source held.
    cut = [day for day in shared + later if day < as_of]
    again = score_item(forecast, window, band="clean", past_earnings=cut, paths=2000)
    assert again.baseline_crps == pytest.approx(quiet.baseline_crps)
    assert again.map_crps == pytest.approx(quiet.map_crps)
    assert again.realised_return == pytest.approx(quiet.realised_return)


def test_the_multiplier_actually_moves_when_earnings_differ() -> None:
    """A control for the test above. If the earnings dates could never change the
    score, the look-ahead assertion would hold vacuously — the failure of #8."""
    rng = np.random.default_rng(11)
    closes = list(100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 420))))
    for i in range(70, 380, 63):
        for j in range(i, min(i + HORIZON, len(closes))):
            closes[j] *= 1.06
    window = _window(closes)
    index = 380
    as_of = window.bars[index].date
    forecast = _forecast(as_of, window.bars[index].close)
    spiky = [window.bars[i].date for i in range(70, 380, 63)]

    with_spikes = score_item(forecast, window, band="clean", past_earnings=spiky, paths=2000)
    without = score_item(forecast, window, band="clean", past_earnings=[], paths=2000)
    assert (
        with_spikes.baseline_crps["earnings_scaled_random_walk"]
        != without.baseline_crps["earnings_scaled_random_walk"]
    )


def test_a_history_too_short_to_fit_records_no_multiplier() -> None:
    """`None` rather than 1.0: "could not be fitted" and "fitted, and declined to
    widen" are different facts about the benchmark, and the report distinguishes
    them."""
    window = _realistic_window(n=60)
    as_of = window.bars[-HORIZON - 1].date
    item = score_item(
        _forecast(as_of, window.bars[-HORIZON - 1].close), window, band="clean", paths=200
    )
    assert item.earnings_multiplier is None
    assert "earnings_scaled_random_walk" not in item.baseline_crps


def test_a_fitted_baseline_that_declines_to_widen_records_one_not_none() -> None:
    """The distinction the report rests on. "Could not be fitted" and "fitted, and
    found nothing to widen for" are different facts about the benchmark, and only
    the second one means M.A.P. was compared against the random walk twice."""
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    item = score_item(
        _forecast(as_of, window.bars[-HORIZON - 1].close),
        window,
        band="clean",
        past_earnings=[],
        paths=200,
    )
    assert item.earnings_multiplier == 1.0
    assert "earnings_scaled_random_walk" in item.baseline_crps


def test_a_fitted_multiplier_is_recorded_on_the_item() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    quarters = [window.bars[i].date for i in range(60, 340, 63)]
    item = score_item(
        _forecast(as_of, window.bars[-HORIZON - 1].close),
        window,
        band="clean",
        past_earnings=quarters,
        paths=200,
    )
    assert item.earnings_multiplier is not None
    assert item.earnings_multiplier > 0.0
