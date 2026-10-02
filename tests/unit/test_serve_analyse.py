"""The analysis path — ADR 0036 §1 and §2.

Driven entirely through `Wiring`'s callables, so there is no model, no network
and no run directory. What is being tested is the ORDER of the stream and the
marking that travels with the result, which is the part a page depends on.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from mapf.serve.analyse import (
    AnalysisError,
    Exhibit,
    Wiring,
    company_screens,
    decide,
    latest_exhibit,
    result_line,
    run_analysis,
)

FILED = date(2026, 9, 21)
ANCHOR = date(2026, 9, 22)
SESSIONS = [date(2026, 9, 18), FILED, ANCHOR, date(2026, 9, 23)]


class _Scenario:
    def __init__(self, weight: float, ret: float, vol: float) -> None:
        self.probability_weight = weight
        self.price_return = ret
        self.annualised_vol = vol


class _Scenarios:
    bullish = _Scenario(0.25, 0.06, 0.34)
    base_case = _Scenario(0.50, 0.01, 0.28)
    bearish = _Scenario(0.25, -0.05, 0.41)


class _Bar:
    def __init__(self, day: date, close: float = 200.0) -> None:
        self.date = day
        self.close = close


class _Window:
    bars = [_Bar(day) for day in SESSIONS]


class _Forecast:
    as_of = datetime.combine(ANCHOR, datetime.min.time(), tzinfo=UTC)
    spot_price = 201.5
    scenarios = _Scenarios()


class _Correction:
    a = -0.0757
    b = 1.3305
    form = "z -> (z - a) / b"


def _exhibit(**over: Any) -> Exhibit:
    base: dict[str, Any] = {
        "accession": "0000320193-26-000077",
        "filed": FILED,
        "document": object(),
        "truncated": None,
    }
    return Exhibit(**{**base, **over})


def _wiring(**over: Any) -> Wiring:
    def execute_run(
        _t: str, _h: int, _e: Exhibit
    ) -> Generator[dict[str, object], None, tuple[str, object, object]]:
        yield {"event": "progress", "stage": "intake", "detail": ""}
        yield {"event": "progress", "stage": "analyst", "detail": ""}
        yield {"event": "progress", "stage": "structuralist", "detail": ""}
        return "run-1", _Forecast(), _Window()

    base: dict[str, Any] = {
        "fetch_exhibit": lambda _t: _exhibit(),
        "execute_run": execute_run,
        "liquidity": lambda _t, _s, _e: 9.0e8,
        "symbol": lambda _t: 320193,
        "correction": _Correction(),
    }
    return Wiring(**{**base, **over})


def _stream(**over: Any) -> list[dict[str, object]]:
    return list(run_analysis("AAPL", 5, wiring=_wiring(**over), typical_seconds=397))


def _listed(line: dict[str, object], key: str) -> list[Any]:
    value = line[key]
    assert isinstance(value, list)
    return value


def _capture(captured: list[Any], server: Any) -> Any:
    def build(config: Any) -> Any:
        captured.append(config)
        return server

    return build


# --- the stream ----------------------------------------------------------------


def test_the_filing_is_announced_before_the_long_wait() -> None:
    """A reader waiting five minutes should already know WHICH document is being
    read. Announcing it afterwards would mean the whole wait is unexplained."""
    events = _stream()
    kinds = [e["event"] for e in events]
    assert kinds.index("filing") < kinds.index("progress")
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "result"


def test_the_first_line_carries_a_measured_expectation() -> None:
    """Not a spinner, and not a single number either.

    The median alone reads as a promise; the middle eighty percent of the 701
    recorded runs spans six to twelve minutes, so the range travels with it."""
    started = list(
        run_analysis(
            "AAPL", 5, wiring=_wiring(), typical_seconds=457, usual_range_seconds=(331, 692)
        )
    )[0]
    assert started["typical_seconds"] == 457
    assert started["usual_range_seconds"] == [331, 692]
    assert started["stages"] == ["intake", "analyst", "structuralist"]


def test_an_absent_range_is_null_rather_than_an_invented_one() -> None:
    assert _stream()[0]["usual_range_seconds"] is None


def test_the_stated_time_comes_from_recorded_elapsed_not_trace_spans() -> None:
    """A trace's first line is written when the FIRST AGENT FINISHES, so the span
    from first line to last is a lower bound on the run — 495 seconds against 601
    of wall clock on the one live run so far. The ledger's `elapsed_s` is the
    runner's own clock and is what these constants are measured from."""
    from mapf.cli.commands import serve as command

    assert command.TYPICAL_RUN_SECONDS == 457
    assert (command.RUN_SECONDS_P10, command.RUN_SECONDS_P90) == (331, 692)
    assert command.RUN_SECONDS_P10 < command.TYPICAL_RUN_SECONDS < command.RUN_SECONDS_P90


def test_every_agent_stage_reaches_the_stream() -> None:
    stages = [e["stage"] for e in _stream() if e["event"] == "progress"]
    assert stages == ["intake", "analyst", "structuralist"]


# --- the marking travels with the numbers --------------------------------------


def test_a_qualifying_run_is_marked_settled_and_corrected() -> None:
    result = _stream()[-1]
    assert result["corrected"] is True
    assert result["marking"] == "settled"
    assert result["reasons"] == []
    assert result["correction"] == {"a": -0.0757, "b": 1.3305, "form": "z -> (z - a) / b"}


def test_an_illiquid_company_is_amber_with_the_reason_shown() -> None:
    """The liquidity floor alone is $50M median dollar volume, so most live runs
    land here. That is the intended outcome, not a defect."""
    result = _stream(liquidity=lambda _t, _s, _e: 1.0e6)[-1]
    assert result["corrected"] is False
    assert result["marking"] == "uncalibrated"
    assert any("illiquid" in str(r) for r in _listed(result, "reasons"))


def test_an_unknown_liquidity_refuses_rather_than_passing() -> None:
    result = _stream(liquidity=lambda _t, _s, _e: None)[-1]
    assert result["corrected"] is False
    assert any("no_price_history" in str(r) for r in _listed(result, "reasons"))


def test_a_ticker_with_no_cik_is_amber() -> None:
    result = _stream(symbol=lambda _t: None)[-1]
    assert result["corrected"] is False
    assert any("no_cik" in str(r) for r in _listed(result, "reasons"))


def test_a_stale_filing_is_amber_because_the_anchor_is_too_far_out() -> None:
    """The panel anchors within one trading day of the filing. A filer whose most
    recent Item 2.02 is three months old cannot be aligned that way, and the fan is
    marked rather than quietly corrected."""
    old = _exhibit(filed=date(2026, 9, 18))
    result = list(
        run_analysis("AAPL", 5, wiring=_wiring(fetch_exhibit=lambda _t: old), typical_seconds=397)
    )[-1]
    assert result["corrected"] is False
    assert any("trading days after one" in str(r) for r in _listed(result, "reasons"))


def test_the_longer_periods_are_offered_and_always_amber() -> None:
    """Ten and twenty-one sessions are selectable; nothing was fitted at either."""
    for horizon in (10, 21):
        result = list(run_analysis("AAPL", horizon, wiring=_wiring(), typical_seconds=397))[-1]
        assert result["corrected"] is False
        assert any(f"and this is {horizon}" in str(r) for r in _listed(result, "reasons"))


def test_the_marking_is_in_the_same_object_as_the_numbers() -> None:
    """A result that could reach a page without its marking is an unmarked fan.
    Keeping them in one object is what makes that impossible rather than unlikely."""
    result = _stream()[-1]
    for key in ("scenarios", "spot", "marking", "corrected", "reasons"):
        assert key in result


def test_the_relation_is_decided_by_the_freeze_never_asserted() -> None:
    """ADR 0036 §2. A corpus company's latest filing may well BE a frozen exhibit —
    for AAPL today it is — so the live path must ask rather than assume."""
    from mapf.serve.analyse import Freeze

    freeze = Freeze(document_ids=frozenset({"sha256:abc"}), accessions=frozenset({"0000-1"}))
    assert freeze.relate(document_id="sha256:abc", accession="other") == "repeat_of_exhibit"
    assert freeze.relate(document_id="sha256:zzz", accession="0000-1") == "repeat_of_exhibit"
    assert freeze.relate(document_id="sha256:zzz", accession="other") == "outside_corpus"
    # Never `ledger_item`: that names a run the ledger recorded, and this one is
    # being made now.
    assert "ledger_item" not in {
        freeze.relate(document_id=d, accession=a) for d, a in (("sha256:abc", "0000-1"), ("x", "y"))
    }


def test_an_unreadable_freeze_leaves_the_relation_unchecked(tmp_path: Any) -> None:
    """Unchecked is the journal's own word for "nobody could tell". It must not
    stop a run, and it must not become `outside_corpus` by default — that would be
    a claim made from a missing file."""
    from mapf.serve.analyse import Freeze

    assert (
        Freeze.load(tmp_path / "absent.json").relate(document_id="x", accession="y") == "unchecked"
    )
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert Freeze.load(broken).relate(document_id="x", accession="y") == "unchecked"


def test_the_real_freeze_relates_aapls_latest_filing_as_a_repeat() -> None:
    """The case that prompted this: the company page claimed a live run always
    reads something newer than the table above it, and for AAPL it does not."""
    from pathlib import Path

    from mapf.serve.analyse import Freeze

    freeze = Freeze.load(Path("corpus/frozen.json"))
    assert freeze.relate(document_id=None, accession="0000320193-26-000018") == "repeat_of_exhibit"
    assert freeze.relate(document_id=None, accession="9999999999-99-999999") == "outside_corpus"


def test_the_result_carries_the_relation() -> None:
    assert _stream()[-1]["corpus_relation"] == "unchecked"


# --- the band ------------------------------------------------------------------


def test_the_band_is_the_forecasts_width_in_prices() -> None:
    """Without it a corrected fan and a raw one are the same three lines, and the
    amber box warns about something invisible."""
    from mapf.serve.analyse import BAND_LEVELS, band_prices

    band = band_prices(100.0, [-0.10, -0.04, 0.04, 0.10], mean=0.0, sigma=0.06)
    assert [b["level"] for b in band] == list(BAND_LEVELS)
    prices = [b["price"] for b in band]
    assert prices == sorted(prices), "quantiles arrive in order and stay in order"
    assert prices[0] < 100.0 < prices[-1]


def test_the_correction_widens_the_band_and_that_is_the_point() -> None:
    """`b = 1.3305` is greater than one, so a corrected band is genuinely wider.
    A picture that did not show that would make the marking beside it decorative."""
    from mapf.serve.analyse import band_prices

    quantiles = [-0.10, -0.04, 0.04, 0.10]
    raw = band_prices(100.0, quantiles, mean=0.0, sigma=0.06)
    corrected = band_prices(100.0, quantiles, mean=0.0, sigma=0.06, correction=_Correction())
    raw_width = raw[-1]["price"] - raw[0]["price"]
    corrected_width = corrected[-1]["price"] - corrected[0]["price"]
    assert corrected_width > raw_width * 1.2


def test_a_band_is_not_widened_when_the_correction_does_not_apply() -> None:
    """The gate decides, and the picture follows it. A band widened by a correction
    the words refuse would be the chart contradicting the box above it."""
    events = list(run_analysis("AAPL", 21, wiring=_wiring(), typical_seconds=457))
    result = events[-1]
    assert result["corrected"] is False
    # No simulator wired in this stub, so no band — and never a fabricated one.
    assert result["band"] == []


# --- the pieces ----------------------------------------------------------------


def test_the_result_line_reports_all_three_scenarios_with_their_weights() -> None:
    line = result_line(
        run_id="r",
        ticker="AAPL",
        horizon=5,
        exhibit=_exhibit(),
        forecast=_Forecast(),
        applies=decide(
            horizon_days=5,
            filed=FILED,
            anchor=ANCHOR,
            sessions=SESSIONS,
            failed_screens=(),
            unevaluated=(),
        ),
        correction=_Correction(),
    )
    names = [s["name"] for s in _listed(line, "scenarios")]
    assert names == ["bullish", "base_case", "bearish"]
    assert sum(s["weight"] for s in _listed(line, "scenarios")) == pytest.approx(1.0)


def test_a_failed_screen_and_an_unevaluated_one_are_different_sentences() -> None:
    """ "We checked and it is too thin" is not "we could not check"."""
    failed, unevaluated = company_screens(
        "AAPL", cik=1, median_dollar_volume=1.0e6, floor=5.0e7, has_exhibit=True
    )
    assert any("illiquid" in f for f in failed)
    assert unevaluated == ()

    failed, _ = company_screens(
        "AAPL", cik=1, median_dollar_volume=None, floor=5.0e7, has_exhibit=True
    )
    assert failed == ("no_price_history",)


def test_a_missing_exhibit_is_a_failed_screen() -> None:
    failed, _ = company_screens(
        "AAPL", cik=1, median_dollar_volume=9.0e8, floor=5.0e7, has_exhibit=False
    )
    assert failed == ("no_exhibit",)


# --- the EDGAR half ------------------------------------------------------------


class _Filing:
    accession = "0000320193-26-000077"
    filed = FILED


class _Doc:
    text = "Southern Copper reported ..." * 200

    def model_copy(self, *, update: dict[str, Any]) -> Any:
        copy = _Doc()
        copy.text = update["text"]
        return copy


def _builders(found: list[Any]) -> tuple[Any, Any]:
    class Filings:
        def earnings_filings(self, _t: str, _s: date, _e: date) -> list[Any]:
            return found

    class Exhibits:
        def fetch(self, _f: Any) -> Any:
            return _Doc()

    return (lambda _s, _c: Filings()), (lambda _s, _c: Exhibits())


@pytest.fixture
def settings() -> Any:
    """The real default settings: `latest_exhibit` reads the intake budget off them,
    and the budget is policy an EDGAR run must share with a corpus run."""
    from mapf.settings import load

    return load(None)


def test_no_filing_refuses_and_says_it_will_not_fall_back(settings: Any) -> None:
    """The news path answers a different question. A silent substitution would
    produce a forecast from unrelated documents under a request that asked for a
    filing."""
    filings, exhibits = _builders([])
    with pytest.raises(AnalysisError, match="does not fall back"):
        latest_exhibit(
            settings, object(), "AAPL", days=120, build_filings=filings, build_exhibits=exhibits
        )


def test_the_most_recent_filing_is_the_one_read(settings: Any) -> None:
    older = _Filing()
    older.accession = "older"
    filings, exhibits = _builders([older, _Filing()])
    exhibit = latest_exhibit(
        settings, object(), "AAPL", days=120, build_filings=filings, build_exhibits=exhibits
    )
    assert exhibit.accession == "0000320193-26-000077"


# --- the CLI command's wiring --------------------------------------------------
#
# `map serve` builds the real adapters and hands one callable to the server. What
# is worth testing is that it wires them to each other correctly — so the builders
# are replaced and the captured callable is driven directly. No socket is opened.


def test_map_serve_wires_a_working_analysis(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")
    runs = tmp_path / "runs"

    class _Result:
        forecast = _Forecast()
        window = _Window()

    class _Wiring:
        agents = object()
        market = object()
        dividends = object()
        trace = object()
        runs_dir = runs
        allow_nondeterministic = False

    given: list[dict[str, Any]] = []

    def _execute(_request: Any, **_kw: Any) -> Any:
        given.append(_kw)
        # The run writes its trace as it goes; the watcher reads progress off it.
        directory = runs / str(_request.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "trace.jsonl").write_text(
            "\n".join(
                json.dumps({"stage": stage, "at": "2026-09-28T00:00:00Z", "cache_hit": False})
                for stage in ("intake", "analyst", "structuralist")
            )
            + "\n",
            encoding="utf-8",
        )
        return _Result()

    filings, exhibits = _builders([_Filing()])
    captured: list[Any] = []

    class _Stub:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def list_models(self) -> list[str]:
            return ["llama-3.2-3b"]

        def median_dollar_volume(self, _t: str, _s: date, _e: date) -> float:
            return 9.0e8

        def get_ohlcv(self, *_: Any, **__: Any) -> Any:
            return _Window()

        def get(self, _t: str) -> Any:
            return type("S", (), {"cik": 320193})()

    monkeypatch.setattr(command, "build_filings", filings)
    monkeypatch.setattr(command, "build_exhibits", exhibits)
    monkeypatch.setattr(command, "build_http_client", lambda _s: _Stub())
    monkeypatch.setattr(command, "build_llm_provider", lambda _s, fixtures=None: _Stub())
    monkeypatch.setattr(command, "build_market_data", lambda _s: _Stub())
    monkeypatch.setattr(command, "build_symbol_index", lambda _s: _Stub())
    monkeypatch.setattr(command, "build_run", lambda *_a, **_k: _Wiring())
    monkeypatch.setattr(command, "execute", _execute)
    monkeypatch.setattr("mapf.cli.commands.serve.ModelRegistry.resolve_all", lambda _self, _m: {})
    monkeypatch.setattr(command, "MarketLiquidity", lambda _m: _Stub())
    monkeypatch.setattr("mapf.cli.commands.serve.webbrowser.open", lambda _u: None)

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    def _build(config: Any) -> Any:
        captured.append(config)
        return _Server()

    monkeypatch.setattr(command, "build", _build)

    result = CliRunner().invoke(app, ["serve", "--ui-dir", str(ui), "--no-open"])
    assert result.exit_code == 0, result.output
    assert "every analysis is a real run" in result.output

    config = captured[0]
    events = list(config.analyse("AAPL", 5))
    assert events[0]["event"] == "started"
    assert [e["event"] for e in events].count("filing") == 1
    assert [e["stage"] for e in events if e["event"] == "progress"] == [
        "intake",
        "analyst",
        "structuralist",
    ]
    final = events[-1]
    assert final["event"] == "result"
    assert final["ticker"] == "AAPL"
    # The filing is recorded in the run itself, so the journal's later listing of it
    # can use the lookup the result below just used.
    assert given[0]["document_accession"] == final["accession"]
    # The real spend record's coefficients, read from disk by the command.
    assert final["correction"]["a"] == pytest.approx(-0.0757)
    assert "marking" in final


def test_map_serve_refuses_without_an_app_directory(tmp_path: Any) -> None:
    from typer.testing import CliRunner

    from mapf.cli.app import app

    result = CliRunner().invoke(app, ["serve", "--ui-dir", str(tmp_path / "absent"), "--no-open"])
    assert result.exit_code != 0
    assert "no app directory" in result.output


def test_a_slow_run_reports_each_stage_exactly_once(tmp_path: Any) -> None:
    """The watcher polls while the run goes, and the caller drains once more after
    it joins. Both must not report the same line: passing the count by value made
    every stage of a slow run appear twice, which a fast-finishing stub could never
    have shown."""
    import json
    import threading

    from mapf.cli.commands.serve import _drain, _trace_watcher

    trace = tmp_path / "trace.jsonl"
    emitted: list[dict[str, object]] = []
    seen = [0]
    stop = threading.Event()
    watcher = threading.Thread(
        target=_trace_watcher, args=(trace, emitted, stop, seen), daemon=True
    )
    watcher.start()

    trace.write_text(
        "\n".join(
            json.dumps({"stage": stage, "cache_hit": False})
            for stage in ("intake", "analyst", "structuralist")
        )
        + "\n",
        encoding="utf-8",
    )
    # Long enough for at least one poll at 0.5s.
    threading.Event().wait(1.2)
    stop.set()
    watcher.join(timeout=5)
    _drain(trace, emitted, seen)

    assert [e["stage"] for e in emitted] == ["intake", "analyst", "structuralist"]


def test_a_cache_hit_is_reported_as_one(tmp_path: Any) -> None:
    import json

    from mapf.cli.commands.serve import _drain

    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({"stage": "intake", "cache_hit": True}) + "\n", encoding="utf-8")
    emitted: list[dict[str, object]] = []
    _drain(trace, emitted, [0])
    assert emitted == [{"event": "progress", "stage": "intake", "detail": "cached"}]


def test_a_half_written_trace_line_is_retried_not_raised(tmp_path: Any) -> None:
    """Decoration must never break a run. A partial line means `nothing new yet`."""
    from mapf.cli.commands.serve import _drain

    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"stage": "int', encoding="utf-8")
    emitted: list[dict[str, object]] = []
    seen = [0]
    _drain(trace, emitted, seen)
    assert emitted == []
    assert seen == [0]

    # And a missing file is simply not there yet.
    _drain(tmp_path / "absent.jsonl", emitted, seen)
    assert emitted == []


def test_a_long_exhibit_is_cut_to_the_intake_budget(settings: Any) -> None:
    """The same budget the corpus path cuts to, so an EDGAR run and a corpus run of
    one exhibit see one document. The id still hashes the bytes EDGAR served
    (ADR 0005) — truncation is recorded beside the hash, never folded into it."""
    huge = _Filing()

    class Filings:
        def earnings_filings(self, _t: str, _s: date, _e: date) -> list[Any]:
            return [huge]

    class Exhibits:
        def fetch(self, _f: Any) -> Any:
            doc = _Doc()
            doc.text = "word " * 400_000
            return doc

    exhibit = latest_exhibit(
        settings,
        object(),
        "AAPL",
        days=120,
        build_filings=lambda _s, _c: Filings(),
        build_exhibits=lambda _s, _c: Exhibits(),
    )
    assert exhibit.truncated is not None
    assert len(exhibit.document.text) < 400_000 * 5


def test_the_calibration_terms_must_be_readable_to_serve(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing at startup rather than at the first request: a server that starts
    and then cannot mark a fan is worse than one that will not start."""
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app

    ui = tmp_path / "ui"
    ui.mkdir()
    monkeypatch.setattr(command, "build", lambda _c: pytest.fail("should not have started"))

    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--ui-dir",
            str(ui),
            "--no-open",
            "--spend-path",
            str(tmp_path / "no-spend-here.jsonl"),
        ],
    )
    assert result.exit_code != 0
    assert "spend record" in result.output


def test_a_failing_run_propagates_rather_than_reporting_an_empty_forecast(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker runs on a thread, so its exception has to be carried back. Losing
    it would leave the stream ending on a result line with nothing in it."""
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")

    class _Wiring:
        agents = object()
        market = object()
        dividends = object()
        trace = object()
        runs_dir = tmp_path / "runs"
        allow_nondeterministic = False

    class _Stub:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def list_models(self) -> list[str]:
            return []

        def median_dollar_volume(self, *_: Any) -> float:
            return 9.0e8

        def get(self, _t: str) -> Any:
            return None

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("the analyst never answered")

    filings, exhibits = _builders([_Filing()])
    captured: list[Any] = []
    monkeypatch.setattr(command, "build_filings", filings)
    monkeypatch.setattr(command, "build_exhibits", exhibits)
    monkeypatch.setattr(command, "build_http_client", lambda _s: _Stub())
    monkeypatch.setattr(command, "build_llm_provider", lambda _s, fixtures=None: _Stub())
    monkeypatch.setattr(command, "build_market_data", lambda _s: _Stub())
    monkeypatch.setattr(command, "build_symbol_index", lambda _s: _Stub())
    monkeypatch.setattr(command, "MarketLiquidity", lambda _m: _Stub())
    monkeypatch.setattr(command, "build_run", lambda *_a, **_k: _Wiring())
    monkeypatch.setattr(command, "execute", _boom)
    monkeypatch.setattr("mapf.cli.commands.serve.ModelRegistry.resolve_all", lambda _self, _m: {})

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr(command, "build", _capture(captured, _Server()))
    CliRunner().invoke(app, ["serve", "--ui-dir", str(ui), "--no-open"])

    with pytest.raises(RuntimeError, match="the analyst never answered"):
        list(captured[0].analyse("AAPL", 5))


def test_a_market_failure_leaves_the_screen_unevaluated_not_passed(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A liquidity lookup that raises must not read as "liquid enough". It becomes
    `None`, and the gate refuses the correction for it."""
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app
    from mapf.core.errors import MarketDataError

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")
    runs = tmp_path / "runs"

    class _Result:
        forecast = _Forecast()
        window = _Window()

    class _Wiring:
        agents = object()
        market = object()
        dividends = object()
        trace = object()
        runs_dir = runs
        allow_nondeterministic = False

    class _Stub:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def list_models(self) -> list[str]:
            return []

        def median_dollar_volume(self, *_: Any) -> float:
            raise MarketDataError("the price cache has nothing for this ticker")

        def get(self, _t: str) -> Any:
            return type("S", (), {"cik": 1})()

    filings, exhibits = _builders([_Filing()])
    captured: list[Any] = []
    for name, value in (
        ("build_filings", filings),
        ("build_exhibits", exhibits),
        ("build_http_client", lambda _s: _Stub()),
        ("build_llm_provider", lambda _s, fixtures=None: _Stub()),
        ("build_market_data", lambda _s: _Stub()),
        ("build_symbol_index", lambda _s: _Stub()),
        ("MarketLiquidity", lambda _m: _Stub()),
        ("build_run", lambda *_a, **_k: _Wiring()),
        ("execute", lambda *_a, **_k: _Result()),
    ):
        monkeypatch.setattr(command, name, value)
    monkeypatch.setattr("mapf.cli.commands.serve.ModelRegistry.resolve_all", lambda _self, _m: {})

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr(command, "build", _capture(captured, _Server()))
    CliRunner().invoke(app, ["serve", "--ui-dir", str(ui), "--no-open"])

    result = list(captured[0].analyse("AAPL", 5))[-1]
    assert result["corrected"] is False
    assert any("no_price_history" in str(r) for r in _listed(result, "reasons"))


def test_the_browser_is_opened_only_when_asked(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app

    ui = tmp_path / "ui"
    ui.mkdir()
    opened: list[str] = []

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr(command, "build", lambda _c: _Server())
    monkeypatch.setattr("mapf.cli.commands.serve.webbrowser.open", opened.append)

    result = CliRunner().invoke(app, ["serve", "--ui-dir", str(ui)])
    assert result.exit_code == 0
    # The door: a run starts from a company's page, and search is the way there.
    assert opened == ["http://127.0.0.1:8765/index.html"]
    assert "ctrl-c to stop" in result.output


def _serve_with(
    monkeypatch: pytest.MonkeyPatch, ui: Any, extra: list[str] | None = None, **over: Any
) -> Any:
    """Start `map serve` with every adapter stubbed and return the server Config."""
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app

    class _Stub:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def list_models(self) -> list[str]:
            return []

        def median_dollar_volume(self, *_: Any) -> float:
            return 9.0e8

        def get(self, _t: str) -> Any:
            return type("S", (), {"cik": 1})()

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    filings, exhibits = _builders([_Filing()])
    captured: list[Any] = []
    defaults: dict[str, Any] = {
        "build_filings": filings,
        "build_exhibits": exhibits,
        "build_http_client": lambda _s: _Stub(),
        "build_llm_provider": lambda _s, fixtures=None: _Stub(),
        "build_market_data": lambda _s: _Stub(),
        "build_symbol_index": lambda _s: _Stub(),
        "MarketLiquidity": lambda _m: _Stub(),
        "build": _capture(captured, _Server()),
    }
    for name, value in {**defaults, **over}.items():
        monkeypatch.setattr(command, name, value)
    monkeypatch.setattr("mapf.cli.commands.serve.ModelRegistry.resolve_all", lambda _self, _m: {})
    CliRunner().invoke(app, ["serve", "--ui-dir", str(ui), "--no-open", *(extra or [])])
    return captured[0] if captured else None


def test_progress_is_streamed_while_the_run_is_still_going(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the stream. A run takes minutes, and the stages have to
    arrive as they happen rather than all at once when it finishes."""
    import json
    import threading

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")
    runs = tmp_path / "runs"

    class _Result:
        forecast = _Forecast()
        window = _Window()

    class _Wiring:
        agents = object()
        market = object()
        dividends = object()
        trace = object()
        runs_dir = runs
        allow_nondeterministic = False

    def _slow(request: Any, **_kw: Any) -> Any:
        directory = runs / str(request.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        trace = directory / "trace.jsonl"
        for stage in ("intake", "analyst", "structuralist"):
            with trace.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"stage": stage, "cache_hit": False}) + "\n")
            threading.Event().wait(0.7)
        return _Result()

    config = _serve_with(monkeypatch, ui, build_run=lambda *_a, **_k: _Wiring(), execute=_slow)
    stages = [e["stage"] for e in config.analyse("AAPL", 5) if e["event"] == "progress"]
    assert stages == ["intake", "analyst", "structuralist"]


def test_a_map_error_while_serving_is_reported_as_one(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`handle` turns a domain error into the CLI's own exit code and message
    rather than a traceback."""
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app
    from mapf.core.errors import MarketDataError

    ui = tmp_path / "ui"
    ui.mkdir()

    def _explode(_config: Any) -> Any:
        raise MarketDataError("the price cache is unreadable")

    monkeypatch.setattr(command, "build", _explode)
    result = CliRunner().invoke(app, ["serve", "--ui-dir", str(ui), "--no-open"])
    assert result.exit_code != 0
    assert "the price cache is unreadable" in result.output


def test_the_result_says_which_close_the_spot_is() -> None:
    """A run anchors on `last_close`, never an intraday quote. Made before a
    session closes, its own date and its price's date are different days — and
    the screen said only the first. The two coincided on the first live run,
    which is why it took a second to show."""
    result = _stream()[-1]
    assert result["price_date"] == SESSIONS[-1].isoformat()
    assert result["anchor"] == ANCHOR.isoformat()


def test_the_result_says_when_the_run_was_made_from_the_same_trace_the_journal_reads() -> None:
    """One reading of one file, so the result and the journal row cannot name two
    different minutes for one run. Without a reader the time is unknown, and the
    result says so rather than falling back to a clock."""
    made = datetime(2026, 9, 30, 12, 21, 11, tzinfo=UTC)
    asked: list[object] = []

    def started(run_id: object) -> datetime:
        asked.append(run_id)
        return made

    result = _stream(started=started)[-1]
    assert result["made_at"] == "2026-09-30T12:21:11+00:00"
    assert asked == [result["run_id"]]
    assert _stream()[-1]["made_at"] is None


def test_the_price_date_is_the_last_session_not_the_run_date() -> None:
    from mapf.serve.analyse import result_line

    line = result_line(
        run_id="r",
        ticker="KO",
        horizon=5,
        exhibit=_exhibit(),
        forecast=_Forecast(),
        applies=decide(
            horizon_days=5,
            filed=FILED,
            anchor=ANCHOR,
            sessions=SESSIONS,
            failed_screens=(),
            unevaluated=(),
        ),
        correction=_Correction(),
        price_date=date(2026, 9, 28),
    )
    assert line["price_date"] == "2026-09-28"
    # And absent rather than guessed when there is no calendar to read it from.
    assert (
        result_line(
            run_id="r",
            ticker="KO",
            horizon=5,
            exhibit=_exhibit(),
            forecast=_Forecast(),
            applies=decide(
                horizon_days=5,
                filed=FILED,
                anchor=ANCHOR,
                sessions=SESSIONS,
                failed_screens=(),
                unevaluated=(),
            ),
            correction=_Correction(),
        )["price_date"]
        is None
    )


def test_serve_can_be_made_incapable_of_touching_the_journal(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Findings #63. An intercept that stops matching fails open, so the screenshot
    server is given fixtures and a temporary runs directory: a missed intercept then
    produces a fixture answer written somewhere that is deleted afterwards."""
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app

    ui = tmp_path / "ui"
    ui.mkdir()
    captured: list[Any] = []

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr(command, "build", _capture(captured, _Server()))
    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--ui-dir",
            str(ui),
            "--no-open",
            "--fixtures",
            str(tmp_path / "fx"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
    )
    assert result.exit_code == 0, result.output
    # Loudly, so a server that cannot make a real forecast is not mistaken for one.
    assert "NOT A REAL ANALYSIS SERVER" in result.output
    assert str(tmp_path / "runs") in result.output


def test_a_plain_serve_says_nothing_about_fixtures(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app

    ui = tmp_path / "ui"
    ui.mkdir()

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr(command, "build", lambda _c: _Server())
    result = CliRunner().invoke(app, ["serve", "--ui-dir", str(ui), "--no-open"])
    assert "NOT A REAL ANALYSIS SERVER" not in result.output
    assert "every analysis is a real run" in result.output


def test_a_redirected_runs_dir_is_where_the_run_lands(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The redirect is the half that makes a missed intercept harmless: fixtures
    stop a real model call, and this stops the record."""
    import json

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")
    real = tmp_path / "real-runs"
    real.mkdir()
    redirected = tmp_path / "throwaway"

    class _Result:
        forecast = _Forecast()
        window = _Window()

    # A real dataclass, because the command redirects with `dataclasses.replace`
    # and the production `Wiring` is one. A plain class here would have made the
    # test fail for a reason the code does not have.
    @dataclass(frozen=True)
    class _Wiring:
        runs_dir: Any
        agents: Any = None
        market: Any = None
        dividends: Any = None
        trace: Any = None
        allow_nondeterministic: bool = False

    seen: list[Any] = []

    def _execute(request: Any, **kw: Any) -> Any:
        # Whatever directory the command handed the trace watcher is where a real
        # run would write, so that is what this records.
        seen.append(kw.get("runs_dir"))
        directory = kw["runs_dir"] / str(request.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "trace.jsonl").write_text(
            json.dumps({"stage": "intake", "cache_hit": True}) + "\n", encoding="utf-8"
        )
        return _Result()

    config = _serve_with(
        monkeypatch,
        ui,
        build_run=lambda *_a, **_k: _Wiring(runs_dir=real),
        execute=_execute,
        extra=["--runs-dir", str(redirected)],
    )
    list(config.analyse("AAPL", 5))

    assert seen == [redirected], "the run was written to the throwaway directory"
    assert not any(real.iterdir()), "and nothing reached the real one"


# --- the two reads, as the command wires them ----------------------------------


def _market(bars: list[tuple[date, float]], *, fails: bool = False) -> Any:
    class _Bar:
        def __init__(self, day: date, close: float) -> None:
            self.date = day
            self.close = close

    class _Window:
        provider = "yfinance"
        adjustment = "split_adjusted"

    window = _Window()
    window.bars = tuple(_Bar(d, c) for d, c in bars)  # type: ignore[attr-defined]

    class _Market:
        def get_ohlcv(self, _t: str, _start: date, _end: date) -> Any:
            if fails:
                from mapf.core.errors import MapError

                raise MapError("the provider has no such symbol")
            return window

        def median_dollar_volume(self, *_: Any) -> float:
            return 9.0e8

    return _Market()


def test_the_price_read_drops_an_unfinished_session_and_names_its_vintage(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A company page outside the corpus draws what this returns, so it follows the
    run's own rule: a bar still trading is not a close (Findings #64)."""
    from datetime import UTC, datetime

    ui = tmp_path / "ui"
    ui.mkdir()
    today = datetime.now(UTC).date()
    old = date(2026, 1, 5)
    market = _market([(old, 10.0), (today, 11.0)])
    config = _serve_with(monkeypatch, ui, build_market_data=lambda _s: market)
    body = config.prices("KO")
    assert body["fetched_on"] == today.isoformat()
    assert body["provider"] == "yfinance"
    closes = dict(body["bars"])
    assert closes[old.isoformat()] == 10.0
    # Today's bar survives only once its session has settled.
    from mapf.core.sessions import session_has_settled

    settled_now = session_has_settled(datetime.now(UTC), session=today)
    assert (today.isoformat() in closes) is settled_now


def test_the_price_read_refuses_with_the_providers_reason(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapf.serve.server import ReadRefusedError

    ui = tmp_path / "ui"
    ui.mkdir()
    failing = _market([], fails=True)
    config = _serve_with(monkeypatch, ui, build_market_data=lambda _s: failing)
    with pytest.raises(ReadRefusedError, match="no price history for KO"):
        config.prices("KO")
    empty = _market([])
    config = _serve_with(monkeypatch, ui, build_market_data=lambda _s: empty)
    with pytest.raises(ReadRefusedError, match="no settled session"):
        config.prices("KO")


def test_the_price_read_covers_exactly_two_years_to_new_yorks_today(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rolling daily on the market's calendar (ADR 0039): a close from before the
    window's first day is not drawn, and the window says where it starts and ends."""
    from datetime import UTC, datetime

    from mapf.cli.commands.serve import years_before
    from mapf.core.sessions import EXCHANGE_TZ

    ui = tmp_path / "ui"
    ui.mkdir()
    today = datetime.now(UTC).astimezone(EXCHANGE_TZ).date()
    start = years_before(today, 2)
    asked: list[tuple[date, date]] = []
    market = _market([(start - timedelta(days=1), 9.0), (start, 10.0), (date(2026, 1, 5), 11.0)])
    original = market.get_ohlcv

    def spy(ticker: str, first: date, last: date) -> Any:
        asked.append((first, last))
        return original(ticker, first, last)

    market.get_ohlcv = spy
    config = _serve_with(monkeypatch, ui, build_market_data=lambda _s: market)
    body = config.prices("KO")
    from mapf.core.sessions import session_has_settled

    closed = (
        today
        if session_has_settled(datetime.now(UTC), session=today)
        else today - timedelta(days=1)
    )
    assert asked == [(start, closed)], "asked to the last session that could have closed"

    assert body["window"] == {"start": start.isoformat(), "end": today.isoformat()}
    assert [d for d, _ in body["bars"]][0] == start.isoformat(), "nothing before the window"
    assert body["adjustment"] == "split_adjusted", "the snapshot's basis"


def test_the_quote_read_says_the_price_its_time_and_whether_the_market_is_open(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from mapf.core.models import Quote
    from mapf.core.sessions import market_state, seconds_until_next_check

    ui = tmp_path / "ui"
    ui.mkdir()
    traded = datetime.now(UTC).replace(microsecond=0)

    class _Quotes:
        name = "yfinance"

        def latest(self, ticker: str) -> Quote:
            return Quote(ticker=ticker, price=70.12, at=traded, provider="yfinance")

    config = _serve_with(monkeypatch, ui, build_quotes=lambda: _Quotes())
    body = config.quote("KO")
    now = datetime.now(UTC)
    assert body["price"] == 70.12
    assert body["at"] == traded.isoformat()
    assert body["provider"] == "yfinance"
    assert body["market"] == market_state(now, last_trade=traded)
    assert body["next_check_s"] in {
        seconds_until_next_check(now, body["market"]),
        seconds_until_next_check(now, body["market"]) - 1,
    }
    assert str(body["new_york"]).endswith(("-04:00", "-05:00")), "New York's clock, with its offset"


def test_the_quote_read_refuses_with_the_providers_reason(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapf.core.errors import EmptyPriceWindowError
    from mapf.serve.server import ReadRefusedError

    ui = tmp_path / "ui"
    ui.mkdir()

    class _Nothing:
        name = "yfinance"

        def latest(self, ticker: str) -> Any:
            raise EmptyPriceWindowError("yfinance", ticker)

    config = _serve_with(monkeypatch, ui, build_quotes=lambda: _Nothing())
    with pytest.raises(ReadRefusedError, match="no quote for KO"):
        config.quote("KO")


def test_the_runs_read_lists_only_live_runs_from_the_journal_it_writes_to(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read from `--runs-dir` when given, so a screenshot server lists what it
    wrote and never the real journal."""
    ui = tmp_path / "ui"
    ui.mkdir()
    seen: list[Any] = []

    class _Entry:
        def __init__(self, ticker: str, day: str) -> None:
            self.ticker = ticker
            self.day = day

    class _Journal:
        def of(self, source: str) -> tuple[Any, ...]:
            seen.append(source)
            if source == "edgar":
                return (_Entry("KO", "2026-09-01"), _Entry("AAPL", "2026-09-02"))
            return (_Entry("KO", "2026-09-28"),)

    def _read(runs_dir: Any, **kw: Any) -> Any:
        seen.append(runs_dir)
        return _Journal()

    elsewhere = tmp_path / "elsewhere"
    config = _serve_with(
        monkeypatch,
        ui,
        ["--runs-dir", str(elsewhere)],
        read_journal=_read,
        as_dict=lambda e: {"ticker": e.ticker, "anchor_date": e.day},
    )
    rows = config.live_runs("KO")
    assert seen[0] == elsewhere
    assert seen[1:] == ["edgar", "news"], "the two live populations and nothing else"
    assert [r["anchor_date"] for r in rows] == ["2026-09-28", "2026-09-01"], "newest first"


# --- the fan: every session, from the scored sample -----------------------------


def _paths(horizon: int = 5) -> Any:
    from mapf.eval.montecarlo import simulate_paths
    from tests.conftest import make_scenario_set

    return simulate_paths(make_scenario_set(), horizon_days=horizon)


def test_the_fan_grades_in_nine_central_intervals() -> None:
    from mapf.serve.analyse import BAND_LEVELS, FAN_LEVELS

    assert len(FAN_LEVELS) == 19
    assert FAN_LEVELS[0] == 0.05 and FAN_LEVELS[-1] == 0.95
    # The band's four levels are among them, so the two cannot disagree.
    assert set(BAND_LEVELS) <= set(FAN_LEVELS)


def test_the_fan_opens_from_the_spot_and_ends_on_the_band() -> None:
    from mapf.serve.analyse import BAND_LEVELS, FAN_LEVELS, band_prices, fan_prices

    paths = _paths()
    fan = fan_prices(100.0, paths)
    sessions = fan["sessions"]
    assert isinstance(sessions, list)
    assert sessions[0]["prices"] == [100.0] * 19, "every level starts at the spot"
    assert [s["session"] for s in sessions] == [0, 1, 2, 3, 4, 5]
    band = band_prices(
        100.0,
        paths.terminal.quantiles(BAND_LEVELS),
        mean=paths.terminal.mean,
        sigma=paths.terminal.sigma,
    )
    at_horizon = dict(zip(FAN_LEVELS, sessions[-1]["prices"], strict=True))
    for point in band:
        assert at_horizon[point["level"]] == pytest.approx(point["price"], rel=1e-12)


def test_the_fan_widens_every_session() -> None:
    from mapf.serve.analyse import fan_prices

    fan = fan_prices(100.0, _paths(21))
    widths = [s["prices"][-1] - s["prices"][0] for s in fan["sessions"]]
    assert all(b > a for a, b in zip(widths, widths[1:], strict=False))


def test_a_corrected_fan_is_the_corrected_band_at_the_horizon_and_wider_throughout() -> None:
    from mapf.serve.analyse import BAND_LEVELS, FAN_LEVELS, band_prices, fan_prices

    paths = _paths()
    raw = fan_prices(100.0, paths)["sessions"]
    fixed = fan_prices(100.0, paths, correction=_Correction())["sessions"]
    band = band_prices(
        100.0,
        paths.terminal.quantiles(BAND_LEVELS),
        mean=paths.terminal.mean,
        sigma=paths.terminal.sigma,
        correction=_Correction(),
    )
    at_horizon = dict(zip(FAN_LEVELS, fixed[-1]["prices"], strict=True))
    for point in band:
        assert at_horizon[point["level"]] == pytest.approx(point["price"], rel=1e-12)
    for r, c in zip(raw[1:], fixed[1:], strict=True):
        assert c["prices"][-1] - c["prices"][0] > r["prices"][-1] - r["prices"][0]


def test_each_scenario_curve_ends_on_the_price_it_states() -> None:
    from mapf.serve.analyse import scenario_paths

    curves = scenario_paths(200.0, _Scenarios(), 5)
    assert [c["name"] for c in curves] == ["bullish", "base_case", "bearish"]
    bull = curves[0]["prices"]
    assert isinstance(bull, list)
    assert bull[0] == 200.0
    assert bull[-1] == pytest.approx(200.0 * 1.06), "a simple return, as the table reads it"
    assert len(bull) == 6


def test_the_history_is_the_last_three_months_of_the_runs_own_window() -> None:
    from datetime import timedelta

    from mapf.serve.analyse import HISTORY_SESSIONS, history

    bars = [_Bar(date(2026, 1, 1) + timedelta(days=i), 100.0 + i) for i in range(100)]
    closes = history(bars)
    assert len(closes) == HISTORY_SESSIONS == 63
    assert closes[-1] == [bars[-1].date.isoformat(), bars[-1].close]
    assert len(history(bars[:5])) == 5


def test_a_run_carries_its_fan_its_curves_and_its_history() -> None:
    from mapf.eval.montecarlo import simulate_paths

    line = _stream(simulate=lambda forecast, h: simulate_paths(forecast.scenarios, horizon_days=h))[
        -1
    ]
    fan = line["fan"]
    assert isinstance(fan, dict) and len(fan["sessions"]) == 6
    assert len(_listed(line, "scenario_paths")) == 3
    assert _listed(line, "history")[-1][0] == SESSIONS[-1].isoformat()


def test_a_run_with_no_simulator_carries_no_fan_rather_than_an_invented_one() -> None:
    line = _stream()[-1]
    assert line["fan"] is None
    assert line["band"] == []


# --- --replay: watching the page work without spending a run --------------------


def _recorded(tmp_path: Any) -> tuple[Any, str, Any]:
    """A recorded run under a temporary runs directory, with a three-stage trace."""
    import json
    from datetime import timedelta

    from tests.unit.test_journal import _write_run

    runs = tmp_path / "recorded"
    run_id = _write_run(runs, ticker="KO", source="edgar")
    forecast = json.loads((runs / run_id / "forecast.json").read_text())
    start = datetime.fromisoformat(forecast["as_of"])
    gaps = {"intake": 104, "analyst": 442, "structuralist": 52}
    at = start
    lines = []
    for stage, seconds in gaps.items():
        at = at + timedelta(seconds=seconds)
        lines.append(
            json.dumps({"at": at.isoformat(), "stage": stage, "cache_hit": stage == "intake"})
        )
    (runs / run_id / "trace.jsonl").write_text("\n".join(lines) + "\n")
    return runs, run_id, start


def _replaying(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, runs: Any, extra: list[str]) -> Any:
    import mapf.cli.commands.serve as command
    from mapf.settings import load

    real = load(None)
    paths = real.paths.model_copy(update={"runs_dir": runs})
    # The price cache too: left real, the replay's history would read this
    # checkout's gitignored snapshots (Findings #67).
    cache = real.cache.model_copy(update={"price_dir": tmp_path / "prices"})
    isolated = real.model_copy(update={"paths": paths, "cache": cache})
    monkeypatch.setattr(command, "load", lambda _c=None: isolated)
    ui = tmp_path / "ui"
    ui.mkdir(exist_ok=True)
    return _serve_with(monkeypatch, ui, extra)


def test_a_replay_streams_the_recorded_stages_at_their_recorded_gaps(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real events from a real trace, paced by the gaps it recorded and divided by
    the speed asked for — and every event that could be mistaken for a live run
    says it is a replay."""
    import mapf.cli.commands.serve as command

    runs, run_id, _start = _recorded(tmp_path)
    paused: list[float] = []
    monkeypatch.setattr(command, "_pause", paused.append)
    config = _replaying(tmp_path, monkeypatch, runs, ["--replay", run_id, "--replay-speed", "10"])
    lines = list(config.analyse("KO", 5))
    assert [line["event"] for line in lines] == [
        "started",
        "filing",
        "progress",
        "progress",
        "progress",
        "result",
    ]
    assert lines[0]["replay"] == {"run_id": run_id, "speed": 10.0}
    assert [line["stage"] for line in lines[2:5]] == ["intake", "analyst", "structuralist"]
    assert lines[2]["detail"] == "cached"
    assert paused == pytest.approx([10.4, 44.2, 5.2])
    row = lines[-1]["replay"]
    assert row["run_id"] == run_id
    assert row["fan"] is not None and len(row["fan"]["sessions"]) == 6


def test_a_replay_refuses_a_company_it_did_not_record(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, run_id, _ = _recorded(tmp_path)
    config = _replaying(tmp_path, monkeypatch, runs, ["--replay", run_id])
    for ticker, horizon in (("AAPL", 5), ("KO", 21)):
        (only,) = list(config.analyse(ticker, horizon))
        assert only["event"] == "failed"
        assert "replays one recorded run, KO over 5 sessions" in str(only["why"])


def test_a_replay_of_a_run_that_is_not_there_refuses_to_start(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, _run_id, _ = _recorded(tmp_path)
    config = _replaying(tmp_path, monkeypatch, runs, ["--replay", "no-such-run"])
    assert config is None, "the server was never built"


def test_a_replay_server_says_so_before_anything_else(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import mapf.cli.commands.serve as command
    from mapf.cli.app import app
    from mapf.settings import load

    runs, run_id, _ = _recorded(tmp_path)
    real = load(None)
    paths = real.paths.model_copy(update={"runs_dir": runs})
    # The price cache too: left real, the replay's history would read this
    # checkout's gitignored snapshots (Findings #67).
    cache = real.cache.model_copy(update={"price_dir": tmp_path / "prices"})
    isolated = real.model_copy(update={"paths": paths, "cache": cache})
    monkeypatch.setattr(command, "load", lambda _c=None: isolated)

    class _Server:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return None

    monkeypatch.setattr(command, "build", lambda _c: _Server())
    ui = tmp_path / "ui"
    ui.mkdir()
    result = CliRunner().invoke(
        app, ["serve", "--ui-dir", str(ui), "--no-open", "--replay", run_id, "--replay-speed", "10"]
    )
    assert result.exit_code == 0, result.output
    assert (
        f"NOT A REAL ANALYSIS SERVER — Analyse replays recorded run {run_id} at 10x"
        in result.output
    )
    assert "writes nothing" in result.output
