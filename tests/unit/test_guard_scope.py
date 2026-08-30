"""The guards fixed after the audit (ADR 0022).

Each test below names a guard that used to return green while checking less than
its name claimed. They are grouped by the shape of the gap rather than by module,
because the shape is the transferable part:

1. presence standing in for identity
2. a declared number trusted instead of the thing measured
3. scope narrower than the sentence
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mapf.core.errors import InferenceStatusError
from mapf.core.models import Scenario, ScenarioSet
from mapf.core.quality import check as check_quality
from mapf.corpus.ledger import TERMINAL_REASONS, LedgerEntry, is_terminal
from mapf.corpus.runner import Health, _classify_status, _seed
from mapf.pipeline.trace import MAX_TRACE_EVENTS, MIN_TRACE_EVENTS, audit_trace


# ---------------------------------------------------------------------------
# 1. Presence standing in for identity — the trace guard
# ---------------------------------------------------------------------------
def _trace(tmp_path: Path, events: int) -> Path:
    path = tmp_path / "trace.jsonl"
    path.write_text("".join('{"stage":"intake"}\n' for _ in range(events)), encoding="utf-8")
    return path


def test_a_trace_holding_a_whole_band_is_rejected(tmp_path: Path) -> None:
    """The incident's own worst artifact. 56 of 57 runs had no trace and the 57th
    held every item's events — present, large, and belonging to 56 other runs. A
    file-exists check caught the 56 and passed the one that was actually wrong."""
    assert audit_trace(_trace(tmp_path, 200)) is not None


def test_a_single_run_worth_of_events_is_accepted(tmp_path: Path) -> None:
    assert audit_trace(_trace(tmp_path, 4)) is None


def test_the_ceiling_leaves_room_for_a_maximal_run(tmp_path: Path) -> None:
    """Intake twice under a degeneration retry, the analyst once, and the
    structuralist's full repair loop with its validation events."""
    assert audit_trace(_trace(tmp_path, 8)) is None


def test_a_trace_with_fewer_events_than_agents_is_rejected(tmp_path: Path) -> None:
    """Three agents each record at least one call, so two events is not a run."""
    assert audit_trace(_trace(tmp_path, 2)) is not None


def test_a_missing_trace_is_still_rejected(tmp_path: Path) -> None:
    assert audit_trace(tmp_path / "absent.jsonl") == "missing"


def test_an_empty_trace_is_still_rejected(tmp_path: Path) -> None:
    (tmp_path / "trace.jsonl").write_text("", encoding="utf-8")
    assert audit_trace(tmp_path / "trace.jsonl") == "empty"


def test_blank_lines_do_not_count_as_events(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text("\n\n\n\n\n", encoding="utf-8")
    assert audit_trace(path) is not None


def test_the_bounds_leave_a_usable_window() -> None:
    assert MIN_TRACE_EVENTS < MAX_TRACE_EVENTS


# ---------------------------------------------------------------------------
# 2. A declared number trusted instead of the thing measured — status classing
# ---------------------------------------------------------------------------
def test_a_context_rejection_is_terminal_however_it_is_worded() -> None:
    """The previous rule matched four English phrases, so a server phrasing its
    refusal differently fell through to transient and was retried forever."""
    assert is_terminal(_classify_status(InferenceStatusError(400, "nope")))


def test_a_named_context_rejection_keeps_the_more_specific_name() -> None:
    """A parsed message may sharpen the report. It may not decide the outcome."""
    body = '{"error":"the request exceeds the available context size (8192 tokens)"}'
    assert _classify_status(InferenceStatusError(400, body)) == "context_overflow"


def test_both_branches_of_the_message_match_are_terminal() -> None:
    """Which is what makes the match a refinement rather than a decision: nothing
    about resume behaviour turns on whether the phrase happened to be present."""
    named = _classify_status(InferenceStatusError(400, "context length exceeded"))
    unnamed = _classify_status(InferenceStatusError(400, "Bad Request"))
    assert named != unnamed
    assert {named, unnamed} <= TERMINAL_REASONS


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_server_error_stays_transient(status: int) -> None:
    """A 5xx says the server is unwell, which a retry may well survive."""
    assert not is_terminal(_classify_status(InferenceStatusError(status, "upstream error")))


@pytest.mark.parametrize("status", [400, 404, 413, 422])
def test_every_client_error_is_terminal(status: int) -> None:
    """A 4xx says THIS request is unacceptable, so an identical retry is refused
    identically. That is protocol semantics, not one vendor's wording."""
    assert is_terminal(_classify_status(InferenceStatusError(status, "")))


# ---------------------------------------------------------------------------
# 3. Scope narrower than the sentence — the band failure allowance
# ---------------------------------------------------------------------------
def _entry(ticker: str, band: str, *, failed: bool) -> LedgerEntry:
    return LedgerEntry(
        ticker=ticker,
        band=band,
        filing_date=date(2026, 1, 7),
        status="failed" if failed else "complete",
        reason="missing_exhibit" if failed else None,
        run_id=None,
    )


class _Ledger:
    def __init__(self, *entries: LedgerEntry) -> None:
        self._entries = entries

    def resolved(self) -> dict[tuple[str, str, date], LedgerEntry]:
        return {e.key: e for e in self._entries}


def test_the_allowance_counts_failures_from_earlier_passes() -> None:
    """`2% of 356` is a property of the BAND. Counting from zero on every resume
    enforces it per invocation: three resumes tolerate 24 against an allowance of 8."""
    ledger = _Ledger(
        _entry("AAA", "clean", failed=True),
        _entry("BBB", "clean", failed=True),
        _entry("CCC", "clean", failed=False),
    )
    health = _seed(Health(), ledger, band="clean")  # type: ignore[arg-type]
    assert health.failed == 2
    assert health.completed == 1


def test_seeding_ignores_the_other_band() -> None:
    ledger = _Ledger(
        _entry("AAA", "clean", failed=True),
        _entry("BBB", "ambiguous", failed=True),
    )
    assert _seed(Health(), ledger, band="clean").failed == 1  # type: ignore[arg-type]


def test_a_fresh_band_seeds_to_nothing() -> None:
    assert _seed(Health(), _Ledger(), band="clean").failed == 0  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. Scope narrower than the sentence — signed numeral grounding
# ---------------------------------------------------------------------------
def _scenarios(justification: str) -> ScenarioSet:
    def one(ret: float, text: str) -> Scenario:
        return Scenario(
            justification=text.ljust(20, "."),
            probability_weight=1 / 3,
            price_return=ret,
            annualised_vol=0.25,
        )

    return ScenarioSet(
        bullish=one(0.05, justification),
        base_case=one(0.0, "base case reasoning here"),
        bearish=one(-0.05, "bearish reasoning here"),
    )


def test_a_positive_fact_does_not_ground_a_negative_claim() -> None:
    """The whole point. A source saying margin rose 46.3% does not support a
    justification saying it fell 46.3% — that is the opposite claim, not a
    rounding difference."""
    flags = check_quality(
        _scenarios("margin moved -46.3 this quarter"),
        horizon_days=5,
        facts=["gross margin was 46.3 percent"],
    )
    assert any("-46.3" in flag for flag in flags.ungrounded_numerals)


def test_a_matching_sign_still_grounds() -> None:
    flags = check_quality(
        _scenarios("margin was 46.3 this quarter"),
        horizon_days=5,
        facts=["gross margin was 46.3 percent"],
    )
    assert flags.ungrounded_numerals == ()


def test_a_negative_fact_grounds_a_negative_claim() -> None:
    flags = check_quality(
        _scenarios("guidance cut by -12.5 percent"),
        horizon_days=5,
        facts=["guidance revised by -12.5 percent"],
    )
    assert flags.ungrounded_numerals == ()


def test_rounding_is_still_tolerated_within_one_percent() -> None:
    """The check must stay crude enough that honest paraphrase does not trip it."""
    flags = check_quality(
        _scenarios("margin near 46.0 this quarter"),
        horizon_days=5,
        facts=["gross margin was 46.3 percent"],
    )
    assert flags.ungrounded_numerals == ()


def test_the_tolerance_does_not_widen_for_negative_values() -> None:
    """`0.01 * known` is negative for a negative fact, which would make the bound
    `max(0.05, negative)` and silently collapse to the absolute floor."""
    flags = check_quality(
        _scenarios("guidance cut by -80.0 percent"),
        horizon_days=5,
        facts=["guidance revised by -100.0 percent"],
    )
    assert flags.ungrounded_numerals != ()


def test_a_run_whose_trace_holds_the_band_fails_verification(tmp_path: Path) -> None:
    """End to end through the runner's own gate, not just `audit_trace`."""
    from mapf.corpus.runner import REQUIRED_ARTIFACTS, _verify_artifacts

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in REQUIRED_ARTIFACTS:
        (run_dir / name).write_text("x", encoding="utf-8")
    (run_dir / "trace.jsonl").write_text('{"stage":"intake"}\n' * 200, encoding="utf-8")
    with pytest.raises(Exception, match="more than one run"):
        _verify_artifacts(run_dir, "r")


def test_a_status_below_four_hundred_is_not_a_refusal() -> None:
    """A 3xx reaching here is not the server refusing the request, so it must not
    be classified as one."""
    assert _classify_status(InferenceStatusError(304, "not modified")) == "other"
