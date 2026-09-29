"""`map serve` — the app and one endpoint, on one loopback origin.

Progress comes from the run's own `trace.jsonl`, which the pipeline writes a line
to as each agent finishes. That file is the audit trail (CLAUDE.md §6), so the
progress display is reading the artifact rather than guessing: a stage is reported
done when the trace says it is, and never on a timer.

The expected duration is measured, not assumed. Eleven recent traces on this
hardware span 261 to 646 seconds with a median of 397, and that median travels
with the first progress line so the page can say how long this usually takes
instead of showing a spinner with no scale.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from collections.abc import Generator, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import typer

from mapf.bootstrap import (
    build_exhibits,
    build_filings,
    build_http_client,
    build_llm_provider,
    build_market_data,
    build_run,
    build_symbol_index,
)
from mapf.cli.app import app, fail, handle
from mapf.core.errors import MapError
from mapf.core.hashing import new_run_id
from mapf.data.liquidity import MarketLiquidity
from mapf.eval.calibration import CalibrationError, load_correction
from mapf.eval.montecarlo import simulate
from mapf.pipeline.run import RunRequest, execute
from mapf.serve.analyse import (
    AnalysisError,
    Exhibit,
    Freeze,
    Wiring,
    latest_exhibit,
    run_analysis,
)
from mapf.serve.server import Config, build
from mapf.settings import ModelRegistry, load

# Measured from the 701 completed corpus runs that recorded an `elapsed_s`, which
# is the runner's own wall clock. Carried to the page so a ten-minute wait reads
# as expected rather than as a hang.
#
# NOT from trace spans, which is what an earlier version used. A trace's first
# line is written when the FIRST AGENT FINISHES, so the span from first line to
# last excludes everything before it — for the one live run so far, 495 seconds
# of span against 601 of wall clock. The span is a lower bound on the run, and it
# was being reported as the run.
#
# AND NOT A MEDIAN ALONE. "About eight minutes" invites being read as a promise
# when the middle eighty percent spans six to twelve, so the range travels too
# and the page states both.
TYPICAL_RUN_SECONDS = 457
RUN_SECONDS_P10 = 331
RUN_SECONDS_P90 = 692
UI_ROOT = Path("ui")


def _drain(path: Path, emit: list[dict[str, object]], seen: list[int]) -> None:
    """Emit any trace lines past `seen[0]`, and advance it.

    The counter is shared with the watcher thread rather than passed by value,
    because the final drain must not resend what the watcher already sent. Passing
    an int made every stage of a slow run appear twice.

    Tolerant by construction: the file does not exist until the first stage
    finishes, and a line can be read half-written. Decoration must never break a
    run, so both cases simply mean "nothing new yet" and are retried.
    """
    try:
        if not path.is_file():
            return
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for line in lines[seen[0] :]:
            record = json.loads(line)
            emit.append(
                {
                    "event": "progress",
                    "stage": str(record.get("stage")),
                    "detail": "cached" if record.get("cache_hit") else "",
                }
            )
        seen[0] = len(lines)
    except (OSError, json.JSONDecodeError):
        return


def _trace_watcher(
    path: Path, emit: list[dict[str, object]], stop: threading.Event, seen: list[int]
) -> None:
    """Report each agent as the run's own trace records it.

    Polled rather than watched: the file does not exist until the first stage
    finishes, and a poll that starts before it exists is simpler than arranging to
    be told when it appears.

    The poll is NOT the only read. A run that finishes inside one poll interval —
    a fully cached one does — would otherwise be reported with no stages at all,
    so the caller drains once more after the worker joins.
    """
    while not stop.is_set():
        _drain(path, emit, seen)
        stop.wait(0.5)


@app.command()
def serve(
    port: int = typer.Option(8765, help="Loopback port for the app and the endpoint."),
    ui_dir: Path = typer.Option(UI_ROOT, help="The app directory to serve."),
    edgar_days: int = typer.Option(120, help="How far back to look for an Item 2.02."),
    frozen: Path = typer.Option(
        Path("corpus/frozen.json"),
        help="The frozen corpus, for relating a live run to it (ADR 0036 section 2).",
    ),
    spend_path: Path = typer.Option(
        Path("corpus/holdout_spend.jsonl"),
        help="The record carrying the fitted calibration terms (ADR 0032).",
    ),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the app on start."),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Serve the app and `POST /analyse` from one loopback origin.

    Every analysis is a real run: it costs minutes of local inference and writes a
    permanent entry to the journal. There is no discard.
    """
    try:
        settings = load([config] if config else None)
        if not ui_dir.is_dir():
            raise fail(f"no app directory at {ui_dir}", 5, hint="Point --ui-dir at `ui/`.")
        try:
            correction = load_correction(spend_path)
        except CalibrationError as error:
            raise fail(
                str(error), 5, hint="The fitted coefficients live in the spend record."
            ) from error

        def fetch_exhibit(ticker: str) -> Exhibit:
            with build_http_client(settings) as client:
                return latest_exhibit(
                    settings,
                    client,
                    ticker,
                    days=edgar_days,
                    build_filings=build_filings,
                    build_exhibits=build_exhibits,
                )

        def execute_run(
            ticker: str, horizon: int, exhibit: Exhibit
        ) -> Generator[dict[str, object], None, tuple[str, Any, Any]]:
            """Run the three agents, streaming each stage as the TRACE records it.

            The trace is the audit trail, written a line per agent as the run goes.
            Reading progress off it means a stage is reported done because the run
            said so, never because enough seconds passed.
            """
            provider = build_llm_provider(settings, fixtures=None)
            registry = ModelRegistry(settings.models)
            resolved = {str(k): v for k, v in registry.resolve_all(provider.list_models()).items()}
            run_id = new_run_id()
            wiring = build_run(settings, provider=provider, resolved=resolved, run_id=run_id)

            emitted: list[dict[str, object]] = []
            seen = [0]
            trace_path = wiring.runs_dir / str(run_id) / "trace.jsonl"
            stop = threading.Event()
            threading.Thread(
                target=_trace_watcher,
                args=(trace_path, emitted, stop, seen),
                daemon=True,
            ).start()

            done: list[object] = []
            failed: list[BaseException] = []

            def work() -> None:
                try:
                    done.append(
                        execute(
                            RunRequest(
                                ticker=ticker,
                                horizon_days=horizon,
                                documents=(exhibit.document,),
                                history_days=settings.data.history_days,
                                run_id=run_id,
                                as_of=datetime.now(UTC),
                            ),
                            agents=wiring.agents,
                            market=wiring.market,
                            dividends=wiring.dividends,
                            trace=wiring.trace,
                            runs_dir=wiring.runs_dir,
                            allow_nondeterministic=wiring.allow_nondeterministic,
                            # Positively recorded. The relation to the frozen corpus
                            # is then whatever the journal's own check makes of the
                            # document (ADR 0036 §2) — never asserted here.
                            document_source="edgar",
                            # Recorded now because nothing downstream can look it
                            # up: the journal resolves names from the frozen 120.
                            company_name=company_name(ticker),
                        )
                    )
                except BaseException as error:  # noqa: BLE001 - re-raised below
                    failed.append(error)

            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            while worker.is_alive() or emitted:
                while emitted:
                    yield emitted.pop(0)
                if worker.is_alive():
                    time.sleep(0.2)
            stop.set()
            worker.join(timeout=5)
            # One last read, synchronously. A run shorter than a poll interval —
            # every stage a cache hit — finishes with the watcher never having seen
            # the file, and reporting no stages for a run that ran three would be
            # the display contradicting the trace.
            _drain(trace_path, emitted, seen)
            while emitted:
                yield emitted.pop(0)
            if failed:
                raise failed[0]
            outcome = done[0]
            return str(run_id), outcome.forecast, outcome.window  # type: ignore[attr-defined]

        screen = MarketLiquidity(build_market_data(settings))
        symbols = build_symbol_index(settings)

        def liquidity(ticker: str, start: date, end: date) -> float | None:
            try:
                return screen.median_dollar_volume(ticker, start, end)
            except MapError:
                # An unevaluated screen is a failing condition, not a pass; the gate
                # is told `None` and refuses the correction for it.
                return None

        def symbol_cik(ticker: str) -> int | None:
            found = symbols.get(ticker)
            return getattr(found, "cik", None) if found else None

        def company_name(ticker: str) -> str | None:
            found = symbols.get(ticker)
            return getattr(found, "name", None) if found else None

        wiring = Wiring(
            fetch_exhibit=fetch_exhibit,
            execute_run=execute_run,
            liquidity=liquidity,
            symbol=symbol_cik,
            correction=correction,
            freeze=Freeze.load(frozen),
            # The same `simulate` the scorer runs, with the same default paths and
            # the same seed, so the band on screen is the distribution that would
            # be scored and not a second one drawn for the picture.
            simulate=lambda forecast, horizon: simulate(forecast.scenarios, horizon_days=horizon),
        )

        def analyse(ticker: str, horizon: int) -> Iterator[dict[str, object]]:
            return run_analysis(
                ticker,
                horizon,
                wiring=wiring,
                typical_seconds=TYPICAL_RUN_SECONDS,
                usual_range_seconds=(RUN_SECONDS_P10, RUN_SECONDS_P90),
            )

        server = build(Config(root=ui_dir, port=port, analyse=analyse))
        url = f"http://127.0.0.1:{port}/analyse.html"
        typer.secho(f"serve      {url}", fg=typer.colors.GREEN)
        typer.echo("           every analysis is a real run and a permanent journal entry")
        lo, hi = round(RUN_SECONDS_P10 / 60), round(RUN_SECONDS_P90 / 60)
        typer.echo(f"           a run usually takes {lo} to {hi} minutes on this hardware")
        typer.echo("           ctrl-c to stop")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            typer.echo()
        finally:
            server.server_close()
    except (MapError, AnalysisError) as err:
        raise handle(err) from err
