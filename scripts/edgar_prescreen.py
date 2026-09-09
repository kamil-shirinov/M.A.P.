"""Which SEC filers publish Item 2.02 8-Ks, so a ticker can be screened offline.

**This is a FORWARD tool and must never become a selection instrument.** The corpus
in `corpus/frozen.json` is the pre-registration: it was selected by a seeded walk,
committed before any inference ran, and nothing produced here can retroactively
change what it contains. This exists to answer "is this ticker worth offering" for
`map run --from-edgar` and for ticker search — questions asked about runs that have
not happened yet. A candidate list built after the results are known is not a
selection rule, and using one as though it were would undo the reason the frozen
corpus is evidence at all.

**What it records, and what it does not.** One request per filer, reading only the
submissions `recent` block — the newest ~1,000 filings, roughly a year for an active
filer. So the answer is `item_202_in_recent`, never `has_ever_filed`: a company that
stopped reporting three years ago comes back `false`, which is a usable pre-screen
answer and a false statement about its history. The field is named for the block it
reads so the two cannot be confused downstream.

**Addressed by CIK, not by ticker.** The symbol index holds 10,398 tickers over
7,998 distinct filers -- the rest are share classes and dual listings -- and
submissions are addressed by CIK. Walking tickers would fetch 2,400 identical
documents for nothing. Tickers are joined back on locally.

**Resume, never overwrite.** Rows are appended as JSON Lines, one per filer, each
stamping its own `fetched_on`: EDGAR submissions change daily and a resumed walk
spans days, so a single header vintage would assert a uniformity the file does not
have. A re-run skips filers already recorded `ok`. A full refresh writes a NEW file
under a new vintage rather than rewriting rows -- an overwritten vintage is an
unreproducible answer, which is ADR 0012's argument about prices applied here.

Failures get rows too, typed. A silently skipped CIK either looks finished forever
or is re-walked forever, and neither is recoverable from the file afterwards.

    uv run python scripts/edgar_prescreen.py                 # walk, resuming
    uv run python scripts/edgar_prescreen.py --limit 50      # a taste first
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx
import typer

from mapf.bootstrap import build_filings, build_http_client, build_symbol_index
from mapf.core.errors import MapError
from mapf.data.filings import FilingsError
from mapf.settings import load

OUT = Path("var/filers")
DEFAULT_OUT = OUT / "item_202.jsonl"


def main(
    out: Path = DEFAULT_OUT,
    limit: int = typer.Option(0, help="Stop after this many filers. 0 for all of them."),
) -> None:
    settings = load()
    index = build_symbol_index(settings)

    by_cik: dict[int, list[str]] = defaultdict(list)
    for symbol in index:
        if symbol.cik is not None:
            by_cik[symbol.cik].append(symbol.ticker)

    done: set[int] = set()
    if out.is_file():
        for line in out.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # Only an `ok` row counts as done. Treating a failure as finished
            # would skip it forever on resume, which is how a transient 403
            # becomes a permanent silent exclusion.
            if row.get("status") == "ok":
                done.add(int(row["cik"]))

    todo = sorted(cik for cik in by_cik if cik not in done)
    if limit:
        todo = todo[:limit]
    typer.echo(
        f"{len(by_cik)} filers over {sum(len(t) for t in by_cik.values())} tickers; "
        f"{len(done)} already recorded; walking {len(todo)}"
    )
    if not todo:
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    started = monotonic()
    counts: dict[str, int] = defaultdict(int)

    with build_http_client(settings) as client, out.open("a", encoding="utf-8") as handle:
        filings = build_filings(settings, client)
        for position, cik in enumerate(todo, start=1):
            today = datetime.now(UTC).date().isoformat()
            row: dict[str, object] = {
                "cik": cik,
                "tickers": sorted(by_cik[cik]),
                "fetched_on": today,
                "block": "recent",
            }
            try:
                found = filings.recent_earnings_filings(cik)
            except FilingsError as err:
                text = str(err)
                status = (
                    "http_404"
                    if "404" in text
                    else "http_403"
                    if "403" in text
                    else "malformed"
                    if "malformed" in text
                    else "request_failed"
                )
                row |= {"status": status, "detail": text[:200]}
            except (MapError, httpx.HTTPError) as err:  # pragma: no cover - defensive
                row |= {"status": "request_failed", "detail": f"{type(err).__name__}: {err}"[:200]}
            else:
                row |= {
                    "status": "ok",
                    "item_202_in_recent": bool(found),
                    "count": len(found),
                    "most_recent": max((f.filed for f in found), default=None).isoformat()
                    if found
                    else None,
                }
            counts[str(row["status"])] += 1
            # Flushed per row: a walk killed at minute nine must leave nine minutes
            # of work behind it, not an empty buffer.
            handle.write(json.dumps(row, default=str) + "\n")
            handle.flush()

            if position % 250 == 0 or position == len(todo):
                rate = position / max(monotonic() - started, 1e-9)
                typer.echo(
                    f"  {position}/{len(todo)}  {rate:.1f}/s  "
                    f"{dict(sorted(counts.items()))}  eta "
                    f"{(len(todo) - position) / max(rate, 1e-9) / 60:.1f}m"
                )


if __name__ == "__main__":
    typer.run(main)
