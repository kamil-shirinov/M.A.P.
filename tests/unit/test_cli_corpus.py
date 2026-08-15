"""`map corpus run` — the command that spends twelve nights.

The assertions are about what has to be true *before* inference starts: it refuses
on drifted prompts, it resumes without being asked and says what it skipped, and
`--check` does the whole pre-flight without calling a model once.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from mapf.cli.app import app
from mapf.cli.commands.corpus import _progress
from mapf.core.errors import MissingExhibitError
from mapf.core.models import Document, UntrustedText
from mapf.corpus.ledger import Ledger, LedgerEntry
from mapf.corpus.runner import CorpusHaltedError, CorpusItem, Health
from mapf.data.exhibits import EdgarExhibits
from mapf.prompts.loader import FilePromptStore
from tests.unit.test_cli import _config

runner = CliRunner()
STORE = FilePromptStore()


def _frozen(tmp_path: Path, **overrides: object) -> Path:
    """A two-item corpus whose prompt hashes match the live templates."""
    prompts = {
        agent: {
            "template": f"{stem}.{version}.md",
            "version": version,
            "sha256": STORE.digest(stem, version),
        }
        for agent, stem, version in (
            ("intake", "intake", "v2"),
            ("analyst", "scenario_analyst", "v3"),
            ("structuralist", "structuralist", "v2"),
        )
    }
    record: dict[str, object] = {
        "freeze_version": "2.0.0",
        "price_vintage": "2026-08-14",
        "models": {
            "intake": {"alias": "llama-3.2-3b"},
            "analyst": {"alias": "gemma4-12b"},
            "structuralist": {"alias": "qwen3-4b"},
        },
        "prompts": prompts,
        "exhibits": {
            "by_accession": {
                "0000000001-26-000001": {"document_id": "sha256:" + "a" * 64},
                "0000000001-26-000002": {"document_id": "sha256:" + "b" * 64},
            }
        },
        "corpus": {
            "criteria": {
                "bands": [
                    {"name": "clean", "first_open": "2026-01-01", "last_open": "2026-08-06"},
                    {
                        "name": "ambiguous",
                        "first_open": "2025-01-01",
                        "last_open": "2025-12-31",
                    },
                ],
                "seed": 20260813,
                "target_tickers": 1,
            },
            "ordering_sha256": "0" * 64,
            "accepted": [
                {
                    "ticker": "AAPL",
                    "cik": 320193,
                    "split": "dev",
                    "filings": [
                        {
                            "band": "clean",
                            "dates": ["2026-02-01", "2026-05-01"],
                            "accessions": [
                                "0000000001-26-000001",
                                "0000000001-26-000002",
                            ],
                        },
                        {
                            "band": "ambiguous",
                            "dates": ["2025-02-01"],
                            "accessions": ["0000000001-26-000003"],
                        },
                    ],
                }
            ],
            "rejected": [],
        },
    }
    record.update(overrides)
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _invoke(tmp_path: Path, *args: str, frozen: Path | None = None):  # type: ignore[no-untyped-def]
    return runner.invoke(
        app,
        [
            "corpus",
            "run",
            "--config",
            str(_config(tmp_path)),
            "--frozen",
            str(frozen or _frozen(tmp_path)),
            "--ledger-path",
            str(tmp_path / "ledger.jsonl"),
            *args,
        ],
    )


# ---------------------------------------------------------------------------
# Refusals that must happen before anything expensive
# ---------------------------------------------------------------------------
def test_a_drifted_prompt_refuses_before_the_server_is_contacted(tmp_path: Path) -> None:
    """The whole point: this must fail while it is still cheap."""
    frozen = _frozen(tmp_path)
    record = json.loads(frozen.read_text())
    record["prompts"]["analyst"]["sha256"] = hashlib.sha256(b"edited").hexdigest()
    frozen.write_text(json.dumps(record), encoding="utf-8")

    result = _invoke(tmp_path, frozen=frozen)
    assert result.exit_code != 0
    assert "content changed" in result.output
    # The config points at a dead port; reaching the server would say so instead.
    assert "connection" not in result.output.lower()


def test_a_missing_frozen_corpus_is_a_sentence_not_a_traceback(tmp_path: Path) -> None:
    result = _invoke(tmp_path, frozen=tmp_path / "absent.json")
    assert result.exit_code != 0
    assert "no frozen corpus" in result.output
    assert "pre-registration" in result.output


def test_an_unknown_band_lists_the_real_ones(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--band", "nonsense")
    assert result.exit_code == 2
    assert "clean" in result.output and "ambiguous" in result.output


def test_a_swapped_model_alias_refuses(tmp_path: Path) -> None:
    frozen = _frozen(tmp_path)
    record = json.loads(frozen.read_text())
    record["models"]["analyst"]["alias"] = "some-other-model"
    frozen.write_text(json.dumps(record), encoding="utf-8")

    result = _invoke(tmp_path, frozen=frozen)
    assert result.exit_code != 0
    assert "model alias" in result.output


# ---------------------------------------------------------------------------
# Resume — automatic, but never silent
# ---------------------------------------------------------------------------
def test_a_fresh_run_says_nothing_is_recorded(tmp_path: Path) -> None:
    result = _invoke(tmp_path)
    assert "nothing recorded" in result.output
    assert "all 2 items" in result.output


def test_a_resume_reports_what_it_skips_and_why(tmp_path: Path) -> None:
    """An unintended resume must be visible rather than silent."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(
            ticker="AAPL", band="clean", filing_date=date(2026, 2, 1), status="complete"
        )
    )
    ledger.append(
        LedgerEntry(
            ticker="AAPL",
            band="clean",
            filing_date=date(2026, 5, 1),
            status="failed",
            reason="missing_exhibit",
        )
    )
    result = _invoke(tmp_path)
    assert "skipping 2 of 2" in result.output
    assert "1 complete" in result.output
    assert "1 terminal" in result.output


def test_a_transient_failure_is_not_reported_as_skipped(tmp_path: Path) -> None:
    """It will be retried, so counting it as done would misdescribe the run."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(
            ticker="AAPL",
            band="clean",
            filing_date=date(2026, 2, 1),
            status="failed",
            reason="inference_unreachable",
        )
    )
    result = _invoke(tmp_path)
    assert "nothing recorded" in result.output


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------
def test_check_runs_no_inference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two minutes of pre-flight must never become the first two minutes of the run."""
    called: list[str] = []
    monkeypatch.setattr(
        "mapf.corpus.runner.execute",
        lambda *a, **k: called.append("ran"),  # pragma: no cover - must not fire
    )
    monkeypatch.setattr(
        "mapf.cli.commands.corpus.run_band",
        lambda *a, **k: called.append("band"),  # pragma: no cover - must not fire
    )
    _check_with(monkeypatch, "sha256:" + "d" * 64)
    _invoke(tmp_path, "--check")
    assert called == []


def test_check_verifies_the_prompt_freeze_first(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--check")
    assert "prompts and model aliases match" in result.output


def test_check_reports_an_unreachable_server(tmp_path: Path) -> None:
    """Server reachability is part of the pre-flight, not a run-time surprise."""
    result = _invoke(tmp_path, "--check")
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# The execution path, with the model and EDGAR stubbed out
# ---------------------------------------------------------------------------
class _Model:
    def __init__(self, alias: str) -> None:
        self.id = alias
        self.fingerprint = "tag:" + alias
        self.fingerprint_source = "tag"
        self.fingerprint_fields = ()


class _Provider:
    def list_models(self):  # type: ignore[no-untyped-def]
        return [_Model(a) for a in ("llama-3.2-3b", "gemma4-12b", "qwen3-4b")]

    def complete(self, **kwargs):  # type: ignore[no-untyped-def]  # pragma: no cover
        raise AssertionError("no inference should happen in these tests")


def _stub_infra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mapf.cli.commands.corpus.build_llm_provider", lambda *a, **k: _Provider()
    )
    monkeypatch.setattr(
        "mapf.cli.commands.corpus.build_run",
        lambda *a, **k: SimpleNamespace(
            agents=object(), market=object(), dividends=object(), trace=object()
        ),
    )


def test_the_run_reports_the_pinned_vintage_and_that_charts_are_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_infra(monkeypatch)
    monkeypatch.setattr(
        "mapf.cli.commands.corpus.run_band", lambda *a, **k: Health(completed=2)
    )
    result = _invoke(tmp_path)
    assert "vintage=2026-08-14" in result.output
    assert "charts=off" in result.output
    assert "2 complete" in result.output


def test_the_documents_callback_fetches_the_frozen_accession(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frozen record is the only source of which document an item uses."""
    _stub_infra(monkeypatch)
    seen: list[str] = []

    def fake_fetch(self, filing):  # type: ignore[no-untyped-def]
        seen.append(filing.accession)
        return Document(
            id="sha256:" + "c" * 64,
            source="x",
            text=UntrustedText("body"),
            fetched_at=datetime(2026, 8, 14, tzinfo=UTC),
        )

    monkeypatch.setattr(EdgarExhibits, "fetch", fake_fetch)
    captured: dict[str, object] = {}

    def fake_run_band(items, **kwargs):  # type: ignore[no-untyped-def]
        captured["docs"] = kwargs["documents"](items[0])
        return Health(completed=1)

    monkeypatch.setattr("mapf.cli.commands.corpus.run_band", fake_run_band)
    _invoke(tmp_path)
    assert seen == ["0000000001-26-000001"]


def test_a_halt_exits_seven_and_says_it_was_a_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_infra(monkeypatch)

    def halt(*a, **k):  # type: ignore[no-untyped-def]
        raise CorpusHaltedError("5 consecutive failures", {"market_data": 5})

    monkeypatch.setattr("mapf.cli.commands.corpus.run_band", halt)
    result = _invoke(tmp_path)
    assert result.exit_code == 7
    assert "HALTED" in result.output
    assert "by decision" in result.output
    assert "market_data=5" in result.output


def test_progress_prints_the_health_fields(capsys: pytest.CaptureFixture[str]) -> None:
    """This line is what gets watched for twelve nights."""
    _progress(
        3,
        709,
        CorpusItem("AAPL", "clean", date(2026, 2, 1)),
        LedgerEntry(
            ticker="AAPL",
            band="clean",
            filing_date=date(2026, 2, 1),
            status="complete",
            elapsed_s=498.2,
        ),
        Health(completed=3, unparseable=1, divergent=2, ungrounded_numerals=4),
    )
    out = capsys.readouterr().out
    assert "[   3/709] AAPL" in out
    assert "498.2s" in out
    assert "unparse=1" in out and "diverge=2" in out and "ungrounded=4" in out


def test_progress_marks_a_failure_with_its_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _progress(
        1,
        2,
        CorpusItem("AAPL", "clean", date(2026, 2, 1)),
        LedgerEntry(
            ticker="AAPL",
            band="clean",
            filing_date=date(2026, 2, 1),
            status="failed",
            reason="missing_exhibit",
        ),
        Health(failed=1),
    )
    assert "FAIL:missing_exhibit" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --check re-hashes the exhibits
# ---------------------------------------------------------------------------
def _check_with(monkeypatch: pytest.MonkeyPatch, doc_id: str | Exception) -> None:
    # --check reaches the server for model resolution, which is part of the
    # pre-flight; the test config points at a dead port.
    _stub_infra(monkeypatch)

    def fake_fetch(self, filing):  # type: ignore[no-untyped-def]
        if isinstance(doc_id, Exception):
            raise doc_id
        return Document(
            id=doc_id,
            source="x",
            text=UntrustedText("body"),
            fetched_at=datetime(2026, 8, 14, tzinfo=UTC),
        )

    monkeypatch.setattr(EdgarExhibits, "fetch", fake_fetch)


def test_check_passes_when_every_hash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = _frozen(tmp_path)
    record = json.loads(frozen.read_text())
    for spec in record["exhibits"]["by_accession"].values():
        spec["document_id"] = "sha256:" + "d" * 64
    frozen.write_text(json.dumps(record), encoding="utf-8")
    _check_with(monkeypatch, "sha256:" + "d" * 64)
    result = _invoke(tmp_path, "--check", frozen=frozen)
    assert result.exit_code == 0
    assert "all 2 match the frozen hashes" in result.output
    assert "no inference ran" in result.output


def test_check_fails_when_an_exhibit_changed_under_us(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filer can amend an 8-K. The corpus would silently be a different corpus."""
    _check_with(monkeypatch, "sha256:" + "f" * 64)
    result = _invoke(tmp_path, "--check")
    assert result.exit_code == 6
    assert "content changed" in result.output


def test_check_fails_when_an_exhibit_no_longer_fetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _check_with(monkeypatch, MissingExhibitError("gone"))
    result = _invoke(tmp_path, "--check")
    assert result.exit_code == 6
    assert "unfetchable" in result.output


def test_check_flags_an_item_absent_from_the_frozen_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = _frozen(tmp_path)
    record = json.loads(frozen.read_text())
    record["exhibits"] = {"by_accession": {}}
    frozen.write_text(json.dumps(record), encoding="utf-8")
    _check_with(monkeypatch, "sha256:" + "d" * 64)
    result = _invoke(tmp_path, "--check", frozen=frozen)
    assert "not in frozen record" in result.output


def test_limit_truncates_the_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _check_with(monkeypatch, "sha256:" + "d" * 64)
    result = _invoke(tmp_path, "--check", "--limit", "1")
    assert "all 1 items" in result.output or "1 items" in result.output


def test_check_prints_progress_on_a_long_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """709 items is a long silence otherwise."""
    frozen = _frozen(tmp_path)
    record = json.loads(frozen.read_text())
    plan_ = record["corpus"]["accepted"][0]["filings"][0]
    days = [f"2026-02-{d:02d}" for d in range(1, 29)] + [
        f"2026-03-{d:02d}" for d in range(1, 25)
    ]
    plan_["dates"] = days
    plan_["accessions"] = [f"0000000001-26-{i:06d}" for i in range(len(days))]
    record["exhibits"]["by_accession"] = {
        a: {"document_id": "sha256:" + "d" * 64} for a in plan_["accessions"]
    }
    frozen.write_text(json.dumps(record), encoding="utf-8")
    _check_with(monkeypatch, "sha256:" + "d" * 64)
    result = _invoke(tmp_path, "--check", frozen=frozen)
    assert "50/52" in result.output
