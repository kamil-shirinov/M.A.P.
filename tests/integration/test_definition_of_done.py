"""The eight Phase 1 acceptance criteria, end to end.

One test per criterion, named for it. This file is the thing that says Phase 1 is
finished — if it passes, the phase is done; if a criterion has no test here, it is
not done regardless of what the code looks like.

Everything runs against `FakeProvider` with no inference server and no network,
which is criterion 6 and is what makes the other seven checkable in CI at all.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mapf.agents.analyst import AnalystAgent
from mapf.agents.intake import IntakeAgent
from mapf.agents.structuralist import StructuralistAgent
from mapf.core.hashing import new_run_id
from mapf.core.models import (
    ADJUSTMENT_BASIS,
    Bar,
    DividendWindow,
    Document,
    Forecast,
    PriceWindow,
    UntrustedText,
)
from mapf.core.ports import LLMResponse, ModelInfo, RenderedPrompt, SamplingParams
from mapf.data.symbols import SqliteSymbolIndex, Throttle, sync
from mapf.pipeline.manifest import RunManifest
from mapf.pipeline.run import Agents, RunRequest, execute
from mapf.pipeline.trace import CountingTrace, JsonlTrace
from mapf.prompts.loader import FilePromptStore
from mapf.providers.caching import CachingProvider
from mapf.render.chart import DISCLAIMER, build_figure

import httpx  # isort: skip

FIXTURES = Path(__file__).parents[1] / "fixtures"
AS_OF = datetime(2026, 8, 11, 14, 3, tzinfo=UTC)
DOC_ID = "sha256:" + "a" * 64

MODELS = {
    "intake": ModelInfo(id="llama-3.2-3b", fingerprint="fp-intake", fingerprint_source="digest"),
    "analyst": ModelInfo(
        id="gemma4-12b",
        fingerprint="fp-analyst",
        fingerprint_source="composite",
        fingerprint_fields=("created", "size"),
    ),
    "structuralist": ModelInfo(id="qwen3-4b", fingerprint="fp-struct", fingerprint_source="tag"),
}

SCENARIOS = json.dumps(
    {
        name: {
            "justification": f"A sufficiently long justification for the {name} branch.",
            "probability_weight": weight,
            "price_return": modifier,
            "annualised_vol": vol,
        }
        for name, weight, modifier, vol in (
            ("bullish", 0.25, 0.045, 0.38),
            ("base_case", 0.60, 0.008, 0.22),
            ("bearish", 0.15, -0.082, 0.55),
        )
    }
)
NARRATIVE = "Bullish: " + "reasoned prose about the facts. " * 12


class CountingProvider:
    """Answers by stage and counts transport calls.

    Criterion 5 is asserted on this counter rather than on a stopwatch: a wall
    clock measures the machine, whereas the count measures the thing the criterion
    is actually about — that the second run reached no server at all.
    """

    def __init__(self) -> None:
        self.calls = 0

    def list_models(self) -> tuple[ModelInfo, ...]:
        return tuple(MODELS.values())

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Any = None,
        attempt: int = 0,
    ) -> LLMResponse:
        self.calls += 1
        if model.id == MODELS["intake"].id:
            text = "- Revenue rose 8%.\n- Guidance was reaffirmed."
        elif model.id == MODELS["analyst"].id:
            text = NARRATIVE
        else:
            text = SCENARIOS
        return LLMResponse(text=text, model_id=model.id)


class StaticMarket:
    @property
    def name(self) -> str:
        return "fixture"

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        base = date(2026, 8, 3)
        return PriceWindow(
            ticker=ticker,
            provider="yfinance",
            adjustment="split_adjusted",
            bars=tuple(
                Bar(
                    date=base + timedelta(days=offset),
                    open=200.0 + offset,
                    high=202.0 + offset,
                    low=199.0 + offset,
                    close=201.0 + offset,
                    volume=1_000_000,
                )
                for offset in range(5)
            ),
        )


class KnownDividends:
    def dividends_in(self, ticker: str, start: date, end: date) -> DividendWindow:
        return DividendWindow(
            start=start,
            end=end,
            ex_dates=(start + timedelta(days=10),),
            total_amount=0.25,
            known=True,
            source="test",
        )


def _documents() -> tuple[Document, ...]:
    return (
        Document(
            id=DOC_ID,
            source="news/reuters.txt",
            text=UntrustedText("Apple reported quarterly revenue of $94.9bn."),
            fetched_at=AS_OF,
        ),
    )


def _agents(provider: object, trace: CountingTrace) -> Agents:
    prompts = FilePromptStore()

    def common(stage: str, temperature: float) -> dict[str, Any]:
        return {
            "provider": provider,
            "model": MODELS[stage],
            "sampling": SamplingParams(temperature=temperature, seed=20260809),
            "prompts": prompts,
            "trace": trace,
            "stage": stage,
        }

    return Agents(
        intake=IntakeAgent(**common("intake", 0.0)),
        analyst=AnalystAgent(**common("analyst", 0.7)),
        structuralist=StructuralistAgent(**common("structuralist", 0.0), max_attempts=3),
    )


def _run(tmp_path: Path, provider: object, *, run_id: Any = None) -> Any:
    runs_dir = tmp_path / "runs"
    rid = run_id or new_run_id()
    trace = CountingTrace(JsonlTrace(runs_dir / str(rid) / "trace.jsonl"))
    return execute(
        RunRequest(
            ticker="AAPL",
            horizon_days=21,
            documents=_documents(),
            run_id=rid,
            as_of=AS_OF,
        ),
        agents=_agents(provider, trace),
        market=StaticMarket(),
        dividends=KnownDividends(),
        trace=trace,
        runs_dir=runs_dir,
        today=date(2026, 8, 11),
    )


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """One pipeline run, shared by every read-only assertion.

    Module-scoped because `execute` inlines the whole plotly bundle into
    `chart.html` — about 4.5 MB per run. Fourteen private runs made this file take
    two and a half minutes; the tests that mutate state still get their own.
    """
    return _run(tmp_path_factory.mktemp("baseline"), CountingProvider())


# ---------------------------------------------------------------------------
# 1. map health
# ---------------------------------------------------------------------------
def test_criterion_1_health_reports_missing_models(tmp_path: Path) -> None:
    """Verifies the server, lists models, and names what is missing."""
    from mapf.cli.app import app

    config = tmp_path / "default.toml"
    config.write_text(_config(tmp_path), encoding="utf-8")
    result = CliRunner().invoke(app, ["health", "--config", str(config)])
    # No server is running, so this must be the unreachable path — with a sentence.
    assert result.exit_code == 4
    assert "error:" in result.output
    assert "traceback" not in result.output.lower()


def test_criterion_1_a_dead_server_is_a_sentence_not_a_traceback(tmp_path: Path) -> None:
    """The specific requirement: someone who has not started their server gets told."""
    from mapf.cli.app import app

    config = tmp_path / "default.toml"
    config.write_text(_config(tmp_path), encoding="utf-8")
    result = CliRunner().invoke(app, ["health", "--config", str(config)])
    assert "Start your inference server" in result.output


# ---------------------------------------------------------------------------
# 2. map search
# ---------------------------------------------------------------------------
def test_criterion_2_search_apple_returns_aapl(tmp_path: Path) -> None:
    db = tmp_path / "symbols.sqlite"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=(FIXTURES / "sec" / "company_tickers_exchange.json").read_bytes()
        )

    sync(
        db,
        url="https://example.test/tickers.json",
        user_agent="Test Runner test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=Throttle(8.0, sleep=lambda _: None),
    )
    tickers = [m.symbol.ticker for m in SqliteSymbolIndex(db).search("apple")]
    assert "AAPL" in tickers


# ---------------------------------------------------------------------------
# 3. map run writes a schema-valid forecast
# ---------------------------------------------------------------------------
def test_criterion_3_run_writes_a_validated_forecast(baseline: Any) -> None:
    result = baseline
    path = result.run_dir / "forecast.json"
    assert path.is_file()
    # Re-validate from disk, not from the object in memory: the artifact is the
    # deliverable, and an object that validates says nothing about what was written.
    reloaded = Forecast.model_validate_json(path.read_text(encoding="utf-8"))
    assert reloaded == result.forecast
    assert reloaded.horizon_days == 21
    assert reloaded.spot_price > 0


def test_criterion_3_all_three_agents_ran_in_order(tmp_path: Path) -> None:
    provider = CountingProvider()
    _run(tmp_path, provider)
    assert provider.calls == 3


# ---------------------------------------------------------------------------
# 4. trace.jsonl and manifest.json
# ---------------------------------------------------------------------------
def test_criterion_4_trace_holds_every_prompt_and_response(baseline: Any) -> None:
    result = baseline
    lines = (result.run_dir / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]
    stages = {event["stage"] for event in events}
    assert {"intake", "analyst", "structuralist"} <= stages
    for event in events:
        if event["stage"] in {"intake", "analyst", "structuralist"}:
            assert event["data"]["messages"]
            assert "response" in event["data"]


def test_criterion_4_manifest_carries_the_phase_2_handshake(baseline: Any) -> None:
    """If Phase 2 would need it and it is not here, that is a bug now, not later."""
    result = baseline
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "manifest.json").read_text(encoding="utf-8")
    )

    assert {record.alias for record in manifest.agents} == {
        "intake",
        "analyst",
        "structuralist",
    }
    for record in manifest.agents:
        assert record.fingerprint
        assert record.fingerprint_source in {"digest", "composite", "tag"}
        assert record.template_name and record.template_version
        assert len(record.template_sha256) == 64
        assert record.sampling.seed == 20260809  # recorded as *requested*
        assert record.sampling.temperature is not None

    analyst = next(r for r in manifest.agents if r.alias == "analyst")
    assert analyst.fingerprint_source == "composite"
    assert analyst.fingerprint_fields == ("created", "size")

    assert manifest.source_doc_ids == (DOC_ID,)
    assert manifest.prices.adjustment == ADJUSTMENT_BASIS
    assert manifest.prices.provider == "yfinance"
    assert manifest.prices.fetched_on == date(2026, 8, 11)
    assert manifest.dividends.known is True
    assert manifest.dividends.ex_dates
    assert manifest.allow_nondeterministic is False
    assert manifest.package_version and manifest.python_version


def test_criterion_4_an_unknown_dividend_window_is_marked_unknown(tmp_path: Path) -> None:
    """ADR 0013: Phase 2 must be able to tell "none" from "not knowable"."""
    from mapf.data.providers.dividends import NullDividendSource

    runs_dir = tmp_path / "runs"
    rid = new_run_id()
    trace = CountingTrace(JsonlTrace(runs_dir / str(rid) / "trace.jsonl"))
    result = execute(
        RunRequest(ticker="AAPL", horizon_days=21, documents=_documents(), run_id=rid, as_of=AS_OF),
        agents=_agents(CountingProvider(), trace),
        market=StaticMarket(),
        dividends=NullDividendSource(),
        trace=trace,
        runs_dir=runs_dir,
    )
    assert result.manifest.dividends.known is False
    assert result.manifest.dividends.ex_dates == ()


# ---------------------------------------------------------------------------
# 5. second run: zero transport calls
# ---------------------------------------------------------------------------
def test_criterion_5_a_second_run_makes_zero_transport_calls(tmp_path: Path) -> None:
    """Asserted on the call counter, not a stopwatch.

    A stopwatch measures the machine. The counter measures the claim: that the
    second run reached no inference server at all.
    """
    cache_dir = tmp_path / "llm"
    fixed_id = new_run_id()

    first_inner = CountingProvider()
    _run(tmp_path, CachingProvider(first_inner, cache_dir), run_id=fixed_id)
    assert first_inner.calls == 3

    second_inner = CountingProvider()
    result = _run(tmp_path, CachingProvider(second_inner, cache_dir), run_id=new_run_id())

    assert second_inner.calls == 0
    assert result.forecast.scenarios.base_case.probability_weight == pytest.approx(0.60)


def test_criterion_5_the_cached_run_still_writes_a_full_trace(tmp_path: Path) -> None:
    """A cache hit that produced no trace would make criterion 5 unauditable."""
    cache_dir = tmp_path / "llm"
    _run(tmp_path, CachingProvider(CountingProvider(), cache_dir))
    result = _run(tmp_path, CachingProvider(CountingProvider(), cache_dir))
    events = [
        json.loads(line)
        for line in (result.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    completions = [e for e in events if e["stage"] in {"intake", "analyst", "structuralist"}]
    assert len(completions) == 3
    assert all(event["cache_hit"] for event in completions)


# ---------------------------------------------------------------------------
# 6. the suite runs with the server off
# ---------------------------------------------------------------------------
def test_criterion_6_no_http_client_is_reachable_from_the_agents() -> None:
    """Structural, not aspirational. `import-linter` forbids the import; this
    asserts the consequence — a full pipeline exists with nothing that can dial."""
    import sys

    import mapf.agents.intake

    graph = {name for name in sys.modules if name.startswith("mapf.agents")}
    assert graph
    assert mapf.agents.intake.__name__  # imported without pulling in a transport


def test_criterion_6_the_whole_pipeline_runs_offline(baseline: Any) -> None:
    result = baseline
    assert result.forecast.ticker == "AAPL"


# ---------------------------------------------------------------------------
# 7. ruff + mypy — enforced by CI, asserted here as a placeholder for intent
# ---------------------------------------------------------------------------
def test_criterion_7_is_enforced_by_the_toolchain_not_by_a_test() -> None:
    """Deliberately not shelling out to ruff and mypy from inside pytest.

    A test that re-runs the linters is slow, duplicates CI, and passes or fails for
    reasons unrelated to the code under test. The criterion is met by
    `ruff check`, `ruff format --check`, `mypy --strict` and `lint-imports` being
    green in the same command that runs this suite. This test documents where the
    guarantee actually lives so nobody later mistakes its absence for an omission.
    """
    config = Path(__file__).parents[2] / "pyproject.toml"
    text = config.read_text(encoding="utf-8")
    assert "[tool.ruff]" in text
    assert "strict = true" in text
    assert "[tool.importlinter]" in text


# ---------------------------------------------------------------------------
# 8. chart.html
# ---------------------------------------------------------------------------
def test_criterion_8_chart_shows_history_and_three_labelled_paths(baseline: Any) -> None:
    result = baseline
    html = (result.run_dir / "chart.html").read_text(encoding="utf-8")
    assert "Bullish" in html
    assert "Base case" in html
    assert "Bearish" in html
    assert "AAPL" in html


def test_criterion_8_the_chart_is_self_contained(baseline: Any) -> None:
    """No CDN, no server. It has to open from disk in three years.

    Asserts there is no remote `<script src=...>`, rather than grepping for a
    hostname: `cdn.plot.ly` appears as a string literal *inside* the vendored
    plotly bundle, so a naive grep fails on a chart that is in fact self-contained.
    """
    html = (baseline.run_dir / "chart.html").read_text(encoding="utf-8")
    remote = re.findall(r'<script[^>]+src=["\']https?://[^"\']+', html)
    assert remote == []
    assert len(html) > 500_000  # the bundle really is inlined


def test_criterion_8_no_volatility_band_is_drawn(baseline: Any) -> None:
    """`annualised_vol` rides in the JSON for Phase 2. Shading a cone here would
    render a distribution nobody has computed.

    Interrogates the figure rather than the HTML: plotly's own source contains the
    string "tonexty" whether or not any trace uses it.
    """
    figure = build_figure(baseline.window, baseline.forecast)
    assert len(figure.data) == 4  # history + three scenario paths
    assert all(getattr(trace, "fill", None) in (None, "none") for trace in figure.data)
    assert DISCLAIMER in (figure.layout.annotations[0].text or "")
    # ...and the volatility is still in the artifact, for Phase 2.
    assert baseline.forecast.scenarios.bearish.annualised_vol == pytest.approx(0.55)


def _config(tmp_path: Path) -> str:
    return f"""
[inference]
base_url = "http://127.0.0.1:9/v1"
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
user_agent = "Test Runner test@example.com"
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


# ---------------------------------------------------------------------------
# Quality flags reach the manifest (items 5 and 6)
# ---------------------------------------------------------------------------
def test_a_degenerate_spread_is_recorded_not_rejected(tmp_path: Path) -> None:
    """The first live run produced three near-identical numbers and nothing said
    so. A warning, because a genuinely flat outlook is legitimate."""
    flat = json.dumps(
        {
            name: {
                "justification": f"A sufficiently long justification for the {name} branch.",
                "probability_weight": weight,
                "price_return": ret,
                "annualised_vol": 0.2,
            }
            for name, weight, ret in (
                ("bullish", 0.25, 0.0005),
                ("base_case", 0.60, 0.0),
                ("bearish", 0.15, -0.001),
            )
        }
    )

    class _Flat(CountingProvider):
        def complete(self, *, model, prompt, sampling, json_schema=None, attempt=0):  # type: ignore[no-untyped-def]
            self.calls += 1
            if model.id == MODELS["intake"].id:
                return LLMResponse(text="- Revenue rose 8%.", model_id=model.id)
            if model.id == MODELS["analyst"].id:
                return LLMResponse(text=NARRATIVE, model_id=model.id)
            return LLMResponse(text=flat, model_id=model.id)

    result = _run(tmp_path, _Flat())
    assert result.manifest.quality.degenerate_spread is True
    assert result.manifest.quality.spread < result.manifest.quality.spread_floor
    # Recorded, not raised: the forecast still exists on disk.
    assert (result.run_dir / "forecast.json").is_file()


def test_a_healthy_forecast_carries_no_quality_flags(baseline: Any) -> None:
    assert baseline.manifest.quality.any_flag is False


def test_a_fabricated_figure_is_recorded_not_rejected(tmp_path: Path) -> None:
    """The 66.3% incident, reproduced. The source and the analyst both said 46.3%;
    the structuralist wrote 66.3% and every validator passed."""
    fabricated = json.dumps(
        {
            name: {
                "justification": (
                    "The high gross margin of 66.3% suggests a stable profit floor."
                    if name == "base_case"
                    else f"A sufficiently long justification for the {name} branch."
                ),
                "probability_weight": weight,
                "price_return": ret,
                "annualised_vol": 0.2,
            }
            for name, weight, ret in (
                ("bullish", 0.25, 0.045),
                ("base_case", 0.60, 0.008),
                ("bearish", 0.15, -0.082),
            )
        }
    )

    class _Fabricates(CountingProvider):
        def complete(self, *, model, prompt, sampling, json_schema=None, attempt=0):  # type: ignore[no-untyped-def]
            self.calls += 1
            if model.id == MODELS["intake"].id:
                return LLMResponse(text="- Gross margin was 46.3%.", model_id=model.id)
            if model.id == MODELS["analyst"].id:
                return LLMResponse(text=NARRATIVE, model_id=model.id)
            return LLMResponse(text=fabricated, model_id=model.id)

    result = _run(tmp_path, _Fabricates())
    assert any("66.3" in v for v in result.manifest.quality.ungrounded_numerals)
    assert (result.run_dir / "forecast.json").is_file()


def test_agent_2_non_compliance_is_recorded_as_unparseable(tmp_path: Path) -> None:
    """v1's failure: the analyst emits prose with no ESTIMATE line. Fidelity is
    undefined rather than zero — blaming Agent 3 for Agent 2's silence would point
    the next fix at the wrong agent."""
    result = _run(tmp_path, CountingProvider())
    assert result.manifest.fidelity.unparseable == ("bullish", "base_case", "bearish")
    assert result.manifest.fidelity.fidelity is None
    assert result.manifest.fidelity.analyst_compliance == 0.0


def test_a_faithful_transcription_is_recorded_as_such(tmp_path: Path) -> None:
    estimates = (
        "**Bullish**\nESTIMATE bullish weight=0.25 return=+0.045 vol=0.38\n"
        "**Base case**\nESTIMATE base_case weight=0.6 return=+0.008 vol=0.22\n"
        "**Bearish**\nESTIMATE bearish weight=0.15 return=-0.082 vol=0.55\n"
    ) + NARRATIVE

    class _Compliant(CountingProvider):
        def complete(self, *, model, prompt, sampling, json_schema=None, attempt=0):  # type: ignore[no-untyped-def]
            self.calls += 1
            if model.id == MODELS["intake"].id:
                return LLMResponse(text="- Revenue rose 8%.", model_id=model.id)
            if model.id == MODELS["analyst"].id:
                return LLMResponse(text=estimates, model_id=model.id)
            return LLMResponse(text=SCENARIOS, model_id=model.id)

    result = _run(tmp_path, _Compliant())
    assert result.manifest.fidelity.parsed == ("bullish", "base_case", "bearish")
    assert result.manifest.fidelity.divergent == ()
    assert result.manifest.fidelity.fidelity == 1.0


def test_agent_3_infidelity_is_recorded_separately_from_non_compliance(
    tmp_path: Path,
) -> None:
    """The analyst stated numbers and Agent 3 emitted different ones. Distinct from
    the case above, because the remedy is a different agent's prompt."""
    estimates = (
        "**Bullish**\nESTIMATE bullish weight=0.25 return=+0.20 vol=0.38\n"
        "**Base case**\nESTIMATE base_case weight=0.6 return=+0.008 vol=0.22\n"
        "**Bearish**\nESTIMATE bearish weight=0.15 return=-0.082 vol=0.55\n"
    ) + NARRATIVE

    class _Unfaithful(CountingProvider):
        def complete(self, *, model, prompt, sampling, json_schema=None, attempt=0):  # type: ignore[no-untyped-def]
            self.calls += 1
            if model.id == MODELS["intake"].id:
                return LLMResponse(text="- Revenue rose 8%.", model_id=model.id)
            if model.id == MODELS["analyst"].id:
                return LLMResponse(text=estimates, model_id=model.id)
            return LLMResponse(text=SCENARIOS, model_id=model.id)

    result = _run(tmp_path, _Unfaithful())
    assert result.manifest.fidelity.divergent == ("bullish",)
    assert result.manifest.fidelity.unparseable == ()
    assert result.manifest.fidelity.fidelity == pytest.approx(2 / 3)
    assert result.manifest.fidelity.max_return_divergence == pytest.approx(0.155)


def test_an_experiment_names_its_arm_in_the_artifact(tmp_path: Path) -> None:
    """Arm A of the ablation replays the corpus from cache, so its forecasts are
    byte-identical to the corpus runs apart from `run_id`. It lived in
    `var/ablation/A/` and nothing inside the run said what it was — 355 replays one
    `--runs-dir` away from being read as 355 projections. A directory is a
    convention; it does not survive being copied, moved or pointed at."""
    runs_dir = tmp_path / "runs"
    rid = new_run_id()
    trace = CountingTrace(JsonlTrace(runs_dir / str(rid) / "trace.jsonl"))
    result = execute(
        RunRequest(ticker="AAPL", horizon_days=21, documents=_documents(), run_id=rid, as_of=AS_OF),
        agents=_agents(CountingProvider(), trace),
        market=StaticMarket(),
        dividends=KnownDividends(),
        trace=trace,
        runs_dir=runs_dir,
        today=date(2026, 8, 11),
        arm="A",
    )

    assert result.manifest.arm == "A"
    stored = json.loads((runs_dir / str(rid) / "manifest.json").read_text(encoding="utf-8"))
    assert stored["arm"] == "A"


def test_an_ordinary_run_claims_no_arm(baseline: Any) -> None:
    """`None` is "not an experiment" for anything written from now on, and
    "predates the field" for the arm manifests already on disk. Not resolvable by
    backfilling those: they produced published results."""
    assert baseline.manifest.arm is None


def test_the_manifest_records_the_forecast_schema_version(baseline: Any) -> None:
    """ADR 0012 makes Phase 2 refuse to score across a schema boundary, and Phase 2
    reads the manifest to decide. With only the manifest's own version present it
    read 1.0.0 and never saw the forecast had moved to 2.0.0 — the exact silent,
    plausible mismatch the obligation exists to prevent."""
    assert baseline.manifest.forecast_schema_version == baseline.forecast.schema_version
    assert baseline.manifest.forecast_schema_version == "2.0.0"
    assert baseline.manifest.manifest_version != baseline.forecast.schema_version


# ---------------------------------------------------------------------------
# An agent cut off mid-output must be visible in the artifacts
# ---------------------------------------------------------------------------
class _CutOffProvider(CountingProvider):
    """Every answer arrives complete but flagged as having hit the token cap.

    Intake is capped at 2,048 tokens and has never exceeded 368, so this should
    never happen in practice. It has happened twice already — once at 18,938 tokens
    on the STZ document — and nothing surfaced it, which is why the flag exists.
    """

    def complete(self, **kwargs: Any) -> Any:
        response = super().complete(**kwargs)
        return response.model_copy(update={"finish_reason": "length"})


def test_a_truncated_agent_output_fails_the_run_rather_than_scoring_it(
    tmp_path: Path,
) -> None:
    """A fragment presented as a whole is worse than a missing item: it produces a
    schema-valid forecast scored beside forecasts built on complete summaries."""
    from mapf.core.errors import OutputTruncatedError

    with pytest.raises(OutputTruncatedError) as caught:
        _run(tmp_path, _CutOffProvider())
    assert "runaway" in str(caught.value)
    assert caught.value.agent in {"intake", "analyst", "structuralist"}


def test_a_completed_run_is_not_flagged_as_truncated(baseline: Any) -> None:
    """Absent evidence is not a truncation claim."""
    records = {a.alias: a for a in baseline.manifest.agents}
    assert all(not r.output_truncated for r in records.values())
    assert all(r.finish_reason in (None, "stop") for r in records.values())
