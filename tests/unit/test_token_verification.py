"""Verifying the truncation rule's output against the real tokeniser (ADR 0020).

PRU overflowed intake's window *after* truncation, because the cut length is derived
from an assumed characters-per-token ratio and PRU tokenised below it. The ratio was
justified as "below anything observed" on two data points; across 135 completed items
14% of documents fall below it.

**With this verification in place the ratio stops being a safety property.** Too high
gives a refusal here; too low truncates slightly more than needed. Neither is silent —
which is why the replacement value does not have to be provably below every remaining
document, an assertion that would be a fourth instance of the error it replaces.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from mapf.core.errors import InferenceStatusError, ModelBudgetExhaustedError
from mapf.core.ports import LLMResponse, ModelInfo
from mapf.pipeline.context_probe import TokenCount, measure_tokens

MODEL = ModelInfo(id="m", fingerprint="tag:m", fingerprint_source="tag")
BUDGET = 29_968


class _Server:
    """Reports a prompt token count, or refuses."""

    def __init__(self, ratio: float = 4.0, error: Exception | None = None) -> None:
        self._ratio = ratio
        self._error = error
        self.calls = 0
        self.budget: int | None = None

    def list_models(self) -> Sequence[ModelInfo]:  # pragma: no cover
        return ()

    def complete(self, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        self.budget = kwargs["sampling"].max_tokens
        if self._error is not None:
            raise self._error
        chars = len(kwargs["prompt"].messages[0].content)
        return LLMResponse(
            text="x", model_id="m", prompt_tokens=int(chars / self._ratio), finish_reason="stop"
        )


def _measure(server: _Server, chars: int) -> TokenCount:
    return measure_tokens(server, MODEL, "a" * chars, label="PRU 2026-04-14", budget=BUDGET)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------
def test_a_document_that_fits_is_reported_as_fitting() -> None:
    assert _measure(_Server(ratio=4.0), 98_121).fits


def test_the_document_that_actually_failed_is_caught() -> None:
    """PRU tokenised below 3.274, which is what a 98,121-character cut needs."""
    measured = _measure(_Server(ratio=3.1), 98_121)
    assert not measured.fits
    assert measured.tokens > BUDGET


def test_the_measurement_reports_the_real_ratio() -> None:
    measured = _measure(_Server(ratio=3.1), 98_121)
    assert measured.ratio == pytest.approx(3.1, abs=0.01)


def test_the_refusal_names_the_ratio_that_would_have_fitted() -> None:
    """A refusal that carries its own next step is one decision; a refusal that does
    not is an investigation."""
    measured = _measure(_Server(ratio=3.1), 98_121)
    assert measured.fitting_ratio == pytest.approx(3.1, abs=0.01)


def test_it_generates_exactly_one_token() -> None:
    """The count comes from the PREFILL. Generating more would pay for output nobody
    reads, on a document of nearly thirty thousand tokens."""
    server = _Server()
    _measure(server, 1000)
    assert server.budget == 1


def test_it_costs_one_call_per_document() -> None:
    server = _Server()
    _measure(server, 1000)
    assert server.calls == 1


# ---------------------------------------------------------------------------
# Failing softly, in the safe direction
# ---------------------------------------------------------------------------
def test_a_refused_prompt_reads_as_over_budget_not_as_fitting() -> None:
    """The server declining to answer must never be recorded as a pass; that is the
    direction where a doomed item reaches the run."""
    measured = _measure(_Server(error=InferenceStatusError(400, "too long")), 98_121)
    assert not measured.fits


def test_a_reasoning_model_burning_the_single_token_does_not_read_as_over_budget() -> None:
    """Reaching generation proves the prompt fitted; the count is simply not in hand,
    and inventing one would be worse than reporting zero."""
    measured = _measure(_Server(error=ModelBudgetExhaustedError("m", 1, 1)), 98_121)
    assert measured.fits
    assert measured.tokens == 0


def test_a_zero_token_count_has_no_ratio_rather_than_dividing_by_zero() -> None:
    measured = _measure(_Server(error=ModelBudgetExhaustedError("m", 1, 1)), 98_121)
    assert measured.ratio == 0.0
