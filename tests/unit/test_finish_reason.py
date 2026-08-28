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
