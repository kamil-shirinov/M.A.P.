"""The CLI surface: sentences and exit codes, not tracebacks.

A CLI is also an API. Every failure a user can cause has to arrive as a sentence
and a meaningful exit code, because the first thing anyone will do with this tool
is run it before starting their inference server.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from mapf.cli.app import (
    EXIT_CONFIG,
    EXIT_DATA,
    EXIT_INFERENCE,
    EXIT_MODEL_OUTPUT,
    app,
    exit_code_for,
    hint_for,
)
from mapf.core.errors import (
    AllMarketDataProvidersFailedError,
    ConfigurationError,
    ForecastRepairExhausted,
    InferenceUnreachableError,
    MapError,
    ModelNotAvailableError,
    SymbolIndexMissingError,
)

runner = CliRunner()


def _config(tmp_path: Path, **overrides: str) -> Path:
    body = f"""
[inference]
base_url = "{overrides.get("base_url", "http://127.0.0.1:9/v1")}"
connect_timeout_s = 0.05
read_timeout_s = 0.05
max_repair_attempts = 3

[models.intake]
alias = "llama-3.2-3b"
temperature = 0.0

[models.analyst]
alias = "gemma4-12b"
temperature = 0.7

[models.structuralist]
alias = "qwen3-4b"
temperature = 0.0

[cache]
llm_dir = "{tmp_path / "llm"}"
price_dir = "{tmp_path / "prices"}"

[data]
provider_order = ["yfinance", "stooq"]
adjustment = "split_adjusted"
history_days = 730

[data.sec]
user_agent = "{overrides.get("user_agent", "Test Runner test@example.com")}"
requests_per_second = 8.0
tickers_url = "https://example.test/tickers.json"
symbols_db = "{tmp_path / "symbols.sqlite"}"
refresh_days = 30

[news]
dir = "{tmp_path / "news"}"
rss_urls = []

[paths]
runs_dir = "{tmp_path / "runs"}"
"""
    path = tmp_path / "default.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The exit-code map — one place, so it cannot drift
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            InferenceUnreachableError("http://localhost:1234/v1", "connection refused"),
            EXIT_INFERENCE,
        ),
        (ModelNotAvailableError("qwen3-4b", []), EXIT_INFERENCE),
        (ConfigurationError("bad config"), EXIT_CONFIG),
        (ForecastRepairExhausted(3, ("bad",), "{}"), EXIT_MODEL_OUTPUT),
        (SymbolIndexMissingError("/tmp/x.sqlite"), EXIT_DATA),
        (AllMarketDataProvidersFailedError({}), EXIT_DATA),
        (MapError("something else"), 1),
    ],
)
def test_every_failure_has_a_meaningful_exit_code(error: MapError, code: int) -> None:
    assert exit_code_for(error) == code


def test_a_model_not_available_is_inference_not_config() -> None:
    """It subclasses ConfigurationError, so ordering in the mapper is load-bearing:
    the remedy is loading a model, not editing a file."""
    assert exit_code_for(ModelNotAvailableError("x", [])) == EXIT_INFERENCE


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (
            InferenceUnreachableError("http://localhost:1234/v1", "connection refused"),
            "Start your inference server",
        ),
        (ModelNotAvailableError("x", []), "Load the model in your server"),
        (SymbolIndexMissingError("/tmp/x"), "map symbols sync"),
    ],
)
def test_the_remedy_is_named_where_there_is_exactly_one(error: MapError, fragment: str) -> None:
    hint = hint_for(error)
    assert hint is not None
    assert fragment in hint


def test_no_hint_is_invented_where_there_is_no_single_remedy() -> None:
    assert hint_for(ConfigurationError("something ambiguous")) is None


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------
def test_health_against_a_dead_server_is_a_sentence(tmp_path: Path) -> None:
    result = runner.invoke(app, ["health", "--config", str(_config(tmp_path))])
    assert result.exit_code == EXIT_INFERENCE
    assert result.output.startswith("error:")
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def test_search_without_an_index_names_the_sync_command(tmp_path: Path) -> None:
    result = runner.invoke(app, ["search", "apple", "--config", str(_config(tmp_path))])
    assert result.exit_code == EXIT_DATA
    assert "map symbols sync" in result.output


def test_search_finds_a_symbol(tmp_path: Path) -> None:
    from mapf.data.symbols import Throttle, sync

    fixture = Path(__file__).parents[1] / "fixtures" / "sec" / "company_tickers_exchange.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=fixture.read_bytes())

    config = _config(tmp_path)
    sync(
        tmp_path / "symbols.sqlite",
        url="https://example.test/tickers.json",
        user_agent="Test Runner test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=Throttle(8.0, sleep=lambda _: None),
    )
    result = runner.invoke(app, ["search", "apple", "--config", str(config)])
    assert result.exit_code == 0
    assert "AAPL" in result.output


def test_search_with_no_match_states_the_coverage_limit(tmp_path: Path) -> None:
    from mapf.data.symbols import Throttle, sync

    fixture = Path(__file__).parents[1] / "fixtures" / "sec" / "company_tickers_exchange.json"
    sync(
        tmp_path / "symbols.sqlite",
        url="https://example.test/tickers.json",
        user_agent="Test Runner test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=fixture.read_bytes())
            )
        ),
        throttle=Throttle(8.0, sleep=lambda _: None),
    )
    result = runner.invoke(app, ["search", "zzznotacompany", "--config", str(_config(tmp_path))])
    assert "US-listed companies only" in result.output


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
def test_run_rejects_an_out_of_range_horizon(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", "AAPL", "--horizon", "999", "--config", str(_config(tmp_path))]
    )
    assert result.exit_code == 2
    assert "--horizon must be between 1 and 252" in result.output


def test_run_without_news_says_so(tmp_path: Path) -> None:
    """A forecast needs something to reason from, and the message says where to
    put it rather than failing three agents later."""
    result = runner.invoke(app, ["run", "AAPL", "--config", str(_config(tmp_path))])
    assert result.exit_code == EXIT_DATA
    assert "no news found" in result.output


def test_a_placeholder_user_agent_is_a_config_error(tmp_path: Path) -> None:
    config = _config(tmp_path, user_agent="REPLACE_ME <your.name> <your.email@example.com>")
    result = runner.invoke(app, ["search", "apple", "--config", str(config)])
    assert result.exit_code == EXIT_CONFIG
    assert "MAP_DATA__SEC__USER_AGENT" in result.output


# ---------------------------------------------------------------------------
# Happy paths — bootstrap is patched so no server is needed
# ---------------------------------------------------------------------------
class _StubProvider:
    """Answers all three agents. Substituted for the live adapter."""

    def __init__(self) -> None:
        import json as _json

        self.calls = 0
        self._scenarios = _json.dumps(
            {
                name: {
                    "justification": f"A sufficiently long justification for {name}.",
                    "probability_weight": weight,
                    "price_return": modifier,
                    "annualised_vol": 0.3,
                }
                for name, weight, modifier in (
                    ("bullish", 0.25, 0.045),
                    ("base_case", 0.60, 0.008),
                    ("bearish", 0.15, -0.082),
                )
            }
        )

    def list_models(self):  # type: ignore[no-untyped-def]
        from mapf.core.ports import ModelInfo

        return tuple(
            ModelInfo(id=alias, fingerprint=f"fp-{alias}", fingerprint_source="tag")
            for alias in ("llama-3.2-3b", "gemma4-12b", "qwen3-4b")
        )

    def complete(self, *, model, prompt, sampling, json_schema=None, attempt=0):  # type: ignore[no-untyped-def]
        from mapf.core.ports import LLMResponse

        self.calls += 1
        if model.id == "llama-3.2-3b":
            text = "- Revenue rose 8%."
        elif model.id == "gemma4-12b":
            text = "Bullish: " + "prose. " * 30
        else:
            text = self._scenarios
        return LLMResponse(text=text, model_id=model.id)


class _StubMarket:
    @property
    def name(self) -> str:
        return "yfinance"

    def get_ohlcv(self, ticker, start, end):  # type: ignore[no-untyped-def]
        from datetime import date as _date
        from datetime import timedelta as _td

        from mapf.core.models import Bar, PriceWindow

        base = _date(2026, 8, 3)
        return PriceWindow(
            ticker=ticker,
            provider="yfinance",
            adjustment="split_adjusted",
            bars=tuple(
                Bar(
                    date=base + _td(days=i),
                    open=200.0 + i,
                    high=202.0 + i,
                    low=199.0 + i,
                    close=201.0 + i,
                    volume=1,
                )
                for i in range(3)
            ),
        )


def test_health_reports_every_configured_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapf.cli.commands import health as health_module

    monkeypatch.setattr(health_module, "build_llm_provider", lambda s, cached=True: _StubProvider())
    result = runner.invoke(
        app, ["health", "--no-grammar-probe", "--config", str(_config(tmp_path))]
    )
    assert result.exit_code == 0
    assert "all configured models are loaded" in result.output
    # ADR 0001: a backend without a digest must say so rather than imply pinning.
    assert "does not expose a weight digest" in result.output


def test_health_names_a_missing_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mapf.cli.commands import health as health_module

    class _Partial(_StubProvider):
        def list_models(self):  # type: ignore[no-untyped-def]
            models = _StubProvider.list_models(self)  # type: ignore[no-untyped-call]
            return tuple(m for m in models if m.id != "qwen3-4b")

    monkeypatch.setattr(health_module, "build_llm_provider", lambda s, cached=True: _Partial())
    result = runner.invoke(
        app, ["health", "--no-grammar-probe", "--config", str(_config(tmp_path))]
    )
    assert result.exit_code == EXIT_INFERENCE
    assert "qwen3-4b" in result.output


def test_run_end_to_end_writes_every_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapf import bootstrap
    from mapf.cli.commands import run as run_module

    news = tmp_path / "news"
    news.mkdir()
    (news / "a.txt").write_text("Apple reported quarterly revenue of $94.9bn.", encoding="utf-8")

    monkeypatch.setattr(run_module, "build_llm_provider", lambda s, fixtures=None: _StubProvider())
    monkeypatch.setattr(bootstrap, "build_market_data", lambda s: _StubMarket())
    monkeypatch.setattr(bootstrap, "build_dividends", lambda s: _NullDiv())

    result = runner.invoke(
        app, ["run", "AAPL", "--horizon", "21", "--config", str(_config(tmp_path))]
    )
    assert result.exit_code == 0, result.output
    assert "bullish" in result.output
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    for artifact in ("forecast.json", "manifest.json", "trace.jsonl", "chart.html"):
        assert (runs[0] / artifact).is_file()
    # ADR 0013: an unknown dividend window is surfaced, not swallowed.
    assert "must not read that as 'none'" in result.output


class _NullDiv:
    def dividends_in(self, ticker, start, end):  # type: ignore[no-untyped-def]
        from mapf.core.models import DividendWindow

        return DividendWindow(start=start, end=end, known=False, source="none")


def test_symbols_sync_builds_the_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mapf.cli.commands import symbols as symbols_module

    fixture = Path(__file__).parents[1] / "fixtures" / "sec" / "company_tickers_exchange.json"
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=fixture.read_bytes()))
    )
    monkeypatch.setattr(symbols_module, "build_http_client", lambda s: client)
    result = runner.invoke(app, ["symbols", "sync", "--config", str(_config(tmp_path))])
    assert result.exit_code == 0
    assert "indexed 6 US-listed symbols" in result.output
    assert (tmp_path / "symbols.sqlite").is_file()


def test_record_to_captures_the_run_for_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fixture must come from the code path production uses, or it is a guess."""
    from mapf import bootstrap
    from mapf.cli.commands import run as run_module

    news = tmp_path / "news"
    news.mkdir()
    (news / "a.txt").write_text("Apple reported revenue of $94.9bn.", encoding="utf-8")
    monkeypatch.setattr(run_module, "build_llm_provider", lambda s, fixtures=None: _StubProvider())
    monkeypatch.setattr(bootstrap, "build_market_data", lambda s: _StubMarket())
    monkeypatch.setattr(bootstrap, "build_dividends", lambda s: _NullDiv())

    destination = tmp_path / "recorded"
    result = runner.invoke(
        app,
        ["run", "AAPL", "--record-to", str(destination), "--config", str(_config(tmp_path))],
    )
    assert result.exit_code == 0, result.output
    recordings = list(destination.glob("*.json"))
    assert len(recordings) >= 4  # three completions plus models.json


def test_a_dividend_inside_the_window_is_surfaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0013: a split-adjusted series keeps the ex-dividend drop, and the user
    is told before Phase 2 has to work it out."""
    from datetime import timedelta as _td

    from mapf import bootstrap
    from mapf.cli.commands import run as run_module

    class _WithDividend:
        def dividends_in(self, ticker, start, end):  # type: ignore[no-untyped-def]
            from mapf.core.models import DividendWindow

            return DividendWindow(
                start=start,
                end=end,
                ex_dates=(start + _td(days=5),),
                total_amount=0.25,
                known=True,
                source="test",
            )

    news = tmp_path / "news"
    news.mkdir()
    (news / "a.txt").write_text("Apple reported revenue.", encoding="utf-8")
    monkeypatch.setattr(run_module, "build_llm_provider", lambda s, fixtures=None: _StubProvider())
    monkeypatch.setattr(bootstrap, "build_market_data", lambda s: _StubMarket())
    monkeypatch.setattr(bootstrap, "build_dividends", lambda s: _WithDividend())

    result = runner.invoke(app, ["run", "AAPL", "--config", str(_config(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "ex-dividend date(s) in the window" in result.output


def test_the_entry_point_is_wired() -> None:
    """`[project.scripts] map = mapf.cli.app:main` — a broken entry point makes
    every other CLI test meaningless."""
    from mapf.cli.app import main

    assert callable(main)


def test_run_translates_a_missing_model_into_an_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapf.cli.commands import run as run_module

    class _Empty:
        def list_models(self):  # type: ignore[no-untyped-def]
            return ()

    news = tmp_path / "news"
    news.mkdir()
    (news / "a.txt").write_text("Apple reported revenue.", encoding="utf-8")
    monkeypatch.setattr(run_module, "build_llm_provider", lambda s, fixtures=None: _Empty())

    result = runner.invoke(app, ["run", "AAPL", "--config", str(_config(tmp_path))])
    assert result.exit_code == EXIT_INFERENCE
    assert "Load the model in your server" in result.output


def test_symbols_sync_translates_a_config_error(tmp_path: Path) -> None:
    config = _config(tmp_path, user_agent="REPLACE_ME nobody")
    result = runner.invoke(app, ["symbols", "sync", "--config", str(config)])
    assert result.exit_code == EXIT_CONFIG
    assert "403" in result.output


def test_main_invokes_the_typer_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import mapf.cli.app as app_module

    called: list[bool] = []
    monkeypatch.setattr(app_module, "app", lambda: called.append(True))
    app_module.main()
    assert called == [True]


def test_health_probes_the_grammar_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open question 8 is the most likely first-run failure; finding it here beats
    finding it after two model swaps at the end of a pipeline."""

    from mapf.cli.commands import health as health_module

    class _Constrained(_StubProvider):
        def complete(self, *, model, prompt, sampling, json_schema=None, attempt=0):  # type: ignore[no-untyped-def]
            from mapf.core.ports import LLMResponse

            assert json_schema is not None and "$defs" in json_schema
            return LLMResponse(text=self._scenarios, model_id=model.id)

    monkeypatch.setattr(health_module, "build_llm_provider", lambda s, cached=True: _Constrained())
    result = runner.invoke(app, ["health", "--config", str(_config(tmp_path))])
    assert result.exit_code == 0
    assert "enforced" in result.output


def test_a_rejected_schema_fails_health_and_names_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapf.cli.commands import health as health_module
    from mapf.core.errors import InferenceStatusError

    class _Rejects(_StubProvider):
        def complete(self, **kwargs):  # type: ignore[no-untyped-def]
            raise InferenceStatusError(400, "cannot compile grammar with $ref")

    monkeypatch.setattr(health_module, "build_llm_provider", lambda s, cached=True: _Rejects())
    result = runner.invoke(app, ["health", "--config", str(_config(tmp_path))])
    assert result.exit_code == EXIT_INFERENCE
    assert "Flatten the schema" in result.output


def test_the_probe_is_skippable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It costs a model load; `map health` stays fast when you only want the list."""
    from mapf.cli.commands import health as health_module

    provider = _StubProvider()
    monkeypatch.setattr(health_module, "build_llm_provider", lambda s, cached=True: provider)
    result = runner.invoke(
        app, ["health", "--no-grammar-probe", "--config", str(_config(tmp_path))]
    )
    assert result.exit_code == 0
    assert "grammar:" not in result.output
    assert provider.calls == 0


def test_health_never_reads_through_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A health check that passes from a cached reply, while the server is down,
    is worse than none."""
    from mapf.cli.commands import health as health_module

    seen: list[bool] = []

    def _capture(settings, *, fixtures=None, cached=True):  # type: ignore[no-untyped-def]
        seen.append(cached)
        return _StubProvider()

    monkeypatch.setattr(health_module, "build_llm_provider", _capture)
    runner.invoke(app, ["health", "--no-grammar-probe", "--config", str(_config(tmp_path))])
    assert seen == [False]


# ---------------------------------------------------------------------------
# Display fidelity — the terminal must not misrepresent the artifact
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        (0.05, "+0.05"),  # the regression: `:+.1f` printed this as "+0.1"
        (0.0, "+0"),
        (-0.1, "-0.1"),
        (4.5, "+4.5"),
        (-8.2, "-8.2"),
        (0.049, "+0.049"),
        (12.345, "+12.35"),
    ],
)
def test_a_forecast_number_is_shown_as_it_is_stored(stored: float, shown: str) -> None:
    from mapf.cli.app import as_shown

    assert as_shown(stored) == shown


def test_the_display_never_changes_a_value_by_more_than_a_rounding_hair() -> None:
    """The failure that mattered was a doubling, not a lost digit. Re-parsing what
    the terminal printed must land back on the stored number."""
    from mapf.cli.app import as_shown

    for stored in (0.05, 0.049, -0.1, 4.5, -8.2, 0.0, 999.9, -99.99):
        reparsed = float(as_shown(stored))
        assert reparsed == pytest.approx(stored, rel=1e-3, abs=1e-9)


def test_two_distinguishable_forecasts_do_not_display_identically() -> None:
    """`:+.1f` collapsed 0.05 and 0.14 to the same string. That is how a
    degenerate spread reads as a merely small one."""
    from mapf.cli.app import as_shown

    assert as_shown(0.05) != as_shown(0.14)
    assert as_shown(0.0) != as_shown(0.05)
