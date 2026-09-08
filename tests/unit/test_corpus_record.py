"""Reading the frozen record, and asking it about one ticker.

The loader was eight lines inside a CLI command, which meant the only read path for
the pre-registration sat at the top of the import graph. These pin the two things
that changed when it moved: the failure stays typed and keeps its exit code, and the
record can now answer "what does M.A.P. hold for this ticker" without the caller
re-deriving the date-to-accession pairing that identifies a filing.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapf.cli.app import EXIT_DATA, app, exit_code_for, hint_for
from mapf.corpus.record import FrozenRecordError, load_frozen
from mapf.corpus.selection import (
    Band,
    BandFilings,
    Corpus,
    HeldFiling,
    SelectionCriteria,
    TickerPlan,
)

runner = CliRunner()

CLEAN = Band(name="clean", first_open=date(2026, 1, 1), last_open=date(2026, 12, 1))
AMBIG = Band(name="ambiguous", first_open=date(2025, 1, 1), last_open=date(2025, 12, 1))


def _corpus() -> Corpus:
    return Corpus(
        criteria=SelectionCriteria(bands=(CLEAN, AMBIG), seed=1, target_tickers=2),
        ordering_sha256="0" * 64,
        accepted=(
            TickerPlan(
                ticker="BBB",
                cik=2,
                split="dev",
                filings=(
                    BandFilings(
                        band="clean",
                        dates=(date(2026, 5, 4), date(2026, 2, 3)),
                        accessions=("0000000002-26-000002", "0000000002-26-000001"),
                    ),
                    BandFilings(
                        band="ambiguous",
                        dates=(date(2025, 2, 3),),
                        accessions=("0000000002-25-000001",),
                    ),
                ),
            ),
            TickerPlan(
                ticker="AAA",
                cik=1,
                split="holdout",
                filings=(
                    BandFilings(
                        band="clean",
                        dates=(date(2026, 2, 3),),
                        accessions=("0000000001-26-000001",),
                    ),
                ),
            ),
        ),
        rejected=(),
    )


# ---------------------------------------------------------------------------
# load_frozen
# ---------------------------------------------------------------------------
def test_the_record_comes_back_raw_not_as_a_corpus(tmp_path: Path) -> None:
    """The file carries fields `Corpus` does not — the freeze digest is computed
    over the record as written, so a caller has to see exactly what was on disk."""
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps({"freeze_version": "2.4.0", "corpus": {}}), encoding="utf-8")

    record = load_frozen(path)

    assert record["freeze_version"] == "2.4.0"
    assert "corpus" in record


def test_a_missing_record_is_typed_not_a_bare_oserror(tmp_path: Path) -> None:
    with pytest.raises(FrozenRecordError, match="no frozen corpus at"):
        load_frozen(tmp_path / "absent.json")


def test_a_corrupt_record_names_the_file_and_the_parse_failure(tmp_path: Path) -> None:
    """`json.JSONDecodeError` alone says a line and column and not which file."""
    path = tmp_path / "frozen.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(FrozenRecordError, match=r"frozen\.json is not valid JSON"):
        load_frozen(path)


def test_the_lifted_failure_keeps_the_exit_code_it_had_in_the_cli() -> None:
    """It exited 5 when the check lived in the command. Moving it into a library
    must not quietly demote it to the generic 1."""
    assert exit_code_for(FrozenRecordError("gone")) == EXIT_DATA
    assert hint_for(FrozenRecordError("gone")) == (
        "The corpus is the pre-registration. Freeze and commit it first."
    )


def test_map_corpus_run_still_reports_a_missing_record_the_same_way(tmp_path: Path) -> None:
    result = runner.invoke(app, ["corpus", "run", "--frozen", str(tmp_path / "absent.json")])

    assert result.exit_code == EXIT_DATA
    assert "no frozen corpus at" in result.output
    assert "pre-registration" in result.output


# ---------------------------------------------------------------------------
# filings_for
# ---------------------------------------------------------------------------
def test_every_filing_held_for_a_ticker_comes_back_with_band_and_split() -> None:
    held = _corpus().filings_for("BBB")

    assert held == (
        HeldFiling(
            ticker="BBB",
            filed=date(2025, 2, 3),
            accession="0000000002-25-000001",
            band="ambiguous",
            split="dev",
        ),
        HeldFiling(
            ticker="BBB",
            filed=date(2026, 2, 3),
            accession="0000000002-26-000001",
            band="clean",
            split="dev",
        ),
        HeldFiling(
            ticker="BBB",
            filed=date(2026, 5, 4),
            accession="0000000002-26-000002",
            band="clean",
            split="dev",
        ),
    )


def test_the_dates_are_ordered_even_though_the_record_is_not() -> None:
    """`BandFilings.dates` is stored in whatever order selection produced. A page
    listing a company's filings should not inherit that."""
    assert [f.filed for f in _corpus().filings_for("BBB")] == sorted(
        f.filed for f in _corpus().filings_for("BBB")
    )


def test_a_ticker_the_corpus_does_not_hold_returns_empty_not_an_error() -> None:
    """A legitimate question with a legitimate answer: most tickers are not in it."""
    assert _corpus().filings_for("ZZZZ") == ()


def test_each_date_keeps_its_own_accession() -> None:
    """The pairing is the part that is expensive to get wrong — a date matched to
    the neighbouring accession names a different filing while looking well-formed."""
    by_date = {f.filed: f.accession for f in _corpus().filings_for("BBB")}
    assert by_date[date(2026, 2, 3)] == "0000000002-26-000001"
    assert by_date[date(2026, 5, 4)] == "0000000002-26-000002"


def test_unequal_dates_and_accessions_refuse_rather_than_pairing_off_by_one() -> None:
    filings = BandFilings(
        band="clean",
        dates=(date(2026, 2, 3), date(2026, 5, 4)),
        accessions=("0000000002-26-000001",),
    )
    with pytest.raises(ValueError, match="argument 2 is shorter"):
        filings.pairs()


def test_a_record_frozen_before_accessions_reports_none_rather_than_inventing_one() -> None:
    filings = BandFilings(band="clean", dates=(date(2026, 2, 3),))
    assert filings.pairs() == ((date(2026, 2, 3), None),)


def test_the_split_travels_with_every_filing() -> None:
    """A page showing a holdout ticker's filings must be able to say so without a
    second lookup — the split is why an item is or is not spendable (ADR 0031)."""
    assert {f.split for f in _corpus().filings_for("AAA")} == {"holdout"}
    assert {f.split for f in _corpus().filings_for("BBB")} == {"dev"}
