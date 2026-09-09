"""`map export` — the whole readable state as flat JSON, for a front end with no server.

Static assets only. No process runs behind these files, so everything a page needs
must already be in them, and nothing here may need a query engine to interpret.

**Three rules this command holds to.**

*It says nothing the library does not already say.* The journal records are written
by `runs.as_dict`, the same serialiser `map runs --json` uses — two serialisers for
one record are two things that drift. No field is computed here, no aggregate is
taken, and no count is emitted that is not already a count somewhere. The manifest's
figures are identity fingerprints for staleness detection, not statistics about
forecasts.

*Populations cannot be pooled.* Runs are written to `runs/by_source/<source>.json`,
mirroring `Journal`'s four accessors, and there is no combined file. A consumer that
wants everything must fetch four files and concatenate on purpose — the same shape
`Journal` enforces in memory, carried across the wire.

*An absence is stated, never left as a missing file.* Every input that could not be
read is named in the manifest with its reason. This matters most for the holdout: a
development scoring record is exported and a holdout one is not, and a reader must
learn *why* from the manifest rather than infer it from a gap. The same discipline
`outcome_status` applies to a missing close.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import typer

from mapf.bootstrap import build_price_snapshot, build_symbol_index
from mapf.cli.app import app, fail, handle
from mapf.cli.commands.evaluate import SCORES_DIR, SCORING_VINTAGE
from mapf.cli.commands.runs import FROZEN, LEDGER, as_dict
from mapf.core.errors import MapError
from mapf.core.provenance import code_version, freeze_digest
from mapf.corpus.ledger import Ledger
from mapf.corpus.record import load_frozen
from mapf.corpus.selection import Corpus
from mapf.eval.journal import SOURCES, LedgerItem, read_journal
from mapf.settings import load

# The export's own format version. A front end that reads these files is entitled
# to refuse a shape it does not know, and a version it can compare is the only way
# it can. Distinct from every vintage in the manifest, which describe the DATA.
EXPORT_VERSION = "1.0.0"

# Why the holdout has no scoring record, stated in the manifest rather than left
# for a reader to discover as a missing file (ADR 0031).
HOLDOUT_ABSENCE = {
    "split": "holdout",
    "exported": False,
    "reason": (
        "The holdout was scored once. Its per-item scores were printed once and "
        "were never persisted, and they cannot be recovered: `map evaluate "
        "--split holdout` is refused before anything is computed once the spend "
        "is recorded (ADR 0031). This is correct, not an omission."
    ),
    "survives_in": (
        "corpus/holdout_spend.jsonl (tracked; its git history is the record of the single spend)"
    ),
    "what_survives": [
        "the calibration coefficients and their fitted form",
        "the band, item count, date, commit, freeze version and price vintage",
    ],
}


def _write(path: Path, body: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, separators=(",", ":"), default=str)
    path.write_text(text, encoding="utf-8")
    return len(text)


def _require(path: Path, what: str, remedy: str, *, partial: bool) -> bool:
    """Present, or a named absence. Never an empty artifact.

    An empty index is indistinguishable from an index of nothing, and a front end
    reading one would show "no results" for every search rather than "this export
    has no symbols". `--allow-partial` records the absence; without it, stop.
    """
    if path.exists():
        return True
    if not partial:
        raise fail(f"{what} is missing at {path}", 5, hint=remedy)
    return False


@app.command()
def export(
    out: Path = typer.Option(..., "--out", help="Directory to write the export into."),
    frozen: Path = typer.Option(FROZEN, help="The frozen corpus."),
    ledger_path: Path = typer.Option(LEDGER, help="The corpus ledger."),
    runs_dir: Path = typer.Option(Path("runs"), help="Where run artifacts live."),
    scores_dir: Path = typer.Option(SCORES_DIR, help="Where scoring passes are recorded."),
    snapshot: str = typer.Option(SCORING_VINTAGE, "--snapshot", help="Price vintage to read."),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help=(
            "Write what can be read and record every absence in the manifest. "
            "Without it a missing input stops the export."
        ),
    ),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Write the corpus, the run journal, prices and scores as flat JSON."""
    try:
        settings = load([config] if config else None)
        vintage = date.fromisoformat(snapshot)
        absent: list[dict[str, object]] = []
        sizes: dict[str, int] = {}

        def missing(what: str, path: Path, reason: str) -> None:
            absent.append({"what": what, "path": str(path), "reason": reason})

        # -- corpus: the pre-registration, and the only input with no alternative --
        _require(frozen, "the frozen corpus", "Freeze and commit it first.", partial=False)
        record = load_frozen(frozen)
        corpus = Corpus.model_validate(record["corpus"])
        exhibits = record.get("exhibits", {})
        by_accession = exhibits.get("by_accession", {}) if isinstance(exhibits, dict) else {}
        frozen_exhibits = frozenset(
            str(e["document_id"]) for e in by_accession.values() if isinstance(e, dict)
        )

        # -- ledger --
        ledger_items: dict[str, LedgerItem] | None = None
        resolved: dict[Any, Any] = {}
        if _require(
            ledger_path,
            "the corpus ledger",
            "Run `map corpus run`, or pass --allow-partial to export without it.",
            partial=allow_partial,
        ):
            resolved = Ledger(ledger_path).resolved()
            ledger_items = {
                str(e.run_id): LedgerItem(ticker=e.ticker, band=e.band, filing_date=e.filing_date)
                for e in resolved.values()
                if e.run_id is not None
            }
        else:
            missing(
                "ledger",
                ledger_path,
                "runs cannot be related to corpus items; every corpus_relation reads "
                "'unchecked' and the per-company run lists are empty",
            )

        # -- symbols --
        symbols_db = settings.data.sec.symbols_db
        index = build_symbol_index(settings)
        names: dict[str, str] = {}
        synced_on: date | None = None
        if _require(
            symbols_db,
            "the symbol index",
            "Run `map symbols sync` once to build it.",
            partial=allow_partial,
        ):
            rows = [
                {"ticker": s.ticker, "name": s.name, "exchange": s.exchange, "cik": s.cik}
                for s in index
            ]
            names = {str(r["ticker"]): str(r["name"]) for r in rows}
            synced_on = index.synced_on()
            # Lazy: 10,398 rows the front end needs only once someone types. The
            # eager universe below is the 120 companies that have anything to show.
            sizes["symbols.json"] = _write(out / "symbols.json", rows)
        else:
            missing("symbols", symbols_db, "search cannot resolve tickers outside the corpus")

        # -- prices --
        snapshot_dir = settings.cache.price_dir
        prices = build_price_snapshot(settings, vintage)
        priced: list[str] = []
        unpriced: list[str] = []

        # -- the journal --
        journal = read_journal(
            runs_dir,
            snapshot=prices,
            today=datetime.now(UTC).date(),
            frozen_exhibits=frozen_exhibits,
            ledger_items=ledger_items,
        )
        runs_by_item: dict[tuple[str, str, str], list[str]] = {}
        for source in SOURCES:
            entries = journal.of(source)
            sizes[f"runs/by_source/{source}.json"] = _write(
                out / "runs" / "by_source" / f"{source}.json", [as_dict(e) for e in entries]
            )
            for entry in entries:
                if entry.ledger_item is not None:
                    key = (
                        entry.ledger_item.ticker,
                        entry.ledger_item.band,
                        entry.ledger_item.filing_date.isoformat(),
                    )
                    runs_by_item.setdefault(key, []).append(entry.run_id)

        # -- per company: every held filing, including the ones nothing ran --
        companies = []
        for plan in sorted(corpus.accepted, key=lambda p: p.ticker):
            held = corpus.filings_for(plan.ticker)
            companies.append(
                {
                    "ticker": plan.ticker,
                    "name": names.get(plan.ticker),
                    "cik": plan.cik,
                    "split": plan.split,
                    "filings": [
                        {
                            "filed": f.filed.isoformat(),
                            "accession": f.accession,
                            "band": f.band,
                            "split": f.split,
                            # The exhibit fact and the run fact are separate. A held
                            # filing with no run is exported with an empty list, not
                            # omitted: the corpus holds 709 and 701 were executed,
                            # and a page showing 701 would misstate the record.
                            "runs": sorted(
                                runs_by_item.get((f.ticker, f.band, f.filed.isoformat()), [])
                            ),
                        }
                        for f in held
                    ],
                }
            )
            # `_widest`, not `covering(vintage, vintage)`: the stored windows end
            # near each filing's anchor and almost never span the snapshot's own
            # date, so asking for one that does would return nothing for nearly
            # every company. A chart wants the longest history the vintage holds.
            series = _widest(prices, snapshot_dir, plan.ticker, vintage)
            if series is None:
                unpriced.append(plan.ticker)
                continue
            priced.append(plan.ticker)
            sizes.setdefault("prices/", 0)
            sizes["prices/"] += _write(
                out / "prices" / f"{plan.ticker}.json",
                {
                    "ticker": series.ticker,
                    "provider": series.provider,
                    "adjustment": series.adjustment,
                    "snapshot": vintage.isoformat(),
                    "bars": [[b.date.isoformat(), b.close] for b in series.bars],
                },
            )
        sizes["corpus.json"] = _write(out / "corpus.json", companies)
        sizes["universe.json"] = _write(
            out / "universe.json",
            [{"ticker": c["ticker"], "name": c["name"], "split": c["split"]} for c in companies],
        )
        if unpriced:
            missing(
                "prices",
                snapshot_dir,
                f"{len(unpriced)} of {len(companies)} companies have no window in the "
                f"{vintage} snapshot: {', '.join(sorted(unpriced))}",
            )

        # -- scoring records --
        records = []
        if scores_dir.is_dir():
            for path in sorted(scores_dir.glob("*.json")):
                body = json.loads(path.read_text(encoding="utf-8"))
                name = f"scores/{path.name}"
                sizes[name] = _write(out / "scores" / path.name, body)
                # Content-addressed exactly as the filename is, so a reader can tell
                # from the manifest alone whether this pass matches the code state
                # the rest of the export came from.
                records.append(
                    {
                        "file": name,
                        "band": body.get("band"),
                        "split": body.get("split"),
                        "vintage": body.get("vintage"),
                        "forecast_digest": body.get("forecast_digest"),
                        "freeze_version": body.get("freeze_version"),
                        "n": body.get("n"),
                    }
                )
        else:
            missing("scores", scores_dir, "no scoring pass has been recorded")

        version = code_version()
        manifest = {
            "export_version": EXPORT_VERSION,
            "exported_at": datetime.now(UTC).date().isoformat(),
            # Identity, for staleness. Each is what its own source already stamps —
            # the export mints none of them, because a single export-wide vintage
            # would flatten five different moments into one date and assert a
            # uniformity that does not exist.
            "freeze": {
                "version": record.get("freeze_version"),
                "digest": freeze_digest(record, truncated=False),
            },
            "code": {"commit": version.commit, "forecast_digest": version.forecast_digest},
            "ledger": {"resolved": len(resolved)},
            "symbols": {"synced_on": synced_on.isoformat() if synced_on else None},
            "prices": {"snapshot": vintage.isoformat(), "companies": len(priced)},
            "scores": {"records": records, "absent": [HOLDOUT_ABSENCE]},
            "absent": absent,
            "files": dict(sorted(sizes.items())),
        }
        _write(out / "manifest.json", manifest)

        total = sum(sizes.values())
        typer.secho(f"export     {out}  ({total / 1e6:.2f} MB)", fg=typer.colors.GREEN)
        for name, size in sorted(sizes.items()):
            typer.echo(f"           {name:<34} {size / 1e3:>8.1f} KB")
        for gap in absent:
            typer.secho(f"absent     {gap['what']}: {gap['reason']}", fg=typer.colors.YELLOW)
    except MapError as err:
        raise handle(err) from err


def _widest(prices: Any, cache_dir: Path, ticker: str, vintage: date) -> Any:
    """The longest window the vintage holds for one ticker.

    A company chart wants as much history as the snapshot has, which is a different
    question from the one `covering` answers for an outcome — there the anchor is
    known and the window must span it. Here there is no anchor, so the range is
    read off the filenames the vintage actually stored.
    """
    directory = cache_dir / ticker.upper() / "split_adjusted" / vintage.isoformat()
    if not directory.is_dir():
        return None
    best: tuple[int, date, date] | None = None
    for path in directory.glob("*.parquet"):
        try:
            first, last = (date.fromisoformat(part) for part in path.stem.split("__"))
        except ValueError:
            continue
        span = (last - first).days
        if best is None or span > best[0]:
            best = (span, first, last)
    return None if best is None else prices.covering(ticker, best[1], best[2])
