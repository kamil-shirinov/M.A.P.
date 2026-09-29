"""Whether a run's anchor was a settled close or a live quote — Findings #64.

Three runs anchored on a bar that was still trading: KO at 15:52, and two AAPL
runs at 13:02 and 13:11. Every artifact around them said "close". The rule here
decides from what each run RECORDED about when it read its price, because the
obvious rule — compare `as_of` with the anchor session — is wrong for every
corpus run: their `as_of` sits at 00:00 UTC on the bar's own date, which is the
evening BEFORE that session opened.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from mapf.eval.journal import price_kind

BAR = date(2026, 8, 13)


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def test_a_live_run_before_the_settle_was_priced_mid_session() -> None:
    # 17:02 UTC is 13:02 in New York in August: the AAPL runs.
    assert price_kind(as_of=_utc(BAR, 17, 2), price_bar=BAR, fetched_on=BAR) == "intraday"


def test_the_bell_itself_is_not_yet_a_close() -> None:
    # 20:10 UTC is 16:10 in New York: after the bell, before the settle.
    assert price_kind(as_of=_utc(BAR, 20, 10), price_bar=BAR, fetched_on=BAR) == "intraday"


def test_a_live_run_after_the_settle_read_a_close() -> None:
    # 20:45 UTC is 16:45 in New York.
    assert price_kind(as_of=_utc(BAR, 20, 45), price_bar=BAR, fetched_on=BAR) == "close"


def test_a_fetch_on_a_later_day_read_a_settled_bar() -> None:
    """The next UTC day begins at 20:00 in New York, after the 16:30 settle, so a
    later fetch day proves the bar had settled. This is the KO run made at 04:48
    the next morning, which correctly anchored on the settled close."""
    kind = price_kind(
        as_of=datetime(2026, 9, 29, 8, 48, tzinfo=UTC),
        price_bar=date(2026, 9, 28),
        fetched_on=date(2026, 9, 29),
    )
    assert kind == "close"


def test_a_corpus_run_is_a_close_despite_an_as_of_before_the_session() -> None:
    """The trap. A corpus run's `as_of` is 00:00 UTC on the bar's own date — 20:00
    in New York the evening BEFORE — so judging by `as_of` alone would call every
    one of the 701 corpus runs intraday. Its `fetched_on` is weeks later, and even
    though #39 showed that field is a label rather than the real fetch day, the
    label precedes the real fetch, so it is a safe lower bound."""
    kind = price_kind(
        as_of=_utc(date(2025, 7, 30), 0, 0),
        price_bar=date(2025, 7, 30),
        fetched_on=date(2026, 8, 14),
    )
    assert kind == "close"


def test_no_fetch_date_is_unknown_rather_than_a_guess() -> None:
    assert price_kind(as_of=_utc(BAR, 12, 0), price_bar=BAR, fetched_on=None) == "unknown"


def test_a_fetch_before_the_bar_is_unknown() -> None:
    """Impossible for a real run. If a manifest says it, the manifest is wrong and
    the honest answer is that the kind cannot be told."""
    kind = price_kind(as_of=_utc(BAR, 12, 0), price_bar=BAR, fetched_on=date(2026, 8, 12))
    assert kind == "unknown"
