"""`map export` — the whole readable state as flat JSON, for a front end with no server.

Static assets only. No process runs behind these files, so everything a page needs
must already be in them, and nothing here may need a query engine to interpret.

**Three rules this command holds to.**

*It says nothing the library does not already say.* The journal records are written
by `runs.as_dict`, the same serialiser `map runs --json` uses — two serialisers for
one record are two things that drift. No field is computed here, no aggregate is
taken, and no count is emitted that is not already a count somewhere. The manifest's
figures are identity fingerprints for staleness detection, not statistics about
forecasts — with one kind of exception, row counts of what was written. `runs.rows`
is the size of each population as it went into its file: the per-population count
`map runs` already prints, and never a total.

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
from collections.abc import Mapping
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
# 1.2.0 added `runs.rows` to the manifest; nothing was removed or renamed.
EXPORT_VERSION = "1.2.0"

# The Item 2.02 pre-screen. Written by scripts/edgar_prescreen.py, untracked like
# every other computed input.
FILERS = Path("var/filers/item_202.jsonl")

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


# How many names of a long list to show before the count carries the rest.
_NAMES_SHOWN = 6


def _print_absence(gap: Mapping[str, object]) -> None:
    """One absence, readable. Shared by the export and `--check` so they agree."""
    typer.secho(f"absent     {gap['what']}: {gap['reason']}", fg=typer.colors.YELLOW)
    items = gap.get("items")
    if isinstance(items, list) and items:
        shown = ", ".join(str(item) for item in items[:_NAMES_SHOWN])
        rest = len(items) - _NAMES_SHOWN
        typer.secho(
            f"           {shown}" + (f", and {rest} more" if rest > 0 else ""),
            fg=typer.colors.BRIGHT_BLACK,
        )


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
    filers_path: Path = typer.Option(
        FILERS,
        help=(
            "The Item 2.02 pre-screen. Without it a search can say whether a ticker "
            "exists but not whether its filer publishes earnings 8-Ks."
        ),
    ),
    snapshot: str = typer.Option(SCORING_VINTAGE, "--snapshot", help="Price vintage to read."),
    check: bool = typer.Option(
        False,
        "--check",
        help=(
            "Compare an existing export against this checkout and report what has "
            "moved. Writes nothing."
        ),
    ),
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
        if check:
            _check(out, settings, frozen=frozen, ledger_path=ledger_path, vintage=vintage)
            return
        absent: list[dict[str, object]] = []
        sizes: dict[str, int] = {}

        def missing(what: str, path: Path, reason: str, items: list[str] | None = None) -> None:
            """Record an absence, with any long list kept OUT of the sentence.

            `prices` names every company it could not find a window for, which on a
            fresh clone is all 120 — a wall of tickers in the middle of the output,
            printed again by `--check`. The list is worth keeping and worth not
            reading, so it goes in its own field and the printer shows a few.
            """
            gap: dict[str, object] = {"what": what, "path": str(path), "reason": reason}
            if items is not None:
                gap["items"] = sorted(items)
            absent.append(gap)

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
        rows_by_source: dict[str, int] = {}
        for source in SOURCES:
            entries = journal.of(source)
            rows_by_source[source] = len(entries)
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
                f"{vintage} snapshot",
                unpriced,
            )

        # -- the Item 2.02 pre-screen --
        #
        # Search has to answer a question the corpus cannot: of the 10,398 tickers
        # someone can type, which belong to a filer that publishes earnings 8-Ks at
        # all. Without this the funnel from searchable to forecastable to frozen
        # cannot be drawn, and every ticker outside the corpus looks equally viable.
        filers: list[dict[str, object]] = []
        if _require(
            filers_path,
            "the Item 2.02 pre-screen",
            "Run `uv run python scripts/edgar_prescreen.py`, or pass --allow-partial.",
            partial=allow_partial,
        ):
            filers = [
                json.loads(line)
                for line in filers_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            sizes["filers.json"] = _write(out / "filers.json", filers)
        else:
            missing(
                "filers",
                filers_path,
                "search can say whether a ticker exists but not whether its filer "
                "publishes Item 2.02 8-Ks",
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
            # NOT a run count, and named so it cannot be read as one. `resolved()`
            # is every item the ledger will not attempt again: 701 that completed
            # plus 8 that failed terminally, which is exactly why 8 held filings
            # carry an empty run list.
            "ledger": {"items_settled": len(resolved)},
            # One count per runs file, counted from the entries written into it, so it
            # cannot disagree with the file. Four counts and no total: a total would be
            # the export pooling the populations its files exist to keep apart, and a
            # consumer that wants one adds them where the pooling can be seen.
            "runs": {"rows": rows_by_source},
            "symbols": {"synced_on": synced_on.isoformat() if synced_on else None},
            "prices": {"snapshot": vintage.isoformat(), "companies": len(priced)},
            # Every row stamps its own `fetched_on`, and a resumed walk spans days,
            # so the vintages travel as the set they are rather than as one date.
            "filers": {
                "rows": len(filers),
                "vintages": sorted({str(r.get("fetched_on")) for r in filers}),
            },
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
            _print_absence(gap)
    except MapError as err:
        raise handle(err) from err


def _widest(prices: Any, cache_dir: Path, ticker: str, vintage: date) -> Any:
    """The longest window the vintage holds for one ticker.

    A company chart wants the most RECENT history the snapshot has, which is a
    different question from the one `covering` answers for an outcome — there the
    anchor is known and the window must span it. Here there is no anchor, so the
    range is read off the filenames the vintage actually stored.
    """
    directory = cache_dir / ticker.upper() / "split_adjusted" / vintage.isoformat()
    if not directory.is_dir():
        return None
    best: tuple[date, int, date] | None = None
    for path in directory.glob("*.parquet"):
        try:
            first, last = (date.fromisoformat(part) for part in path.stem.split("__"))
        except ValueError:
            continue
        # LATEST END first, span only as a tie-break. Selecting on span alone put
        # 92 of 120 charts a median 273 days behind data the same vintage held --
        # every window here is about 764 days, so span was effectively a tie and
        # the winner was whichever the filesystem yielded first. A company page
        # ending before the runs drawn on it is worse than a shorter one.
        candidate = (last, (last - first).days, first)
        if best is None or candidate > best:
            best = candidate
    return None if best is None else prices.covering(ticker, best[2], best[0])


def _live_identity(
    settings: Any, *, frozen: Path, ledger_path: Path, vintage: date
) -> dict[str, object]:
    """What an export written from this checkout right now would stamp.

    Assembled from the same read paths the export uses, so a difference here is a
    difference in the data and never in how the two were derived.
    """
    version = code_version()
    record = load_frozen(frozen) if frozen.is_file() else {}
    return {
        "freeze.version": record.get("freeze_version"),
        "freeze.digest": freeze_digest(record, truncated=False) if record else None,
        "code.commit": version.commit,
        "code.forecast_digest": version.forecast_digest,
        "ledger.items_settled": (
            len(Ledger(ledger_path).resolved()) if ledger_path.is_file() else None
        ),
        "symbols.synced_on": _synced_on(settings),
        "prices.snapshot": vintage.isoformat(),
    }


def _synced_on(settings: Any) -> str | None:
    if not settings.data.sec.symbols_db.is_file():
        return None
    synced = build_symbol_index(settings).synced_on()
    return synced.isoformat() if synced else None


def _exported_identity(manifest: dict[str, Any]) -> dict[str, object]:
    """The same keys, read back out of an export's manifest."""
    return {
        "freeze.version": manifest.get("freeze", {}).get("version"),
        "freeze.digest": manifest.get("freeze", {}).get("digest"),
        "code.commit": manifest.get("code", {}).get("commit"),
        "code.forecast_digest": manifest.get("code", {}).get("forecast_digest"),
        "ledger.items_settled": manifest.get("ledger", {}).get("items_settled"),
        "symbols.synced_on": manifest.get("symbols", {}).get("synced_on"),
        "prices.snapshot": manifest.get("prices", {}).get("snapshot"),
    }


def _check(out: Path, settings: Any, *, frozen: Path, ledger_path: Path, vintage: date) -> None:
    """Report what has moved under an export since it was written.

    Staleness is the cost of a copy, and a date alone does not make it visible: a
    reader seeing `exported_at` learns when, not whether it is still true. So the
    manifest records the IDENTITY of every input, and this re-derives all seven from
    the live checkout and names the ones that differ.

    It writes nothing and refuses nothing on its own account. A stale export is a
    fact to report, not an error to raise — whether it matters depends on which
    field moved, and only the reader knows that.
    """
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        raise fail(f"no export at {out}", 5, hint=f"Run `map export --out {out}` first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest.get("export_version") != EXPORT_VERSION:
        typer.secho(
            f"format     export is {manifest.get('export_version')}, this build writes "
            f"{EXPORT_VERSION} — re-export before comparing anything else",
            fg=typer.colors.RED,
        )

    typer.secho(f"exported   {manifest.get('exported_at')}", fg=typer.colors.GREEN)
    was, now = (
        _exported_identity(manifest),
        _live_identity(settings, frozen=frozen, ledger_path=ledger_path, vintage=vintage),
    )
    moved = {key: (was[key], now[key]) for key in now if was[key] != now[key]}
    for key in sorted(now):
        if key in moved:
            typer.secho(
                f"moved      {key}: {moved[key][0]} -> {moved[key][1]}", fg=typer.colors.YELLOW
            )
        else:
            typer.echo(f"same       {key}: {now[key]}")

    # Absences travel with the export, so a reader checking freshness also learns
    # what was never in it. Silence here would make an absence look like a gap.
    for gap in manifest.get("absent", []):
        _print_absence(gap)
    for gap in manifest.get("scores", {}).get("absent", []):
        _print_absence({"what": f"scores/{gap['split']}", "reason": gap["reason"]})

    typer.secho(
        f"check      {len(moved)} of {len(now)} inputs have moved"
        if moved
        else "check      nothing has moved; the export is current",
        fg=typer.colors.YELLOW if moved else typer.colors.GREEN,
    )
