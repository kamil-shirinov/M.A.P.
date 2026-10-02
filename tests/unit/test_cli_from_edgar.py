"""`map run --from-edgar`: a forecast from a filing that is not in the corpus.

Two behaviours here are defined rather than emergent, and both exist because the
alternative is a quiet lie:

**It never falls back to news.** `--from-edgar` and the news path answer different
questions from different documents. A filer with no Item 2.02 in the window that
silently reverted to whatever `.txt` files happened to be on disk would produce a
forecast labelled as coming from a filing that did not come from one.

**The artifact says which it was.** The run is outside `frozen.json`: unscored, no
band, and it must never be pooled with corpus items. Absence of a `freeze_version`
was already *suggestive* of that, but absence is ambiguous — a corpus run predating
the field looks identical. So the manifest carries a positive claim instead.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapf.cli.app import EXIT_DATA, app
from mapf.core.hashing import document_id
from mapf.core.models import Document, EarningsFiling, UntrustedText
from tests.unit.test_cli import _config, _NullDiv, _StubMarket, _StubProvider

runner = CliRunner()

OLDER = EarningsFiling(accession="0000320193-26-000041", cik=320193, filed=date(2026, 5, 1))
NEWEST = EarningsFiling(accession="0000320193-26-000078", cik=320193, filed=date(2026, 8, 4))


def _exhibit(body: str, source: str = "https://www.sec.gov/Archives/exhibit.htm") -> Document:
    return Document(
        id=document_id(body.encode("utf-8")),
        source=source,
        text=UntrustedText(body),
        fetched_at=datetime(2026, 9, 8, tzinfo=UTC),
    )


class _FakeFilings:
    """Records the window it was asked for, so the failure message can be checked
    against the search that actually happened rather than against a repeated string."""

    def __init__(self, *found: EarningsFiling) -> None:
        self._found = found
        self.asked: tuple[str, date, date] | None = None

    def earnings_filings(self, ticker: str, start: date, end: date) -> tuple[EarningsFiling, ...]:
        self.asked = (ticker, start, end)
        return self._found


class _FakeExhibits:
    def __init__(self, text: str = "Apple reported quarterly revenue of $94.9bn.") -> None:
        self._text = text
        self.fetched: list[EarningsFiling] = []

    def fetch(self, filing: EarningsFiling) -> Document:
        self.fetched.append(filing)
        # The shape `EdgarExhibits` gives a real exhibit: the accession, dashes removed,
        # is the archive directory.
        url = f"https://www.sec.gov/Archives/edgar/data/{filing.cik}/{filing.path_segment}/ex99.htm"
        return _exhibit(f"{self._text} [{filing.accession}]", url)


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    filings: _FakeFilings,
    exhibits: _FakeExhibits | None = None,
) -> None:
    from mapf import bootstrap
    from mapf.cli.commands import run as run_module

    monkeypatch.setattr(run_module, "build_filings", lambda s, c: filings)
    monkeypatch.setattr(run_module, "build_exhibits", lambda s, c: exhibits or _FakeExhibits())
    monkeypatch.setattr(run_module, "build_llm_provider", lambda s, fixtures=None: _StubProvider())
    monkeypatch.setattr(bootstrap, "build_market_data", lambda s: _StubMarket())
    monkeypatch.setattr(bootstrap, "build_dividends", lambda s: _NullDiv())


def _manifest(tmp_path: Path) -> dict[str, object]:
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    return dict(json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8")))


def test_the_newest_filing_in_the_window_is_the_one_forecast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Newest, not first: `earnings_filings` sorts ascending, and an old quarter's
    exhibit would forecast against a price history that has already moved past it."""
    filings, exhibits = _FakeFilings(OLDER, NEWEST), _FakeExhibits()
    _wire(monkeypatch, filings, exhibits)

    result = runner.invoke(app, ["run", "AAPL", "--from-edgar", "--config", str(_config(tmp_path))])

    assert result.exit_code == 0, result.output
    assert exhibits.fetched == [NEWEST]
    assert NEWEST.accession in result.output


def test_the_run_record_says_the_document_came_from_edgar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _FakeFilings(NEWEST))

    result = runner.invoke(app, ["run", "AAPL", "--from-edgar", "--config", str(_config(tmp_path))])

    assert result.exit_code == 0, result.output
    manifest = _manifest(tmp_path)
    assert manifest["document_source"] == "edgar"
    # The filing, so the journal can relate this run to the corpus by accession as the
    # live page does: a re-fetched document can hash differently from the frozen one.
    assert manifest["document_accession"] == NEWEST.accession
    # The old signal, kept: it is outside the frozen corpus, so it is unscored and
    # carries no band. The positive field is what makes that unambiguous.
    assert manifest["freeze_version"] is None


def test_the_runs_own_trace_names_the_filing_it_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What lets the journal relate a run made before the manifest recorded the filing:
    the trace the real pipeline wrote, read back, names the accession."""
    from mapf.pipeline.trace import document_accession

    _wire(monkeypatch, _FakeFilings(NEWEST))

    result = runner.invoke(app, ["run", "AAPL", "--from-edgar", "--config", str(_config(tmp_path))])

    assert result.exit_code == 0, result.output
    (run,) = (tmp_path / "runs").iterdir()
    assert document_accession(run / "trace.jsonl") == NEWEST.accession


def test_a_news_run_is_distinguishable_from_an_edgar_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both are outside the corpus, and until now both were recorded identically."""
    from mapf import bootstrap
    from mapf.cli.commands import run as run_module

    news = tmp_path / "news"
    news.mkdir()
    (news / "a.txt").write_text("Apple reported quarterly revenue.", encoding="utf-8")
    monkeypatch.setattr(run_module, "build_llm_provider", lambda s, fixtures=None: _StubProvider())
    monkeypatch.setattr(bootstrap, "build_market_data", lambda s: _StubMarket())
    monkeypatch.setattr(bootstrap, "build_dividends", lambda s: _NullDiv())

    result = runner.invoke(app, ["run", "AAPL", "--config", str(_config(tmp_path))])

    assert result.exit_code == 0, result.output
    manifest = _manifest(tmp_path)
    assert manifest["document_source"] == "news"
    assert manifest["document_accession"] is None  # no filing was read


def test_no_filing_in_the_window_fails_and_names_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filings = _FakeFilings()
    _wire(monkeypatch, filings)

    result = runner.invoke(
        app,
        ["run", "AAPL", "--from-edgar", "--edgar-days", "30", "--config", str(_config(tmp_path))],
    )

    assert result.exit_code == EXIT_DATA
    assert filings.asked is not None
    _, start, end = filings.asked
    assert (end - start).days == 30
    # The message names the window that was actually searched, so "there is no
    # filing" can be told apart from "you searched the wrong 30 days".
    assert str(start) in result.output
    assert str(end) in result.output
    assert "--edgar-days" in result.output


def test_it_does_not_fall_back_to_news_when_there_is_no_filing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dangerous case: news is present and would have produced a forecast."""
    news = tmp_path / "news"
    news.mkdir()
    (news / "a.txt").write_text("Unrelated commentary about the sector.", encoding="utf-8")
    _wire(monkeypatch, _FakeFilings())

    result = runner.invoke(app, ["run", "AAPL", "--from-edgar", "--config", str(_config(tmp_path))])

    assert result.exit_code == EXIT_DATA
    assert not (tmp_path / "runs").exists()


def test_from_edgar_and_news_dir_are_refused_together(tmp_path: Path) -> None:
    """Not a precedence question. Silently honouring one would mislabel the run."""
    result = runner.invoke(
        app,
        [
            "run",
            "AAPL",
            "--from-edgar",
            "--news-dir",
            str(tmp_path),
            "--config",
            str(_config(tmp_path)),
        ],
    )

    assert result.exit_code == 2
    assert "different document sources" in result.output


def test_a_backwards_window_is_refused_rather_than_searched(tmp_path: Path) -> None:
    """A non-positive window makes `start` later than `end`. EDGAR would return
    nothing, and the honest failure above would then report an interval the user
    never chose as though no filing existed in it."""
    result = runner.invoke(
        app,
        ["run", "AAPL", "--from-edgar", "--edgar-days", "0", "--config", str(_config(tmp_path))],
    )

    assert result.exit_code == 2
    assert "at least 1" in result.output


def test_an_oversized_exhibit_is_cut_to_the_intake_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule the corpus path applies (ADR 0020), so an EDGAR run and a
    corpus run of the same exhibit see the same document."""
    _wire(monkeypatch, _FakeFilings(NEWEST), _FakeExhibits("Revenue. " * 40_000))

    result = runner.invoke(app, ["run", "AAPL", "--from-edgar", "--config", str(_config(tmp_path))])

    assert result.exit_code == 0, result.output
    assert "head_tail_v1" in result.output
