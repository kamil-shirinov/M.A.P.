"""Recording why each agent stopped.

Intake is capped at 2,048 tokens. If it ever reaches that cap its fact list is cut
mid-sentence, the analyst reasons from half a summary, and the result is a
schema-valid forecast built on a fragment with nothing marking it.

Observed intake output is 368 tokens against that cap, so this should never fire —
which is exactly why it is recorded rather than assumed. It has already fired twice
in real runs and nothing surfaced it: intake once at 18,938 tokens on the STZ
document, and the analyst once against the old 8,192 window.
"""

from __future__ import annotations

from mapf.pipeline.trace import CountingTrace


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.events.append(kwargs)


def _trace() -> CountingTrace:
    return CountingTrace(_Sink())


def _emit(trace: CountingTrace, stage: str, reason: str, attempt: int = 0) -> None:
    trace.record(stage=stage, attempt=attempt, data={"finish_reason": reason})


# ---------------------------------------------------------------------------
# What the trace aggregates
# ---------------------------------------------------------------------------
def test_a_completed_answer_is_recorded_and_not_flagged() -> None:
    trace = _trace()
    _emit(trace, "intake", "stop")
    assert trace.finish_reasons["intake"] == "stop"
    assert trace.truncated_output == set()


def test_stopping_for_length_is_flagged() -> None:
    """The model was cut off, so what it handed downstream is a fragment."""
    trace = _trace()
    _emit(trace, "intake", "length")
    assert trace.finish_reasons["intake"] == "length"
    assert trace.truncated_output == {"intake"}


def test_each_agent_is_tracked_separately() -> None:
    trace = _trace()
    _emit(trace, "intake", "length")
    _emit(trace, "analyst", "stop")
    _emit(trace, "structuralist", "stop")
    assert trace.truncated_output == {"intake"}
    assert trace.finish_reasons["analyst"] == "stop"


def test_a_truncated_repair_attempt_is_not_forgotten_by_a_later_one() -> None:
    """Any attempt that was cut off degraded that call, even if a retry completed."""
    trace = _trace()
    _emit(trace, "structuralist", "length", attempt=0)
    _emit(trace, "structuralist", "stop", attempt=1)
    assert trace.finish_reasons["structuralist"] == "stop"
    assert "structuralist" in trace.truncated_output


def test_a_missing_finish_reason_records_nothing_rather_than_guessing() -> None:
    trace = _trace()
    trace.record(stage="intake", attempt=0, data={"response": "x"})
    assert "intake" not in trace.finish_reasons
    assert trace.truncated_output == set()


def test_sub_stage_events_are_not_counted() -> None:
    """Validation failures are events, not calls."""
    trace = _trace()
    trace.record(stage="structuralist.validation_failed", data={"finish_reason": "length"})
    assert trace.truncated_output == set()


def test_the_inner_trace_still_receives_everything() -> None:
    sink = _Sink()
    trace = CountingTrace(sink)
    trace.record(stage="intake", attempt=0, data={"finish_reason": "length"})
    assert len(sink.events) == 1


# ---------------------------------------------------------------------------
# The manifest shape
# ---------------------------------------------------------------------------
def test_the_manifest_record_carries_both_fields() -> None:
    from mapf.core.ports import SamplingParams
    from mapf.pipeline.manifest import AgentRecord

    record = AgentRecord(
        alias="intake",
        model_id="m",
        fingerprint="tag:m",
        fingerprint_source="tag",
        sampling=SamplingParams(temperature=0.0),
        template_name="t",
        template_version="v1",
        template_sha256="0" * 64,
        finish_reason="length",
        output_truncated=True,
    )
    assert record.finish_reason == "length"
    assert record.output_truncated is True


def test_the_manifest_record_defaults_to_untruncated() -> None:
    """Absent evidence is not a truncation claim."""
    from mapf.core.ports import SamplingParams
    from mapf.pipeline.manifest import AgentRecord

    record = AgentRecord(
        alias="intake",
        model_id="m",
        fingerprint="tag:m",
        fingerprint_source="tag",
        sampling=SamplingParams(temperature=0.0),
        template_name="t",
        template_version="v1",
        template_sha256="0" * 64,
    )
    assert record.finish_reason is None
    assert record.output_truncated is False


# ---------------------------------------------------------------------------
# The ledger shape, mirroring the document-truncation flag
# ---------------------------------------------------------------------------
def test_the_ledger_records_which_agent_was_cut_off() -> None:
    from datetime import date

    from mapf.corpus.ledger import LedgerEntry

    entry = LedgerEntry(
        ticker="STZ",
        band="clean",
        filing_date=date(2026, 1, 7),
        status="complete",
        output_truncated=True,
        truncated_agents="intake",
    )
    assert entry.output_truncated is True
    assert entry.truncated_agents == "intake"


def test_document_truncation_and_output_truncation_are_separate_flags() -> None:
    """Different failures: one elides the input by a frozen rule, the other cuts the
    output mid-sentence by accident."""
    from datetime import date

    from mapf.corpus.ledger import LedgerEntry

    entry = LedgerEntry(
        ticker="BXP",
        band="clean",
        filing_date=date(2026, 1, 28),
        status="complete",
        truncated=True,
        elided_chars=121_441,
        output_truncated=False,
    )
    assert entry.truncated is True
    assert entry.output_truncated is False


# ---------------------------------------------------------------------------
# A runaway is failed, not flagged
# ---------------------------------------------------------------------------
def test_a_runaway_is_terminal() -> None:
    """Deterministic at temperature 0: the same document runs away identically on
    every attempt, so retrying only consumes the failure allowance."""
    from mapf.core.errors import OutputTruncatedError
    from mapf.corpus.ledger import is_terminal
    from mapf.corpus.runner import _reason_for

    reason = _reason_for(OutputTruncatedError("intake", 2048))
    assert reason == "output_truncated"
    assert is_terminal(reason) is True


def test_the_error_says_why_a_bigger_cap_is_not_the_answer() -> None:
    """Intake emits 252-543 tokens across documents from 2k to 51k characters, then
    on two documents runs past 18,000. A cap sized to 'what it wants' is meaningless
    when what it wants is unbounded."""
    from mapf.core.errors import OutputTruncatedError

    message = str(OutputTruncatedError("intake", 2048))
    assert "runaway" in message
    assert "few hundred tokens" in message


# ---------------------------------------------------------------------------
# One trace per item, not one per band
# ---------------------------------------------------------------------------
def test_counters_are_per_item_not_cumulative() -> None:
    """A CountingTrace shared across a band reports band-cumulative reasoning in
    every manifest — one run recorded 272,033 analyst reasoning tokens for a single
    item — and every item after the first truncation inherits its flag."""
    first, second = _trace(), _trace()
    first.record(stage="analyst", data={"reasoning_tokens": 4000, "finish_reason": "stop"})
    second.record(stage="analyst", data={"reasoning_tokens": 3000, "finish_reason": "stop"})
    assert first.reasoning_tokens["analyst"] == 4000
    assert second.reasoning_tokens["analyst"] == 3000


def test_a_truncation_does_not_leak_into_the_next_item() -> None:
    first, second = _trace(), _trace()
    _emit(first, "intake", "length")
    _emit(second, "intake", "stop")
    assert first.truncated_output == {"intake"}
    assert second.truncated_output == set()
