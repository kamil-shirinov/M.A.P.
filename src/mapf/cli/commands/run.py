"""`map run` — the whole pipeline, once."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from mapf.bootstrap import build_http_client, build_llm_provider, build_run
from mapf.cli.app import app, fail, handle
from mapf.core.errors import MapError
from mapf.core.hashing import new_run_id
from mapf.data.news import load_corpus
from mapf.pipeline.run import RunRequest, execute
from mapf.settings import ModelRegistry, load


@app.command()
def run(
    ticker: str = typer.Argument(..., help="Ticker to forecast, e.g. AAPL."),
    horizon: int = typer.Option(21, "--horizon", help="Forecast horizon in trading days."),
    news_dir: Path | None = typer.Option(None, help="Override the configured news directory."),
    fixtures: Path | None = typer.Option(
        None, help="Replay recorded LLM fixtures instead of calling a server."
    ),
    record_to: Path | None = typer.Option(
        None,
        "--record-to",
        help=(
            "Record every LLM exchange to this directory as replayable fixtures. "
            "The destination is mandatory: a production command must never write "
            "into tests/fixtures/ on its own."
        ),
    ),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Produce a validated forecast, a trace, a manifest and a chart."""
    try:
        settings = load([config] if config else None)
        if not 1 <= horizon <= 252:
            raise fail(f"--horizon must be between 1 and 252, got {horizon}", 2)

        corpus_dir = news_dir or settings.news.dir
        with build_http_client(settings) as client:
            documents = load_corpus(
                corpus_dir,
                settings.news.rss_urls,
                client=client if settings.news.rss_urls else None,
            )
        if not documents:
            raise fail(
                f"no news found in {corpus_dir}",
                5,
                hint=(
                    "Put .txt or .md files there, or set news.rss_urls in "
                    "config/default.toml. A forecast needs something to reason from."
                ),
            )

        provider = build_llm_provider(settings, fixtures=fixtures)
        if record_to is not None:
            from mapf.providers.fake import RecordingProvider

            provider = RecordingProvider(provider, record_to)

        registry = ModelRegistry(settings.models)
        resolved = {str(k): v for k, v in registry.resolve_all(provider.list_models()).items()}

        run_id = new_run_id()
        wiring = build_run(settings, provider=provider, resolved=resolved, run_id=run_id)
        result = execute(
            RunRequest(
                ticker=ticker,
                horizon_days=horizon,
                documents=documents,
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
        )

        typer.secho(f"run {run_id}", fg=typer.colors.GREEN)
        typer.echo(
            f"  spot        {result.forecast.spot_price:.2f} "
            f"({result.window.provider}, {result.window.adjustment})"
        )
        for label in ("bullish", "base_case", "bearish"):
            scenario = getattr(result.forecast.scenarios, label)
            typer.echo(
                f"  {label:11} p={scenario.probability_weight:.2f}  "
                f"{scenario.price_modifier_pct:+.1f}%  vol={scenario.annualised_vol:.2f}"
            )
        if not result.manifest.dividends.known:
            typer.secho(
                "  note: ex-dividend dates in the forecast window are unknown; "
                "Phase 2 must not read that as 'none' (ADR 0013).",
                fg=typer.colors.YELLOW,
            )
        elif result.manifest.dividends.ex_dates:
            typer.secho(
                f"  note: {len(result.manifest.dividends.ex_dates)} ex-dividend date(s) "
                f"in the window, total {result.manifest.dividends.total_amount:.4f}. "
                "A split-adjusted series keeps that drop (ADR 0013).",
                fg=typer.colors.YELLOW,
            )
        typer.echo(f"  artifacts   {result.run_dir}")
    except MapError as err:
        raise handle(err) from err
