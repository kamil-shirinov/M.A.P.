"""The context probe.

The first corpus run failed because config and the server disagreed and nothing
compared them. A pre-flight that checked a configured number against a computed one
would have passed it happily, so this measures the server — by bracketing, not by
reading its error prose, which would be vendor coupling in application code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from mapf.core.errors import (
    InferenceStatusError,
    InferenceTimeoutError,
    ModelBudgetExhaustedError,
)
from mapf.core.ports import ModelInfo
from mapf.pipeline.context_probe import (
    ContextReport,
    parse_reported_context,
    probe_context,
)

MODEL = ModelInfo(id="m", fingerprint="tag:m", fingerprint_source="tag")

# The body one particular server returned during the halted run. Used only to show
# the optional refinement works — nothing branches on it.
REAL_BODY = (
    '{"error":"Engine protocol predict request received: the request (13830 tokens) '
    'exceeds the available context size (8192 tokens)"}'
)


class _Server:
    """Accepts any prompt up to `window` tokens, rejects anything larger.

    Token count is approximated by the repeat count of the filler word, which is
    exactly what the probe relies on.
    """

    def __init__(
        self,
        window: int,
        body: str = "too long",
        silent: bool = False,
        reasons: bool = False,
    ) -> None:
        self.window = window
        self.body = body
        self.silent = silent
        self.reasons = reasons
        self.sizes: list[int] = []
        self.budget: int | None = None

    def list_models(self) -> Sequence[ModelInfo]:  # pragma: no cover
        return ()

    def complete(self, **kwargs: Any) -> Any:
        tokens = kwargs["prompt"].messages[0].content.count(" the")
        self.sizes.append(tokens)
        self.budget = kwargs["sampling"].max_tokens
        if tokens > self.window:
            if self.silent:
                raise InferenceTimeoutError("m", 1.0)
            raise InferenceStatusError(400, self.body)
        if self.reasons:
            # A reasoning model given a one-token budget spends it thinking.
            raise ModelBudgetExhaustedError("m", 1, 0)
        return None


# ---------------------------------------------------------------------------
# The bracket
# ---------------------------------------------------------------------------
def test_a_server_at_the_configured_window_is_verified() -> None:
    report = probe_context(_Server(32768), MODEL, agent="intake", configured=32768)
    assert report.agrees is True
    assert report.accepts_under is True
    assert report.rejects_over is True
    assert "bracketing" in report.describe()


def test_a_server_smaller_than_configured_is_caught() -> None:
    """The failure that actually happened: config said what the run needed, the
    server was loaded at 8,192, and nothing compared them."""
    report = probe_context(_Server(8192), MODEL, agent="intake", configured=32768)
    assert report.agrees is False
    assert "TOO SMALL" in report.describe()


def test_a_server_larger_than_configured_agrees_and_says_so() -> None:
    """More context than promised is not a failure — the run stays inside its
    configured budget, so the guarantee holds."""
    report = probe_context(_Server(262144), MODEL, agent="intake", configured=32768)
    assert report.agrees is True
    assert report.larger_than_configured is True
    assert "larger" in report.describe()


def test_the_under_probe_sits_below_the_configured_window() -> None:
    """Scaffolding must not push it over and produce a false 'too small'."""
    server = _Server(32768)
    probe_context(server, MODEL, agent="intake", configured=32768)
    assert server.sizes[0] < 32768


def test_the_over_probe_sits_comfortably_above() -> None:
    server = _Server(32768)
    probe_context(server, MODEL, agent="intake", configured=32768)
    assert server.sizes[1] > 32768 * 2


def test_a_rejected_under_probe_skips_the_over_probe() -> None:
    """Once the window is known too small, the second request tells us nothing and
    costs a prefill."""
    server = _Server(1000)
    probe_context(server, MODEL, agent="intake", configured=32768)
    assert len(server.sizes) == 1


def test_two_requests_when_the_window_is_adequate() -> None:
    server = _Server(32768)
    probe_context(server, MODEL, agent="intake", configured=32768)
    assert len(server.sizes) == 2


def test_each_probe_generates_at_most_one_token() -> None:
    server = _Server(32768)
    probe_context(server, MODEL, agent="intake", configured=32768)
    assert server.budget == 1


# ---------------------------------------------------------------------------
# Backend independence — the point of bracketing
# ---------------------------------------------------------------------------
def test_a_server_that_names_no_number_is_still_verified() -> None:
    """Two of three agents rejected the earlier probe without naming a context.
    The bracket does not need one."""
    report = probe_context(
        _Server(16384, body="request too large"), MODEL, agent="structuralist", configured=16384
    )
    assert report.agrees is True
    assert report.reported is None
    assert "bracketing" in report.describe()


def test_a_transport_failure_on_the_under_probe_is_raised_not_read_as_too_small() -> None:
    """A timeout says nothing about the window. Reporting one would send someone to
    change a setting that was never wrong."""
    with pytest.raises(InferenceTimeoutError):
        probe_context(_Server(1000, silent=True), MODEL, agent="intake", configured=32768)


def test_a_transport_failure_on_the_over_probe_is_also_raised() -> None:
    """Ambiguous either way: a dropped connection is not a small window, and a
    pre-flight that cannot determine the answer must say so rather than guess."""
    with pytest.raises(InferenceTimeoutError):
        probe_context(_Server(16384, silent=True), MODEL, agent="a", configured=16384)


# ---------------------------------------------------------------------------
# Reasoning models
# ---------------------------------------------------------------------------
def test_budget_exhaustion_on_the_probe_means_the_prompt_was_accepted() -> None:
    """A reasoning model given a one-token budget spends it thinking and returns no
    answer, which the provider reports as exhaustion. Reaching generation at all
    proves the prompt fitted — reading it as a rejection made the probe report
    TOO SMALL for a correctly configured server."""
    report = probe_context(
        _Server(16384, reasons=True), MODEL, agent="analyst", configured=16384
    )
    assert report.agrees is True
    assert report.accepts_under is True


def test_a_reasoning_model_below_the_window_still_reads_as_too_small() -> None:
    report = probe_context(
        _Server(4096, reasons=True), MODEL, agent="analyst", configured=16384
    )
    assert report.agrees is False


# ---------------------------------------------------------------------------
# The optional refinement
# ---------------------------------------------------------------------------
def test_a_named_number_is_shown_when_present() -> None:
    report = probe_context(
        _Server(8192, body=REAL_BODY), MODEL, agent="intake", configured=32768
    )
    assert report.reported == 8192
    assert "names 8,192" in report.describe()


def test_the_verdict_does_not_depend_on_the_named_number() -> None:
    """Same window, one server verbose and one terse: the same verdict."""
    verbose = probe_context(_Server(8192, body=REAL_BODY), MODEL, agent="a", configured=32768)
    terse = probe_context(_Server(8192, body="nope"), MODEL, agent="a", configured=32768)
    assert verbose.agrees is False
    assert terse.agrees is False


def test_the_parser_is_tolerant_but_optional() -> None:
    assert parse_reported_context(REAL_BODY) == 8192
    assert parse_reported_context("context length (16384 tokens) exceeded") == 16384
    assert parse_reported_context('{"error":"malformed request"}') is None


def test_the_report_names_the_agent() -> None:
    report = ContextReport(
        agent="analyst", configured=32768, accepts_under=False, rejects_over=True
    )
    assert report.describe().startswith("analyst:")


@pytest.mark.parametrize("configured", [512, 8192, 16384, 32768, 65536])
def test_the_bracket_holds_at_any_configured_size(configured: int) -> None:
    assert probe_context(
        _Server(configured), MODEL, agent="a", configured=configured
    ).agrees
    assert not probe_context(
        _Server(configured // 2), MODEL, agent="a", configured=configured
    ).agrees
