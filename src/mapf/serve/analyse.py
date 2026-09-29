"""One ticker in, one run out, with the calibration decision attached.

The EDGAR half is `latest_exhibit`, which `map run --from-edgar` calls too. It is
shared rather than copied because the intake truncation budget is policy — an
EDGAR run and a corpus run of the same exhibit must see the same document — and
two copies of a policy are two things that can drift.

Nothing here decides whether a fan is drawn corrected. `mapf.eval.calibration`
does, and this module's job is to gather the facts that decision needs and hand
both to the caller. Keeping the gathering and the deciding apart is what lets the
decision be tested without a network, a model or a run.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from mapf.core.errors import MapError
from mapf.core.models import Document
from mapf.core.tokens import AgentBudget
from mapf.core.truncation import truncate
from mapf.eval.calibration import Applicability, applicability, sessions_between
from mapf.settings import ModelRegistry


@dataclass(frozen=True)
class Freeze:
    """What the frozen corpus knows about documents, for relating a live run.

    Two lookups rather than one, because they answer different questions. The
    document id is the identity the journal uses and is what decides the
    relation; the accession is what a reader recognises, and is what lets a page
    say "this is the filing already in the table above" rather than implying a
    live run always reads something new.
    """

    document_ids: frozenset[str]
    accessions: frozenset[str]

    @classmethod
    def load(cls, path: Path) -> Freeze:
        """Read the freeze, or an empty one if it is not there.

        Empty rather than refused: a missing freeze means the relation cannot be
        decided, which is the `unchecked` case the journal already has a word for,
        and it must not stop a run.
        """
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            by_accession = record.get("exhibits", {}).get("by_accession", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            return cls(document_ids=frozenset(), accessions=frozenset())
        return cls(
            document_ids=frozenset(
                str(e["document_id"]) for e in by_accession.values() if isinstance(e, dict)
            ),
            accessions=frozenset(str(a) for a in by_accession),
        )

    def relate(self, *, document_id: str | None, accession: str) -> str:
        """The live run's `corpus_relation`, by the journal's own rule.

        Never `ledger_item`: that names a run the ledger recorded, and this run is
        being made now. A live run over a frozen exhibit is a `repeat_of_exhibit`
        — same document, new run — which is exactly what re-running a corpus
        company before its next quarter produces.
        """
        if not self.document_ids and not self.accessions:
            return "unchecked"
        if document_id and document_id in self.document_ids:
            return "repeat_of_exhibit"
        # The accession is the fallback, not the primary: a re-fetch can differ by
        # a byte and change the hash while naming the same filing.
        if accession in self.accessions:
            return "repeat_of_exhibit"
        return "outside_corpus"


class AnalysisError(MapError):
    """The analysis could not be started, with a reason a reader can act on."""


@dataclass(frozen=True)
class Exhibit:
    """The filing that will be read, and the document itself."""

    accession: str
    filed: date
    document: Document
    truncated: str | None


def latest_exhibit(
    settings: Any, client: Any, ticker: str, *, days: int, build_filings: Any, build_exhibits: Any
) -> Exhibit:
    """The filer's most recent Item 2.02 within `days`, cut to the intake budget.

    NEVER falls back to the news path. The two answer different questions and a
    silent substitution would produce a forecast from unrelated documents under a
    request that asked for a filing.

    The adapters arrive as arguments rather than imports so this module stays
    testable without the bootstrap wiring, in the same spirit as `score_band`
    taking `prices` as a callable.
    """
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    filings = build_filings(settings, client).earnings_filings(ticker, start, end)
    if not filings:
        raise AnalysisError(
            f"no 8-K Item 2.02 filing for {ticker} between {start} and {end}. "
            "This does not fall back to news on its own."
        )
    latest = filings[-1]
    document = build_exhibits(settings, client).fetch(latest)
    intake = ModelRegistry(settings.models).spec("intake")
    text, record = truncate(
        document.text,
        budget_tokens=AgentBudget(
            agent="intake",
            context_tokens=intake.context_tokens,
            max_tokens=intake.sampling.max_tokens,
        ).document_budget,
    )
    # The id still hashes the bytes EDGAR served (ADR 0005); truncation is recorded
    # beside the hash and never folded into it.
    if record.applied:
        document = document.model_copy(update={"text": text})
    return Exhibit(
        accession=latest.accession,
        filed=latest.filed,
        document=document,
        truncated=record.describe() if record.applied else None,
    )


def company_screens(
    ticker: str,
    *,
    cik: int | None,
    median_dollar_volume: float | None,
    floor: float,
    has_exhibit: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The four company-level screens of ADR 0036 §1, as (failed, unevaluated).

    Split in two because they mean different things. A failed screen says the
    corpus would have rejected this company; an unevaluated one says nobody could
    tell. Both refuse the correction, and the screen says which it was — "we
    checked and it is too thin" is a different sentence from "we could not check".
    """
    failed: list[str] = []
    unevaluated: list[str] = []
    if cik is None:
        failed.append("no_cik")
    if median_dollar_volume is None:
        # No history is its own rejection reason in `corpus.selection`, not a
        # liquidity failure: the screen never ran.
        failed.append("no_price_history")
    elif median_dollar_volume < floor:
        failed.append(f"illiquid (median ${median_dollar_volume:,.0f}/day < ${floor:,.0f})")
    if not has_exhibit:
        failed.append("no_exhibit")
    return tuple(failed), tuple(unevaluated)


def decide(
    *,
    horizon_days: int,
    filed: date,
    anchor: date,
    sessions: list[date],
    failed_screens: tuple[str, ...],
    unevaluated: tuple[str, ...],
) -> Applicability:
    """Gather the three conditions and hand them to the gate.

    The anchor lag is counted in TRADING SESSIONS off the real price calendar, so
    a Friday filing anchored the following Monday is one session late rather than
    three days late. Only one of those is the panel's alignment.
    """
    return applicability(
        horizon_days=horizon_days,
        anchor_lag_sessions=sessions_between(sessions, filed, anchor),
        failed_screens=failed_screens,
        unscreened=unevaluated,
    )


@dataclass(frozen=True)
class Wiring:
    """Everything `run_analysis` needs from the outside world, as callables.

    Injected rather than imported for the reason `score_band` takes `prices` as a
    callable: it is what lets the whole path run against recorded fixtures with no
    model and no network (CLAUDE.md §6). The CLI passes the real builders; the
    tests pass stubs.
    """

    fetch_exhibit: Any
    execute_run: Any
    liquidity: Any
    symbol: Any
    correction: Any
    freeze: Any = None
    simulate: Any = None


# The band the chart draws. Two levels, not five: the point is that the forecast
# has a WIDTH, and a nest of ribbons makes the reader estimate which one matters.
BAND_LEVELS: tuple[float, ...] = (0.10, 0.25, 0.75, 0.90)


def band_prices(
    spot: float,
    quantiles: Sequence[float],
    *,
    mean: float,
    sigma: float,
    correction: Any = None,
) -> list[dict[str, float]]:
    """Quantiles of the predictive distribution, as prices.

    THE CORRECTION IS APPLIED HERE OR NOWHERE. ADR 0032's map is `z -> (z - a) / b`
    on the PIT side; the distribution that makes an outcome's corrected z come out
    right has mean `mu + a*sigma` and sd `b*sigma`. So a corrected band is
    genuinely wider than its raw twin — which is the whole reason the chart draws
    one. Without a band, a corrected fan and a raw fan are the same three lines
    and the amber box is warning about something invisible.

    `quantiles` are LOG returns, which is what `simulate` produces. Prices are
    `spot * exp(q)`; the scenario endpoints elsewhere use simple returns and the
    two must not be mixed.
    """
    out: list[dict[str, float]] = []
    for level, q in zip(BAND_LEVELS, quantiles, strict=True):
        moved = mean + correction.a * sigma + correction.b * (q - mean) if correction else q
        out.append({"level": level, "price": spot * math.exp(moved)})
    return out


def result_line(
    *,
    run_id: str,
    ticker: str,
    horizon: int,
    exhibit: Exhibit,
    forecast: Any,
    applies: Applicability,
    correction: Any,
    band: Sequence[dict[str, float]] = (),
    relation: str = "unchecked",
    price_date: date | None = None,
) -> dict[str, object]:
    """The final line of the stream.

    The marking travels WITH the numbers, in the same object, rather than being
    computed by whatever draws the fan. A result that reached a page without its
    marking would be an unmarked fan, and ADR 0036 §1 exists so that cannot happen.
    """
    return {
        "event": "result",
        "run_id": run_id,
        "ticker": ticker,
        "anchor": forecast.as_of.date().isoformat(),
        "spot": forecast.spot_price,
        # WHICH CLOSE THE SPOT IS. A run made before a session closes anchors on
        # the previous one — `last_close`, never an intraday quote — so the run's
        # own date and its price's date are different days, and the screen said
        # only the first. They coincided on the first live run, which hid it.
        "price_date": price_date.isoformat() if price_date else None,
        "horizon_days": horizon,
        "filed": exhibit.filed.isoformat(),
        "accession": exhibit.accession,
        "truncated": exhibit.truncated,
        "scenarios": [
            {
                "name": name,
                "weight": getattr(forecast.scenarios, name).probability_weight,
                "price_return": getattr(forecast.scenarios, name).price_return,
                "annualised_vol": getattr(forecast.scenarios, name).annualised_vol,
            }
            for name in ("bullish", "base_case", "bearish")
        ],
        "band": list(band),
        # Decided by the freeze, never asserted by the page (ADR 0036 section 2).
        "corpus_relation": relation,
        "marking": applies.marking,
        "corrected": applies.applies,
        "reasons": list(applies.reasons),
        "correction": {"a": correction.a, "b": correction.b, "form": correction.form},
    }


def run_analysis(
    ticker: str,
    horizon: int,
    *,
    wiring: Wiring,
    typical_seconds: int,
    usual_range_seconds: tuple[int, int] | None = None,
    liquidity_floor: float = 50_000_000.0,
) -> Iterator[dict[str, object]]:
    """One ticker to one streamed result, with the calibration decision attached.

    The order matters: the filing is announced before the long wait, so a reader
    knows WHICH document is being read during the five minutes in which nothing
    else happens.
    """
    yield {
        "event": "started",
        "ticker": ticker,
        "horizon_days": horizon,
        "typical_seconds": typical_seconds,
        # The range, not only the middle of it: a single number reads as a promise
        # and the middle eighty percent of real runs spans six to twelve minutes.
        "usual_range_seconds": list(usual_range_seconds) if usual_range_seconds else None,
        "stages": ["intake", "analyst", "structuralist"],
    }
    exhibit = wiring.fetch_exhibit(ticker)
    yield {
        "event": "filing",
        "accession": exhibit.accession,
        "filed": exhibit.filed.isoformat(),
        "truncated": exhibit.truncated,
    }

    run_id, forecast, window = yield from wiring.execute_run(ticker, horizon, exhibit)

    relation = (
        wiring.freeze.relate(
            document_id=getattr(exhibit.document, "id", None), accession=exhibit.accession
        )
        if wiring.freeze
        else "unchecked"
    )

    sessions = [bar.date for bar in window.bars]
    # The session the spot is the close of. `run.py` anchors on `last_close`, so
    # this is the last completed session and not necessarily the run's own date.
    price_date = sessions[-1] if sessions else None
    anchor = forecast.as_of.date()
    failed, unevaluated = company_screens(
        ticker,
        cik=wiring.symbol(ticker),
        median_dollar_volume=wiring.liquidity(ticker, sessions[0], anchor) if sessions else None,
        floor=liquidity_floor,
        has_exhibit=True,
    )
    applies = decide(
        horizon_days=horizon,
        filed=exhibit.filed,
        anchor=anchor,
        sessions=sessions,
        failed_screens=failed,
        unevaluated=unevaluated,
    )
    band: list[dict[str, float]] = []
    if wiring.simulate:
        sim = wiring.simulate(forecast, horizon)
        band = band_prices(
            forecast.spot_price,
            sim.quantiles(BAND_LEVELS),
            mean=sim.mean,
            sigma=sim.sigma,
            # Only where the gate allows it. A band widened by a correction that
            # does not apply here would be the picture making a claim the words
            # beside it refuse.
            correction=wiring.correction if applies.applies else None,
        )
    yield result_line(
        run_id=run_id,
        ticker=ticker,
        horizon=horizon,
        exhibit=exhibit,
        forecast=forecast,
        applies=applies,
        correction=wiring.correction,
        band=band,
        relation=relation,
        price_date=price_date,
    )
