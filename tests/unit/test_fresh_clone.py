"""A fresh clone has no `runs/` and no `var/`, and must still work.

Neither directory is tracked, not even for a placeholder. That is only safe if every
command which writes to one creates it, and every command which merely reads one treats
its absence as "nothing here yet" rather than as an error. These tests hold both halves
to that, from a working directory containing only what a clone contains.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mapf.cli.app import app
from mapf.corpus.ledger import Ledger, LedgerEntry
from mapf.corpus.pins import RealisedPins
from mapf.corpus.scores import write_once
from mapf.data.symbols import SqliteSymbolIndex, Throttle, sync
from mapf.eval.scorer import RealisedPin
from tests.unit.test_cli import _config
from tests.unit.test_cli_from_edgar import NEWEST, _FakeFilings, _wire
from tests.unit.test_data_symbols import FIXTURE, UA, URL

ROOT = Path(__file__).parents[2]
runner = CliRunner()


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory holding what a clone holds that a command reads, and neither
    `runs/` nor `var/`. Commands resolve those relative to the working directory."""
    root = tmp_path / "clone"
    root.mkdir()
    shutil.copytree(ROOT / "corpus", root / "corpus")
    monkeypatch.chdir(root)
    return root


def _relative_config(tmp_path: Path) -> Path:
    """The test config, with its directories where the shipped config puts them."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = _config(elsewhere)
    text = path.read_text(encoding="utf-8")
    for absolute, relative in (
        (elsewhere / "llm", "var/llm"),
        (elsewhere / "prices", "var/prices"),
        (elsewhere / "symbols.sqlite", "var/symbols.sqlite"),
        (elsewhere / "runs", "runs"),
    ):
        assert f'"{absolute}"' in text
        text = text.replace(f'"{absolute}"', f'"{relative}"')
    path.write_text(text, encoding="utf-8")
    return path


def _neither_exists(root: Path) -> bool:
    return not (root / "runs").exists() and not (root / "var").exists()


# --- the repository ------------------------------------------------------------


def test_the_repository_tracks_neither_directory_and_ignores_both() -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
        )

    assert git("ls-files", "runs", "var").stdout.strip() == ""
    # Ignored whatever lies under them, including paths that do not exist yet.
    for path in ("runs/any-run/trace.jsonl", "var/corpus/ledger.jsonl"):
        assert git("check-ignore", "-q", path).returncode == 0, path


# --- commands that only read ---------------------------------------------------


def test_listing_runs_with_no_runs_directory_says_so_and_creates_nothing(
    clone: Path, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["runs", "--config", str(_relative_config(tmp_path))])

    assert result.exit_code == 0, result.output
    assert "no readable runs under runs" in result.output
    assert _neither_exists(clone)


def test_searching_with_no_symbol_index_says_how_to_build_one(clone: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["search", "apple", "--config", str(_relative_config(tmp_path))])

    assert result.exit_code == 5, result.output
    assert "map symbols sync" in result.output
    assert isinstance(result.exception, SystemExit)  # a sentence, not a traceback
    assert _neither_exists(clone)


def test_a_partial_export_works_with_no_runs_ledger_scores_or_prices(
    clone: Path, tmp_path: Path
) -> None:
    out = tmp_path / "export"

    result = runner.invoke(
        app,
        [
            "export",
            "--allow-partial",
            "--out",
            str(out),
            "--config",
            str(_relative_config(tmp_path)),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (out / "corpus.json").is_file()
    assert (out / "runs" / "by_source" / "corpus.json").is_file()
    assert _neither_exists(clone)


# --- commands that write -------------------------------------------------------


def test_the_first_run_creates_runs_itself(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _FakeFilings(NEWEST))

    result = runner.invoke(
        app, ["run", "AAPL", "--from-edgar", "--config", str(_relative_config(tmp_path))]
    )

    assert result.exit_code == 0, result.output
    (run,) = (clone / "runs").iterdir()
    assert (run / "forecast.json").is_file()
    assert (run / "manifest.json").is_file()
    assert (run / "trace.jsonl").is_file()


def test_every_var_writer_creates_its_own_directories(tmp_path: Path) -> None:
    """The ledger, the realised-bar pins, the scoring record, the symbol index, the
    price cache and the LLM cache each write somewhere under `var/`, and the first
    thing a fresh clone does to any of them is write."""
    var = tmp_path / "var"
    assert not var.exists()

    Ledger(var / "corpus" / "ledger.jsonl").append(
        LedgerEntry(ticker="AAPL", band="clean", filing_date=date(2026, 7, 30), status="complete")
    )
    RealisedPins(var / "corpus" / "realised_pins.jsonl").record(
        RealisedPin(
            ticker="AAPL",
            as_of=date(2026, 7, 31),
            horizon_days=5,
            realised_date=date(2026, 8, 7),
            realised_close=300.0,
        )
    )
    write_once(
        var / "corpus" / "scores",
        {"band": "clean", "split": "dev", "vintage": "2026-09-05", "forecast_digest": None},
    )
    sync(
        var / "symbols.sqlite",
        url=URL,
        user_agent=UA,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(200, content=FIXTURE.read_bytes())
            )
        ),
        throttle=Throttle(8.0, sleep=lambda _: None),
        today=lambda: date(2026, 8, 11),
    )
    _write_a_price_window(var / "prices")
    _write_an_llm_response(var / "llm")

    assert (var / "corpus" / "ledger.jsonl").is_file()
    assert (var / "corpus" / "realised_pins.jsonl").is_file()
    assert len(list((var / "corpus" / "scores").glob("*.json"))) == 1
    assert SqliteSymbolIndex(var / "symbols.sqlite").search("apple")
    assert list((var / "prices").rglob("*.parquet"))
    assert list((var / "llm").rglob("*.json"))


def _write_a_price_window(directory: Path) -> None:
    from mapf.data.cache import ParquetPriceCache
    from tests.unit.test_data_prices import END, START, StubProvider, _window

    ParquetPriceCache(
        StubProvider("yfinance", _window()), directory, today=lambda: date(2026, 9, 5)
    ).get_ohlcv("AAPL", START, END)


def _write_an_llm_response(directory: Path) -> None:
    from mapf.core.models import TrustedText
    from mapf.core.ports import LLMResponse, ModelInfo, SamplingParams
    from mapf.core.quarantine import quarantine
    from mapf.prompts.loader import FilePromptStore
    from mapf.providers.caching import CachingProvider

    model = ModelInfo(id="m", fingerprint="fp", fingerprint_source="digest")

    class _Inner:
        def list_models(self) -> tuple[ModelInfo, ...]:
            return (model,)

        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(text="ok", model_id="m")

    prompt = FilePromptStore().render(
        "intake",
        "v2",
        trusted={"ticker": TrustedText("AAPL"), "as_of_date": TrustedText("2026-07-30")},
        untrusted={"documents": quarantine("text")},
    )
    CachingProvider(_Inner(), directory).complete(
        model=model, prompt=prompt, sampling=SamplingParams(temperature=0.0)
    )
