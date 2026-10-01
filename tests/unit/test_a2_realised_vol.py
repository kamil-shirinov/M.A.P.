"""Experiment A2: the analyst may be shown the stock's trailing realised volatility.

Built and not run (ADR 0042). Every test here is offline and uses recorded or scripted
responses: no model is called, no price is fetched. The two properties that matter
most are the ones the frozen system depends on: with the switch OFF nothing changes,
down to the template's hash; and with it ON, the figure is the random-walk baseline's
own volatility and could not have been built from a bar the forecast had not yet seen.
"""

from __future__ import annotations

import difflib
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mapf.agents.analyst import REALISED_VOL_TEMPLATE, AnalystAgent, AnalystRequest
from mapf.agents.intake import IntakeAgent
from mapf.agents.structuralist import StructuralistAgent
from mapf.bootstrap import build_run
from mapf.core.errors import (
    AnalystInputError,
    InsufficientVolatilityHistoryError,
)
from mapf.core.hashing import new_run_id
from mapf.core.models import Bar, MaterialFacts, PriceWindow, UntrustedText
from mapf.core.ports import LLMResponse, ModelInfo, RenderedPrompt, SamplingParams
from mapf.core.quarantine import quarantine
from mapf.pipeline.run import Agents, RunRequest, execute
from mapf.pipeline.trace import CountingTrace, JsonlTrace
from mapf.prompts.loader import FilePromptStore
from mapf.providers.fake import FakeProvider
from mapf.settings import load
from tests.integration.test_definition_of_done import (
    MODELS,
    NARRATIVE,
    SCENARIOS,
    KnownDividends,
    _documents,
)
from tests.unit.test_cli import _config

REPO_ROOT = Path(__file__).parents[2]
PROMPTS = REPO_ROOT / "src" / "mapf" / "prompts"
TICKER = "AAPL"
AS_OF_DATE = date(2026, 8, 10)
RUN_AT = datetime(2026, 8, 11, 14, 3, tzinfo=UTC)  # 10:03 in New York: the 10th is settled


def _closes(count: int = 140, *, last_jump: float = 0.0) -> list[float]:
    """A deterministic series that actually moves, optionally with a final-bar jump."""
    closes = [100.0]
    for index in range(1, count):
        closes.append(closes[-1] * math.exp(0.012 * math.sin(1.3 * index) + 0.003))
    closes[-1] *= math.exp(last_jump)
    return closes


def _window(closes: list[float]) -> PriceWindow:
    first = AS_OF_DATE - timedelta(days=len(closes) - 1)
    return PriceWindow(
        ticker=TICKER,
        provider="yfinance",
        adjustment="split_adjusted",
        bars=tuple(
            Bar(
                date=first + timedelta(days=index),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1_000,
            )
            for index, close in enumerate(closes)
        ),
    )


def _by_hand(closes: list[float]) -> float:
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False)]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


# ---------------------------------------------------------------------------
# The agent and its template
# ---------------------------------------------------------------------------
AGENT_MODEL = ModelInfo(id="gemma", fingerprint="fp", fingerprint_source="digest")


class _Scripted:
    def __init__(self) -> None:
        self.prompts: list[RenderedPrompt] = []

    def list_models(self) -> tuple[ModelInfo, ...]:
        return (AGENT_MODEL,)

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Any = None,
        attempt: int = 0,
    ) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(text=NARRATIVE, model_id=model.id)


class _Trace:
    def record(self, **_: object) -> None:
        return None


def _agent(provider: _Scripted, **kwargs: object) -> AnalystAgent:
    return AnalystAgent(
        provider=provider,
        model=AGENT_MODEL,
        sampling=SamplingParams(temperature=0.7, seed=1),
        prompts=FilePromptStore(),
        trace=_Trace(),
        stage="analyst",
        **kwargs,  # type: ignore[arg-type]
    )


def _request(realised_vol: float | None = None) -> AnalystRequest:
    return AnalystRequest(
        ticker=TICKER,
        as_of_date=AS_OF_DATE,
        horizon_days=5,
        facts=MaterialFacts(
            ticker=TICKER,
            facts=(UntrustedText("Revenue rose 8%."),),
            source_doc_ids=("sha256:" + "a" * 64,),
        ),
        realised_vol=realised_vol,
    )


def test_off_the_frozen_prompt_is_byte_identical_and_its_hash_is_the_frozens() -> None:
    """The point of the switch being off. The prompt the agent sends is exactly what
    the store renders for v3 with the three slots and the facts, and v3's hash is the
    one `corpus/frozen.json` recorded: every cache key the corpus produced still
    matches."""
    provider = _Scripted()
    _agent(provider, version="v3").run(_request())
    sent = provider.prompts[0]

    expected = FilePromptStore().render(
        "scenario_analyst",
        "v3",
        trusted={
            "ticker": TICKER,  # type: ignore[dict-item]
            "as_of_date": AS_OF_DATE.isoformat(),  # type: ignore[dict-item]
            "horizon_days": "5",  # type: ignore[dict-item]
        },
        untrusted={"material_facts": quarantine("Revenue rose 8%.")},
    )
    assert sent.messages == expected.messages
    assert sent.template_name == "scenario_analyst"
    frozen = json.loads((REPO_ROOT / "corpus" / "frozen.json").read_text(encoding="utf-8"))
    assert sent.template_sha256 == frozen["prompts"]["analyst"]["sha256"]
    assert "realised" not in " ".join(m.content for m in sent.messages).lower()


def test_a_frozen_agent_does_not_take_a_realised_volatility() -> None:
    assert _agent(_Scripted()).takes_realised_vol is False


def test_off_a_supplied_volatility_is_refused_rather_than_dropped() -> None:
    """A figure handed to a template with no slot for it would vanish, and the run
    would be counted as one that had seen it."""
    provider = _Scripted()
    with pytest.raises(AnalystInputError, match="no slot for a realised volatility"):
        _agent(provider, version="v3").run(_request(realised_vol=0.31))
    assert provider.prompts == []


def test_on_the_figure_reaches_the_user_message_to_two_places_and_only_there() -> None:
    provider = _Scripted()
    agent = _agent(provider, template=REALISED_VOL_TEMPLATE, version="v1")
    assert agent.takes_realised_vol is True
    agent.run(_request(realised_vol=0.3149))

    sent = provider.prompts[0]
    system, user = (m.content for m in sent.messages)
    assert (sent.template_name, sent.template_version) == (REALISED_VOL_TEMPLATE, "v1")
    assert f"Trailing realised volatility of {TICKER}: 0.31 (annualised" in user
    assert "0.31" not in system
    assert "{{" not in system + user


def test_on_without_a_figure_it_will_not_run_as_the_control() -> None:
    provider = _Scripted()
    with pytest.raises(AnalystInputError, match="needs a realised volatility"):
        _agent(provider, template=REALISED_VOL_TEMPLATE, version="v1").run(_request())
    assert provider.prompts == []


def test_the_new_template_differs_from_v3_by_exactly_the_two_registered_lines() -> None:
    """The prompt confound, pinned. ADR 0042 reproduces this diff; a change to either
    template that moved anything else would fail here rather than in a result."""
    v3 = (PROMPTS / "scenario_analyst.v3.md").read_text(encoding="utf-8").splitlines()
    vol = (PROMPTS / "scenario_analyst_vol.v1.md").read_text(encoding="utf-8").splitlines()
    changes = [line for line in difflib.unified_diff(v3, vol, lineterm="", n=0) if line[:1] in "+-"]
    removed = [line for line in changes if line.startswith("-") and not line.startswith("---")]
    added = [line for line in changes if line.startswith("+") and not line.startswith("+++")]
    assert len(removed) == 1 and len(added) == 2
    assert removed[0].endswith(
        "and nothing else. You may reason *from* those facts — that is the "
        "task — but you may not introduce new ones. Do not supply figures "
        "the material does not contain."
    )
    assert "the realised-volatility figure given with it, and nothing else" in added[0]
    assert added[1] == (
        "+Trailing realised volatility of {{ticker}}: {{realised_vol}} (annualised, from its "
        "daily closes before the date above; a measurement of the past, not a forecast)"
    )


@pytest.mark.parametrize("bad", [0.0, -0.2, math.nan, math.inf, 10.5])
def test_a_request_cannot_carry_a_volatility_that_is_not_one(bad: float) -> None:
    with pytest.raises(ValidationError):
        _request(realised_vol=bad)


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------
def test_the_shipped_config_has_it_off() -> None:
    settings = load([REPO_ROOT / "config" / "default.toml"])
    assert settings.experiments.analyst_realised_vol is False
    assert settings.prompts.analyst == "v3"  # the frozen analyst, untouched
    assert settings.prompts.analyst_realised_vol == "v1"


def test_an_environment_variable_can_turn_it_on_without_touching_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAP_EXPERIMENTS__ANALYST_REALISED_VOL", "true")
    assert load([_config(tmp_path)]).experiments.analyst_realised_vol is True


def test_an_unknown_experiment_switch_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "typo.toml"
    path.write_text(
        _config(tmp_path).read_text(encoding="utf-8") + "\n[experiments]\nanalyst_vol = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load([path])


def _wired(tmp_path: Path, *, on: bool) -> AnalystAgent:
    config = _config(tmp_path).read_text(encoding="utf-8")
    config += (
        f'\n[prompts]\nanalyst = "v3"\n[experiments]\nanalyst_realised_vol = {str(on).lower()}\n'
    )
    path = tmp_path / ("on.toml" if on else "off.toml")
    path.write_text(config, encoding="utf-8")
    wiring = build_run(
        load([path]),
        provider=FakeProvider(tmp_path),
        resolved=dict.fromkeys(("intake", "analyst", "structuralist"), AGENT_MODEL),
        run_id=new_run_id(),
    )
    return wiring.agents.analyst


def test_wired_off_the_analyst_is_the_frozen_one(tmp_path: Path) -> None:
    analyst = _wired(tmp_path, on=False)
    assert (analyst.template, analyst.version) == ("scenario_analyst", "v3")
    assert analyst.takes_realised_vol is False


def test_wired_on_the_template_and_its_version_change_together(tmp_path: Path) -> None:
    analyst = _wired(tmp_path, on=True)
    assert (analyst.template, analyst.version) == (REALISED_VOL_TEMPLATE, "v1")
    assert analyst.takes_realised_vol is True


# ---------------------------------------------------------------------------
# Through the pipeline
# ---------------------------------------------------------------------------
class _Pipeline:
    """Answers by stage, and keeps every analyst prompt it was shown."""

    def __init__(self) -> None:
        self.calls = 0
        self.analyst_prompts: list[RenderedPrompt] = []

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
            self.analyst_prompts.append(prompt)
            text = NARRATIVE
        else:
            text = SCENARIOS
        return LLMResponse(text=text, model_id=model.id)


class _Market:
    def __init__(self, closes: list[float]) -> None:
        self._window = _window(closes)

    @property
    def name(self) -> str:
        return "fixture"

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        return self._window


def _execute(
    tmp_path: Path, provider: _Pipeline, closes: list[float], *, takes_vol: bool, arm: str | None
) -> Any:
    runs = tmp_path / "runs"
    run_id = new_run_id()
    trace = CountingTrace(JsonlTrace(runs / str(run_id) / "trace.jsonl"))
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

    analyst_extra: dict[str, Any] = (
        {"template": REALISED_VOL_TEMPLATE, "version": "v1"} if takes_vol else {}
    )
    return execute(
        RunRequest(
            ticker=TICKER, horizon_days=5, documents=_documents(), run_id=run_id, as_of=RUN_AT
        ),
        agents=Agents(
            intake=IntakeAgent(**common("intake", 0.0)),
            analyst=AnalystAgent(**common("analyst", 0.7), **analyst_extra),
            structuralist=StructuralistAgent(**common("structuralist", 0.0), max_attempts=3),
        ),
        market=_Market(closes),
        dividends=KnownDividends(),
        trace=trace,
        runs_dir=runs,
        today=date(2026, 8, 11),
        render_chart=False,
        arm=arm,
    )


def _analyst_record(result: Any) -> Any:
    return next(record for record in result.manifest.agents if record.alias == "analyst")


def test_the_figure_shown_is_computed_from_closes_before_the_anchor_only(tmp_path: Path) -> None:
    """A 30% jump on the anchor bar itself must not reach the figure: the baseline's
    history stops strictly before it, and so does this."""
    closes = _closes(140, last_jump=0.30)
    provider = _Pipeline()
    result = _execute(tmp_path, provider, closes, takes_vol=True, arm="A2")

    expected = _by_hand(closes[:-1])
    assert abs(expected - _by_hand(closes)) > 0.05  # the jump would have been visible
    shown = provider.analyst_prompts[0].messages[-1].content
    assert f"{expected:.2f} (annualised" in shown
    assert f"{_by_hand(closes):.2f} (annualised" not in shown
    assert _analyst_record(result).template_name == REALISED_VOL_TEMPLATE
    assert result.manifest.arm == "A2"


def test_off_the_same_run_shows_no_figure_and_records_the_frozen_template(
    tmp_path: Path,
) -> None:
    provider = _Pipeline()
    result = _execute(tmp_path, provider, _closes(140), takes_vol=False, arm=None)
    shown = " ".join(m.content for m in provider.analyst_prompts[0].messages)
    assert "realised volatility" not in shown.lower().replace("realised-volatility", "")
    assert _analyst_record(result).template_name == "scenario_analyst"
    assert result.manifest.arm is None


def test_an_experiment_run_without_an_arm_label_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    """The loophole this closes: the corpus runner verifies the frozen templates'
    hashes and would pass with the switch on, writing A2 forecasts into the ledger
    as if they were the frozen system's."""
    provider = _Pipeline()
    with pytest.raises(AnalystInputError, match="arm label"):
        _execute(tmp_path, provider, _closes(140), takes_vol=True, arm=None)
    assert provider.calls == 0


def test_a_window_too_short_for_a_volatility_fails_before_any_model_runs(
    tmp_path: Path,
) -> None:
    """Never run without the figure and count the item as an A2 one."""
    provider = _Pipeline()
    with pytest.raises(InsufficientVolatilityHistoryError):
        _execute(tmp_path, provider, _closes(30), takes_vol=True, arm="A2")
    assert provider.calls == 0
