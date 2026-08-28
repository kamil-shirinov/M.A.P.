"""Every agent's output must fit the next agent's input window.

Agents were validated in isolation and the chain between them against nothing.
Intake then emitted ~20,000 tokens from a 12,500-token document — it expanded
rather than compressed — and the analyst rejected a 22,368-token prompt against its
16,384 window. Both agents were individually valid; the pipeline was not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapf.core.errors import ChainBudgetError, PromptTooLargeError
from mapf.core.ports import Message, RenderedPrompt, SamplingParams
from mapf.core.tokens import (
    PROMPT_OVERHEAD,
    generation_reserve,
    prompt_allowance,
)
from mapf.settings import load


def _prompt(chars: int) -> RenderedPrompt:
    return RenderedPrompt(
        template_name="t",
        template_version="v1",
        template_sha256="0" * 64,
        messages=(Message(role="user", content="x" * chars),),
    )


# ---------------------------------------------------------------------------
# The shipped configuration satisfies the chain
# ---------------------------------------------------------------------------
def test_intake_output_fits_the_analyst_window() -> None:
    s = load()
    produced = s.models.intake.visible_budget
    assert produced is not None
    allowance = prompt_allowance(
        s.models.analyst.context_tokens, s.models.analyst.max_tokens
    )
    assert produced + PROMPT_OVERHEAD["analyst"] <= allowance


def test_analyst_visible_output_fits_the_structuralist_window() -> None:
    """Its 12,000-token budget is mostly reasoning that never leaves the model, so
    the bound that matters is what actually crosses the boundary."""
    s = load()
    produced = s.models.analyst.visible_budget
    assert produced is not None
    allowance = prompt_allowance(
        s.models.structuralist.context_tokens, s.models.structuralist.max_tokens
    )
    assert produced + PROMPT_OVERHEAD["structuralist"] <= allowance


def test_intake_is_capped_at_all() -> None:
    """Uncapped output is what let intake expand a document instead of compressing
    it. Nothing bounded what it could emit."""
    assert load().models.intake.max_tokens is not None


def test_the_cap_is_far_above_anything_observed() -> None:
    """Largest intake output ever recorded is 368 tokens; a cap near that would
    truncate ordinary work to prevent a pathological case."""
    cap = load().models.intake.max_tokens
    assert cap is not None
    assert cap >= 368 * 5


# ---------------------------------------------------------------------------
# The validator rejects a broken chain
# ---------------------------------------------------------------------------
def _toml(tmp_path: Path, intake_max: int, analyst_ctx: int = 16384) -> Path:
    body = f"""
[inference]
base_url = "http://127.0.0.1:9/v1"
connect_timeout_s = 1.0
read_timeout_s = 1300.0
max_repair_attempts = 3
min_tokens_per_second = 16.0

[models.intake]
alias = "a"
temperature = 0.0
context_tokens = 32768
max_tokens = {intake_max}

[models.analyst]
alias = "b"
temperature = 0.0
context_tokens = {analyst_ctx}
max_tokens = 12000
max_visible_tokens = 2048

[models.structuralist]
alias = "c"
temperature = 0.0
context_tokens = 8192

[cache]
llm_dir = "{tmp_path / "llm"}"
price_dir = "{tmp_path / "p"}"

[data]
provider_order = ["yfinance"]
adjustment = "split_adjusted"
history_days = 730

[data.sec]
user_agent = "T t@e.com"
requests_per_second = 8.0
tickers_url = "https://example.test/t.json"
symbols_db = "{tmp_path / "s.sqlite"}"
refresh_days = 30

[news]
dir = "{tmp_path / "news"}"
rss_urls = []

[paths]
runs_dir = "{tmp_path / "runs"}"
"""
    path = tmp_path / "c.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_an_output_too_large_for_the_next_window_is_rejected(tmp_path: Path) -> None:
    """The STZ failure, caught at startup instead of on item two."""
    with pytest.raises(ChainBudgetError) as caught:
        load([_toml(tmp_path, intake_max=20000)])
    message = str(caught.value)
    assert "intake may emit 20,000" in message
    assert "analyst can accept only" in message


def test_the_error_names_both_agents(tmp_path: Path) -> None:
    with pytest.raises(ChainBudgetError) as caught:
        load([_toml(tmp_path, intake_max=20000)])
    assert caught.value.upstream == "intake"
    assert caught.value.downstream == "analyst"


def test_a_chain_that_fits_is_accepted(tmp_path: Path) -> None:
    settings = load([_toml(tmp_path, intake_max=2048)])
    assert settings.models.intake.max_tokens == 2048


def test_raising_the_downstream_window_also_resolves_it(tmp_path: Path) -> None:
    """Two ways out, and the error names both. 8,000 is over the 2,848 the analyst
    can take at 16,384 and comfortably inside what it can take at 65,536."""
    with pytest.raises(ChainBudgetError):
        load([_toml(tmp_path, intake_max=8000)])
    settings = load([_toml(tmp_path, intake_max=8000, analyst_ctx=65536)])
    assert settings.models.analyst.context_tokens == 65536


def test_an_unbounded_output_is_skipped_rather_than_assumed_safe(tmp_path: Path) -> None:
    """It cannot be checked at startup, so the pre-dispatch assertion carries it."""
    body = (tmp_path / "c.toml")
    load([_toml(tmp_path, intake_max=2048)])
    text = body.read_text().replace("max_tokens = 2048\n", "")
    body.write_text(text, encoding="utf-8")
    assert load([body]).models.intake.max_tokens is None


# ---------------------------------------------------------------------------
# The pre-dispatch assertion
# ---------------------------------------------------------------------------
class _Agent:
    """Minimal stand-in exercising only the size guard."""

    def __init__(
        self, context_tokens: int, max_tokens: int | None, upstream: str | None
    ) -> None:
        from mapf.agents.base import LLMAgent

        self._guard = LLMAgent.__dict__["_assert_fits"]
        self._stage = "analyst"
        self._upstream = upstream
        self._context_tokens: int | None = context_tokens
        self._sampling = SamplingParams(temperature=0.0, max_tokens=max_tokens)

    def check(self, prompt: RenderedPrompt) -> None:
        self._guard(self, prompt)


def test_an_oversized_prompt_is_refused_before_dispatch() -> None:
    agent = _Agent(context_tokens=16384, max_tokens=12000, upstream="intake")
    with pytest.raises(PromptTooLargeError) as caught:
        agent.check(_prompt(120_000))
    assert caught.value.agent == "analyst"
    assert caught.value.upstream == "intake"


def test_the_refusal_names_the_agent_that_produced_the_payload() -> None:
    """A raw HTTP 400 says only that something did not fit."""
    agent = _Agent(context_tokens=16384, max_tokens=12000, upstream="intake")
    with pytest.raises(PromptTooLargeError) as caught:
        agent.check(_prompt(120_000))
    message = str(caught.value)
    assert "produced by intake" in message
    assert "Refused before dispatch" in message


def test_a_prompt_within_the_allowance_passes() -> None:
    agent = _Agent(context_tokens=16384, max_tokens=12000, upstream="intake")
    agent.check(_prompt(4_000))


def test_the_allowance_subtracts_the_generation_budget() -> None:
    """Generation shares the window with the prompt."""
    assert prompt_allowance(16384, 12000) == 4384
    assert prompt_allowance(8192, None) == 8192 - generation_reserve(None)


def test_an_agent_without_a_declared_window_is_not_guarded() -> None:
    """Older wiring passes no window; the guard must not invent one."""
    agent = _Agent(context_tokens=16384, max_tokens=12000, upstream=None)
    agent._context_tokens = None
    agent.check(_prompt(400_000))


def test_the_stz_payload_would_have_been_refused() -> None:
    """22,368 tokens against a 4,384 allowance — the failure that stopped the run."""
    agent = _Agent(context_tokens=16384, max_tokens=12000, upstream="intake")
    with pytest.raises(PromptTooLargeError) as caught:
        agent.check(_prompt(22_368 * 4))
    assert caught.value.tokens > 20_000
    assert caught.value.allowance == 4_384
