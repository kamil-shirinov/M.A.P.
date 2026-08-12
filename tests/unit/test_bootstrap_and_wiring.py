"""The composition root, and the pieces module 7 added around it.

`bootstrap` is the one module exempt from the forbidden-import contracts, and
therefore the one place a boundary breach can still hide. These tests pin what it
constructs so a future edit that quietly swaps an adapter shows up here.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mapf.bootstrap import (
    build_dividends,
    build_http_client,
    build_llm_provider,
    build_market_data,
    build_run,
    build_symbol_index,
)
from mapf.core.hashing import new_run_id
from mapf.core.models import Bar, Forecast, PriceWindow
from mapf.core.ports import LLMResponse, ModelInfo, RenderedPrompt, SamplingParams
from mapf.data.cache import ParquetPriceCache
from mapf.data.providers.dividends import NullDividendSource, YFinanceDividendSource
from mapf.pipeline.trace import CountingTrace, JsonlTrace
from mapf.providers.caching import CachingProvider
from mapf.providers.fake import FakeProvider, RecordingProvider
from mapf.render.chart import build_figure, write_chart
from mapf.settings import load
from tests.unit.test_cli import _config

runner = CliRunner()

MODEL = ModelInfo(id="qwen3-4b", fingerprint="fp", fingerprint_source="digest")
SAMPLING = SamplingParams(temperature=0.0, seed=7)


def _settings(tmp_path: Path) -> Any:
    return load([_config(tmp_path)])


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------
def test_the_live_provider_is_the_http_adapter_behind_a_cache(tmp_path: Path) -> None:
    provider = build_llm_provider(_settings(tmp_path))
    assert isinstance(provider, CachingProvider)


def test_fixtures_select_the_fake_provider(tmp_path: Path) -> None:
    """Why `FakeProvider` ships in `src/`: the CLI must run with no server."""
    provider = build_llm_provider(_settings(tmp_path), fixtures=tmp_path / "llm")
    assert isinstance(provider, FakeProvider)


def test_market_data_is_the_chain_behind_the_parquet_cache(tmp_path: Path) -> None:
    market = build_market_data(_settings(tmp_path))
    assert isinstance(market, ParquetPriceCache)
    assert market.name == "yfinance+stooq"


def test_dividends_use_yahoo_when_it_is_in_the_chain(tmp_path: Path) -> None:
    assert isinstance(build_dividends(_settings(tmp_path)), YFinanceDividendSource)


def test_dividends_fall_back_to_an_honest_unknown(tmp_path: Path) -> None:
    config = (
        _config(tmp_path)
        .read_text(encoding="utf-8")
        .replace('provider_order = ["yfinance", "stooq"]', 'provider_order = ["stooq"]')
    )
    path = tmp_path / "stooq-only.toml"
    path.write_text(config, encoding="utf-8")
    assert isinstance(build_dividends(load([path])), NullDividendSource)


def test_the_symbol_index_points_at_the_configured_database(tmp_path: Path) -> None:
    index = build_symbol_index(_settings(tmp_path))
    assert index is not None


def test_the_http_client_uses_the_configured_timeouts(tmp_path: Path) -> None:
    with build_http_client(_settings(tmp_path)) as client:
        assert client.timeout.connect == pytest.approx(0.05)


def test_the_trace_is_wrapped_before_the_agents_are_built(tmp_path: Path) -> None:
    """If the tap were added afterwards it would count nothing: each agent holds
    its own reference, so the manifest's attempt counts would all be zero."""
    settings = _settings(tmp_path)
    run_id = new_run_id()
    resolved = dict.fromkeys(("intake", "analyst", "structuralist"), MODEL)
    wiring = build_run(settings, provider=FakeProvider(tmp_path), resolved=resolved, run_id=run_id)
    assert isinstance(wiring.trace, CountingTrace)
    assert wiring.agents.intake._trace is wiring.trace  # noqa: SLF001
    assert wiring.agents.structuralist._trace is wiring.trace  # noqa: SLF001
    assert wiring.allow_nondeterministic is False


# ---------------------------------------------------------------------------
# dividends (ADR 0013)
# ---------------------------------------------------------------------------
def test_a_null_dividend_source_reports_unknown_not_none() -> None:
    window = NullDividendSource().dividends_in("AAPL", date(2026, 8, 11), date(2026, 9, 1))
    assert window.known is False
    assert window.ex_dates == ()


def test_yahoo_dividends_inside_the_window_are_recorded() -> None:
    source = YFinanceDividendSource(
        lookup=lambda ticker: [(date(2026, 8, 14), 0.25), (date(2026, 12, 1), 0.26)]
    )
    window = source.dividends_in("AAPL", date(2026, 8, 11), date(2026, 9, 1))
    assert window.known is True
    assert window.ex_dates == (date(2026, 8, 14),)
    assert window.total_amount == pytest.approx(0.25)


def test_a_failed_dividend_lookup_never_blocks_a_forecast() -> None:
    def boom(ticker: str) -> list[tuple[date, float]]:
        raise RuntimeError("Yahoo changed the page")

    window = YFinanceDividendSource(lookup=boom).dividends_in(
        "AAPL", date(2026, 8, 11), date(2026, 9, 1)
    )
    assert window.known is False
    assert window.source == "lookup_failed"


def test_a_backwards_dividend_window_is_rejected() -> None:
    """A window that ends before it starts would silently contain no ex-dates and
    read as a clean window."""
    from pydantic import ValidationError

    from mapf.core.models import DividendWindow

    with pytest.raises(ValidationError, match="before it starts"):
        DividendWindow(start=date(2026, 9, 1), end=date(2026, 8, 11))


def test_a_dividend_window_cannot_claim_detail_while_unknown() -> None:
    """Guards the ambiguity the flag exists to remove."""
    from pydantic import ValidationError

    from mapf.core.models import DividendWindow

    with pytest.raises(ValidationError, match="while known is False"):
        DividendWindow(start=date(2026, 8, 11), end=date(2026, 9, 1), ex_dates=(date(2026, 8, 14),))


# ---------------------------------------------------------------------------
# RecordingProvider (--record-to)
# ---------------------------------------------------------------------------
class _Inner:
    def list_models(self) -> tuple[ModelInfo, ...]:
        return (MODEL,)

    def complete(self, **kwargs: Any) -> LLMResponse:
        return LLMResponse(text='{"ok": true}', model_id=MODEL.id)


def _prompt() -> RenderedPrompt:
    from mapf.core.ports import Message

    return RenderedPrompt(
        template_name="structuralist",
        template_version="v1",
        template_sha256="0" * 64,
        messages=(Message(role="user", content="hello"),),
    )


def test_recording_writes_a_replayable_fixture(tmp_path: Path) -> None:
    """A fixture that came from a different code path is a guess about what the
    real path would have produced."""
    destination = tmp_path / "recorded"
    recorder = RecordingProvider(_Inner(), destination)
    recorder.list_models()
    recorder.complete(model=MODEL, prompt=_prompt(), sampling=SAMPLING)

    assert recorder.recorded
    replayed = FakeProvider(destination).complete(model=MODEL, prompt=_prompt(), sampling=SAMPLING)
    assert replayed.text == '{"ok": true}'
    assert (destination / "models.json").is_file()


def test_recording_has_no_default_destination() -> None:
    """A production command must never write into tests/fixtures/ on its own."""
    import inspect

    signature = inspect.signature(RecordingProvider.__init__)
    assert signature.parameters["destination"].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------
def test_the_trace_closes_and_is_a_context_manager(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    with JsonlTrace(path) as trace:
        trace.record(stage="intake", data={"k": "v"})
    assert json.loads(path.read_text(encoding="utf-8").strip())["stage"] == "intake"


def test_sub_stage_events_are_not_counted_as_attempts(tmp_path: Path) -> None:
    """`structuralist.validation_failed` is an event, not a call. Counting it
    would double every repair in the manifest."""
    trace = CountingTrace(JsonlTrace(tmp_path / "t.jsonl"))
    trace.record(
        stage="structuralist",
        attempt=0,
        data={"template": "structuralist.v1", "template_sha256": "a" * 64},
    )
    trace.record(stage="structuralist.validation_failed", attempt=0)
    trace.record(
        stage="structuralist",
        attempt=1,
        cache_hit=True,
        data={"template": "structuralist_repair.v1", "template_sha256": "b" * 64},
    )
    assert trace.attempts["structuralist"] == 2
    assert trace.cache_hits["structuralist"] == 1
    # The first template seen wins: it is the one the agent actually started with.
    assert trace.templates["structuralist"] == ("structuralist", "v1", "a" * 64)


# ---------------------------------------------------------------------------
# chart
# ---------------------------------------------------------------------------
def _window() -> PriceWindow:
    return PriceWindow(
        ticker="AAPL",
        provider="yfinance",
        adjustment="split_adjusted",
        bars=(
            Bar(date=date(2026, 8, 3), open=200.0, high=202.0, low=199.0, close=201.0, volume=1),
            Bar(date=date(2026, 8, 4), open=201.0, high=203.0, low=200.0, close=202.0, volume=1),
        ),
    )


def _forecast(horizon: int = 21) -> Forecast:
    from mapf.core.models import ModelVersions
    from tests.conftest import make_scenario_set

    return Forecast(
        run_id=new_run_id(),
        ticker="AAPL",
        as_of=datetime(2026, 8, 11, tzinfo=UTC),
        horizon_days=horizon,
        spot_price=202.0,
        source_doc_ids=("sha256:" + "a" * 64,),
        model_versions=ModelVersions(intake="a", analyst="b", structuralist="c"),
        scenarios=make_scenario_set(),
    )


def test_a_one_day_horizon_still_draws(tmp_path: Path) -> None:
    figure = build_figure(_window(), _forecast(horizon=1))
    assert len(figure.data) == 4


def test_the_chart_writes_a_single_file(tmp_path: Path) -> None:
    path = write_chart(_window(), _forecast(), tmp_path / "nested" / "chart.html")
    assert path.is_file()
    assert path.stat().st_size > 500_000


def test_scenario_paths_end_at_the_stated_return() -> None:
    """A path that does not arrive where the forecast says it does is a chart that
    disagrees with its own JSON.

    No division by 100: `price_return` is a fraction, and the whole point of the
    migration was to remove that conversion from every consumer.
    """
    from mapf.render.chart import _path_prices

    forecast = _forecast()
    prices = _path_prices(forecast.spot_price, forecast.scenarios.bullish, forecast.horizon_days)
    expected = forecast.spot_price * (1 + forecast.scenarios.bullish.price_return)
    assert prices[0] == pytest.approx(forecast.spot_price)
    assert prices[-1] == pytest.approx(expected)
    assert len(prices) == forecast.horizon_days + 1


# ---------------------------------------------------------------------------
# Prompt selection is config, not code (known issue 5)
# ---------------------------------------------------------------------------
def test_an_agent_uses_its_class_default_template() -> None:
    from mapf.agents.intake import IntakeAgent

    agent = IntakeAgent(
        provider=FakeProvider(Path("/nonexistent")),
        model=MODEL,
        sampling=SAMPLING,
        prompts=object(),  # type: ignore[arg-type]
        trace=object(),  # type: ignore[arg-type]
        stage="intake",
    )
    assert (agent.template, agent.version) == ("intake", "v1")


def test_a_prompt_variant_needs_no_edit_to_the_agents_package() -> None:
    """The abstraction CLAUDE.md §4 claims: a per-model prompt variant is a config
    edit. It was not true while the template name was a module constant."""
    from mapf.agents.structuralist import StructuralistAgent

    agent = StructuralistAgent(
        provider=FakeProvider(Path("/nonexistent")),
        model=MODEL,
        sampling=SAMPLING,
        prompts=object(),  # type: ignore[arg-type]
        trace=object(),  # type: ignore[arg-type]
        stage="structuralist",
        max_attempts=3,
        template="structuralist_single_agent",
        version="v7",
    )
    assert (agent.template, agent.version) == ("structuralist_single_agent", "v7")


def test_the_configured_prompt_version_reaches_the_agents(tmp_path: Path) -> None:
    config = _config(tmp_path).read_text(encoding="utf-8")
    config += '\n[prompts]\nintake = "v9"\nanalyst = "v9"\nstructuralist = "v9"\n'
    path = tmp_path / "v9.toml"
    path.write_text(config, encoding="utf-8")

    settings = load([path])
    wiring = build_run(
        settings,
        provider=FakeProvider(tmp_path),
        resolved=dict.fromkeys(("intake", "analyst", "structuralist"), MODEL),
        run_id=new_run_id(),
    )
    assert wiring.agents.intake.version == "v9"
    assert wiring.agents.analyst.version == "v9"
    assert wiring.agents.structuralist.version == "v9"


def test_prompt_versions_default_to_v1_when_unconfigured(tmp_path: Path) -> None:
    """The section is optional; an existing config keeps working."""
    assert _settings(tmp_path).prompts.structuralist == "v1"
