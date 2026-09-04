"""The realised-bar pin store.

Append-only JSONL beside the ledger, for the same reason the ledger is: a pin that
can be quietly rewritten is not a pin. Lives in `corpus` rather than `eval` so the
scoring layer keeps taking its IO as injected callables and never imports a store.

`SpotDriftError` anchors what a forecast was produced from. This anchors what it was
scored against, which cannot be recorded at forecast time because the outcome has
not happened yet — so the first scoring takes the pin and every later one is checked
against it (ADR pending; see git note record 12).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from mapf.eval.scorer import RealisedPin


class RealisedPins:
    """Read-through store of the outcome bar each item was first scored against."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._pins: dict[tuple[str, date, int], RealisedPin] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.is_file():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            pin = RealisedPin(
                ticker=row["ticker"],
                as_of=date.fromisoformat(row["as_of"]),
                horizon_days=int(row["horizon_days"]),
                realised_date=date.fromisoformat(row["realised_date"]),
                realised_close=float(row["realised_close"]),
            )
            # Last write wins on replay, but a second line for one key should never
            # exist: `record` refuses to append over a key already held.
            self._pins[pin.key] = pin

    def get(self, ticker: str, as_of: date, horizon_days: int) -> RealisedPin | None:
        self._load()
        return self._pins.get((ticker, as_of, horizon_days))

    def record(self, pin: RealisedPin) -> None:
        """Append a pin for an item that has none. Never overwrites: a pin that can
        be replaced by re-running the thing it constrains constrains nothing."""
        self._load()
        if pin.key in self._pins:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ticker": pin.ticker,
                        "as_of": pin.as_of.isoformat(),
                        "horizon_days": pin.horizon_days,
                        "realised_date": pin.realised_date.isoformat(),
                        "realised_close": pin.realised_close,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        self._pins[pin.key] = pin

    def __len__(self) -> int:
        self._load()
        return len(self._pins)
