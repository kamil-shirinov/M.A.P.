"""The context probe.

The first corpus run failed because config and the server disagreed and nothing
compared them. A pre-flight that checked a configured number against a computed one
would have passed it happily, so this measures the server instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from mapf.core.errors import InferenceStatusError, InferenceTimeoutError
from mapf.core.ports import ModelInfo
from mapf.pipeline.context_probe import (
    ContextReport,
    parse_reported_context,
    probe_context,
)

MODEL = ModelInfo(id="m", fingerprint="tag:m", fingerprint_source="tag")

# The body the server actually returned during the halted run.
REAL_BODY = (
    '{"error":"Engine protocol predict request received: the request (13830 tokens) '
    'exceeds the available context size (8192 tokens)"}'
)


class _Server:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.calls = 0

    def list_models(self) -> Sequence[ModelInfo]:  # pragma: no cover
        return ()

    def complete(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.last = kwargs
        if self.error is not None:
            raise self.error
        return None


# ---------------------------------------------------------------------------
# Reading the server's answer out of its rejection
# ---------------------------------------------------------------------------
def test_the_real_rejection_from_the_halted_run_is_parsed() -> None:
    assert parse_reported_context(REAL_BODY) == 8192


@pytest.mark.parametrize(
    "body",
    [
        "the request (99999 tokens) exceeds the available context size (32768 tokens)",
        "context length (16384 tokens) exceeded",
        "Context Window (4096 tokens) too small",
    ],
)
def test_common_phrasings_are_parsed(body: str) -> None:
    assert parse_reported_context(body) in (32768, 16384, 4096)


def test_a_body_that_names_no_context_yields_none() -> None:
    assert parse_reported_context('{"error":"malformed request"}') is None


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------
def test_a_server_matching_the_configuration_agrees() -> None:
    server = _Server(InferenceStatusError(400, "available context size (32768 tokens)"))
    report = probe_context(server, MODEL, agent="intake", configured=32768)
    assert report.reported == 32768
    assert report.agrees is True
    assert "ok" in report.describe()


def test_a_server_smaller_than_configured_disagrees() -> None:
    """The failure that actually happened: config said what the run needed, the
    server was loaded at 8,192, and nothing compared them."""
    server = _Server(InferenceStatusError(400, REAL_BODY))
    report = probe_context(server, MODEL, agent="intake", configured=32768)
    assert report.agrees is False
    assert "TOO SMALL" in report.describe()
    assert "8,192" in report.describe()


def test_a_server_larger_than_configured_agrees() -> None:
    """More context than promised is not a failure — the run stays inside its
    configured budget, so the guarantee still holds."""
    server = _Server(InferenceStatusError(400, "available context size (131072 tokens)"))
    report = probe_context(server, MODEL, agent="intake", configured=32768)
    assert report.agrees is True


def test_a_server_that_accepts_the_oversized_probe_agrees() -> None:
    """Acceptance is informative: the window is at least as large as the probe."""
    server = _Server(None)
    report = probe_context(server, MODEL, agent="intake", configured=16384)
    assert report.accepted_oversize is True
    assert report.agrees is True
    assert "accepted" in report.describe()


def test_a_rejection_without_a_number_does_not_agree() -> None:
    """Unknown is not the same as fine; inventing a verdict would be worse."""
    server = _Server(InferenceStatusError(400, "request too large"))
    report = probe_context(server, MODEL, agent="intake", configured=32768)
    assert report.reported is None
    assert report.agrees is False
    assert "without naming" in report.describe()


def test_a_timeout_says_nothing_about_the_window() -> None:
    server = _Server(InferenceTimeoutError("m", 5.0))
    report = probe_context(server, MODEL, agent="intake", configured=32768)
    assert report.reported is None
    assert report.agrees is False


# ---------------------------------------------------------------------------
# The probe itself
# ---------------------------------------------------------------------------
def test_the_probe_overshoots_the_configured_window() -> None:
    server = _Server(InferenceStatusError(400, REAL_BODY))
    probe_context(server, MODEL, agent="intake", configured=8192)
    sent = server.last["prompt"].messages[0].content
    # Comfortably over 8,192 tokens' worth of characters, so a healthy server
    # cannot quietly accept it.
    assert len(sent) > 8192 * 4


def test_the_probe_generates_at_most_one_token() -> None:
    """If the server does accept it, the cost must be a token rather than a run."""
    server = _Server(None)
    probe_context(server, MODEL, agent="intake", configured=8192)
    assert server.last["sampling"].max_tokens == 1


def test_one_request_per_probe() -> None:
    server = _Server(InferenceStatusError(400, REAL_BODY))
    probe_context(server, MODEL, agent="intake", configured=8192)
    assert server.calls == 1


def test_the_report_names_the_agent() -> None:
    report = ContextReport(
        agent="analyst", configured=32768, reported=8192, accepted_oversize=False
    )
    assert report.describe().startswith("analyst:")
